"""Parser de texto plano y Markdown (.md, .markdown, .txt).

Extrae estructura; NO limpia. El marcado inline se conserva literal
(**negrita**, [texto](url), `codigo`) y las lineas de un parrafo se unen con
"\\n", no con espacio: el soft-wrap original es informacion que decide la capa
cleaning/, no este modulo.

Los indices de linea de `ancla` son 1-based, para casar con lo que muestran los
editores, `grep -n` y los mensajes de error.
"""

from __future__ import annotations

import codecs
import logging
import re
from pathlib import Path
from typing import Any

from parser.models import Block, ParsedDocument
from parser.parsers.base import BaseParser, ParserError

logger = logging.getLogger(__name__)

_RE_ATX = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
_RE_CIERRE_ATX = re.compile(r"\s+#+\s*$")
_RE_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})\s*([^\s`]*)\s*$")
_RE_LISTA = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
_RE_SEP_TABLA = re.compile(r"^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$")
_RE_PIPE = re.compile(r"(?<!\\)\|")
_RE_CITA = re.compile(r"^ {0,3}>\s?")
_RE_NUMERACION = re.compile(r"^(\d+(?:\.\d+)*)[.)]?\s+\S")
_RE_CLAVE_YAML = re.compile(r"^([A-Za-z_][\w.-]*)\s*:\s*(.*)$")

_LARGO_MAX_HEADING_TXT = 80
_PALABRAS_MAX_HEADING_TXT = 12
_LARGO_MAX_TITULO_TXT = 120
_NIVEL_MAX = 6
_SANGRIA_MIN_CONTINUACION = 2

# Pila de secciones: (nivel, texto del encabezado).
Pila = list[tuple[int, str]]


class TextParser(BaseParser):
    """Parser de Markdown y texto plano."""

    EXTENSIONES = (".md", ".markdown", ".txt")
    FORMATO = "md"
    MAPA_FORMATOS = {".txt": "txt"}

    # ------------------------------------------------------------------ API

    def parse(self, path: Path, doc_id: str, fenomeno: int) -> ParsedDocument:
        """Parsea un .md/.markdown/.txt a la representacion intermedia."""
        doc = self._nuevo_documento(path, doc_id, fenomeno)
        texto, encoding, bom = self._leer(path)
        doc.meta_extra["encoding"] = encoding
        doc.meta_extra["bom"] = bom

        # Normalizar saltos de linea no es limpieza de texto sino decodificacion
        # estructural: un \r colgando rompe los regex anclados en $. Se usa
        # split("\n") y no splitlines() porque este ultimo tambien parte en \v,
        # \f, \x1c y U+2028, lo que descuadraria los indices de `ancla`.
        lineas = texto.replace("\r\n", "\n").replace("\r", "\n").split("\n")

        if path.suffix.lower() == ".txt":
            doc.meta_extra["modo"] = "plano"
            doc.blocks = self._parsear_plano(lineas)
        else:
            doc.meta_extra["modo"] = "markdown"
            inicio = self._extraer_front_matter(lineas, doc)
            doc.blocks = self._parsear_markdown(lineas, inicio, doc)

        doc.titulo = self._deducir_titulo(doc, lineas)

        if not doc.blocks:
            # No es un ParserError: la evaluacion empareja por `fuente`, asi que
            # cada archivo del corpus debe aparecer en la salida. "Vacio" es un
            # dato, no un fallo.
            doc.meta_extra["vacio"] = True
            doc.errores.append("documento vacio: 0 bloques extraidos")
            self.logger.warning("documento vacio: %s", doc.fuente)
        return doc

    # -------------------------------------------------------------- Lectura

    def _leer(self, path: Path) -> tuple[str, str, bool]:
        """Devuelve (texto, encoding usado, tenia BOM).

        El BOM se detecta por bytes en lugar de confiar en el orden
        utf-8 -> utf-8-sig: un archivo con BOM decodifica SIN error como utf-8
        y deja un \\ufeff invisible al inicio que impide reconocer el primer
        encabezado o la apertura del front-matter.
        """
        datos = path.read_bytes()
        if datos.startswith(codecs.BOM_UTF8):
            return datos.decode("utf-8-sig"), "utf-8-sig", True
        for encoding in ("utf-8", "latin-1"):
            try:
                return datos.decode(encoding), encoding, False
            except UnicodeDecodeError:
                self.logger.debug("%s no decodifica como %s", path.name, encoding)
        # Inalcanzable: latin-1 decodifica cualquier secuencia de bytes.
        raise ParserError(f"no se pudo decodificar {path.name}")

    # ------------------------------------------------------------- Markdown

    def _extraer_front_matter(self, lineas: list[str], doc: ParsedDocument) -> int:
        """Guarda el front-matter en meta_extra y devuelve la linea de inicio.

        El front-matter es metadata: emitirlo como parrafos inyectaria ruido
        tipo "layout: post" en el indice vectorial. Si no hay cierre no se
        considera front-matter, para que un documento que abre con una regla
        horizontal no se pierda entero.
        """
        if not lineas or lineas[0].rstrip() != "---":
            return 0
        for j in range(1, len(lineas)):
            if lineas[j].rstrip() in ("---", "..."):
                crudo = "\n".join(lineas[1:j])
                doc.meta_extra["front_matter"] = crudo
                doc.meta_extra["front_matter_datos"] = self._claves_front_matter(crudo)
                return j + 1
        return 0

    def _claves_front_matter(self, crudo: str) -> dict[str, str]:
        """Parseo plano de las claves de primer nivel. Sin PyYAML a proposito."""
        datos: dict[str, str] = {}
        for linea in crudo.split("\n"):
            if linea[:1].isspace():  # anidamiento: fuera de alcance
                continue
            match = _RE_CLAVE_YAML.match(linea.strip())
            if match:
                datos[match.group(1)] = match.group(2).strip().strip("\"'")
        return datos

    def _parsear_markdown(
        self, lineas: list[str], inicio: int, doc: ParsedDocument
    ) -> list[Block]:
        """Maquina de estados de una pasada. El orden de las ramas importa."""
        bloques: list[Block] = []
        pila: Pila = []
        buf: list[str] = []
        buf_inicio = 0
        buf_cita = False
        idx_tabla = 0

        def flush() -> None:
            nonlocal buf, buf_inicio, buf_cita
            if buf and "".join(buf).strip():
                ancla: dict[str, Any] = {
                    "linea": buf_inicio,
                    "linea_fin": buf_inicio + len(buf) - 1,
                }
                if buf_cita:
                    ancla["cita"] = True
                bloques.append(
                    self._bloque(
                        "paragraph",
                        "\n".join(buf),
                        ancla=ancla,
                        seccion_path=self._rutas(pila),
                    )
                )
            buf = []
            buf_cita = False

        i = inicio
        while i < len(lineas):
            linea = lineas[i]

            # 1-2. Bloques de codigo. Van primero: es lo que impide que un
            # "# comentario" de Python dentro del fence acabe como heading.
            fence = _RE_FENCE.match(linea)
            if fence:
                flush()
                bloque, i = self._consumir_codigo(lineas, i, pila, doc)
                if bloque is not None:
                    bloques.append(bloque)
                continue

            # 3. Linea en blanco.
            if not linea.strip():
                flush()
                i += 1
                continue

            # 4. Encabezado ATX. Se exige espacio tras las almohadillas, asi
            # que "#hashtag" no es un encabezado.
            atx = _RE_ATX.match(linea)
            if atx:
                flush()
                nivel = len(atx.group(1))
                texto = _RE_CIERRE_ATX.sub("", atx.group(2) or "").strip()
                ancestros = self._empujar_seccion(pila, nivel, texto)
                if texto:
                    bloques.append(
                        self._bloque(
                            "heading",
                            texto,
                            nivel=nivel,
                            ancla={"linea": i + 1, "linea_fin": i + 1, "estilo": "atx"},
                            seccion_path=ancestros,
                        )
                    )
                i += 1
                continue

            # 5. Subrayado setext. Solo cuenta si hay un parrafo pendiente: si
            # el buffer esta vacio, la linea previa era blanca o un elemento de
            # bloque, y entonces "---" es una regla horizontal.
            nivel_setext = self._tipo_subrayado(linea)
            if nivel_setext is not None and buf:
                # A diferencia de CommonMark se toma solo la ULTIMA linea del
                # parrafo: subrayar sin linea en blanco previa fabricaria si no
                # un heading de varias lineas que envenena los seccion_path
                # de todos sus descendientes.
                texto = buf.pop().strip()
                linea_heading = buf_inicio + len(buf)
                flush()
                ancestros = self._empujar_seccion(pila, nivel_setext, texto)
                bloques.append(
                    self._bloque(
                        "heading",
                        texto,
                        nivel=nivel_setext,
                        ancla={
                            "linea": linea_heading,
                            "linea_fin": i + 1,
                            "estilo": "setext",
                        },
                        seccion_path=ancestros,
                    )
                )
                i += 1
                continue

            # 6. Regla horizontal. Antes que la lista: "* * *" casa con el
            # regex de item. No emite bloque, pero cierra el parrafo pendiente.
            if self._es_hr(linea):
                flush()
                i += 1
                continue

            # 7. Tabla.
            if self._inicia_tabla(lineas, i):
                flush()
                filas, i = self._consumir_tabla(lineas, i, idx_tabla, pila)
                bloques.extend(filas)
                idx_tabla += 1
                continue

            # 8. Item de lista.
            lista = _RE_LISTA.match(linea)
            if lista:
                flush()
                bloque, i = self._consumir_item(lineas, i, lista, pila)
                bloques.append(bloque)
                continue

            # 9. Cita: se quita el marcador para que no acabe en el texto
            # indexado, y el resto se trata como linea de parrafo.
            cita = _RE_CITA.match(linea)
            if cita:
                if not buf:
                    buf_inicio = i + 1
                buf_cita = True
                buf.append(linea[cita.end() :])
                i += 1
                continue

            # 10. Cualquier otra cosa: linea de parrafo.
            if not buf:
                buf_inicio = i + 1
            buf.append(linea)
            i += 1

        flush()
        return bloques

    def _consumir_codigo(
        self, lineas: list[str], i: int, pila: Pila, doc: ParsedDocument
    ) -> tuple[Block | None, int]:
        """Consume un bloque de codigo cercado. Devuelve (bloque, siguiente)."""
        fence = _RE_FENCE.match(lineas[i])
        assert fence is not None
        cerca = fence.group(1)
        lenguaje = fence.group(2) or None
        caracter = cerca[0]

        cuerpo: list[str] = []
        j = i + 1
        cerrado = False
        while j < len(lineas):
            actual = lineas[j].strip()
            if actual and set(actual) == {caracter} and len(actual) >= len(cerca):
                cerrado = True
                break
            cuerpo.append(lineas[j])
            j += 1

        if not cerrado:
            doc.errores.append(f"bloque de codigo sin cerrar desde la linea {i + 1}")
            self.logger.warning(
                "bloque de codigo sin cerrar en %s (linea %d)", doc.fuente, i + 1
            )

        siguiente = j + 1 if cerrado else j
        if not "".join(cuerpo).strip():
            return None, siguiente

        bloque = self._bloque(
            "paragraph",
            "\n".join(cuerpo),
            ancla={
                "linea": i + 1,
                "linea_fin": j if cerrado else j,
                "es_codigo": True,
                "lenguaje": lenguaje,
                "cerca": cerca,
            },
            seccion_path=self._rutas(pila),
        )
        return bloque, siguiente

    def _consumir_item(
        self, lineas: list[str], i: int, lista: re.Match[str], pila: Pila
    ) -> tuple[Block, int]:
        """Consume un item de lista y sus lineas de continuacion."""
        sangria = len(lista.group(1))
        marcador = lista.group(2)
        texto = lista.group(3).strip()

        j = i + 1
        while j < len(lineas):
            siguiente = lineas[j]
            if not siguiente.strip() or _RE_LISTA.match(siguiente):
                break
            if len(siguiente) - len(siguiente.lstrip()) < _SANGRIA_MIN_CONTINUACION:
                break
            texto += "\n" + siguiente.strip()
            j += 1

        # `nivel` se queda en None a proposito: significa "nivel de encabezado"
        # en todo el resto del sistema. El anidamiento va en ancla["sangria"].
        bloque = self._bloque(
            "list_item",
            texto,
            ancla={
                "linea": i + 1,
                "linea_fin": j,
                "marcador": marcador,
                "ordenada": marcador[0].isdigit(),
                "sangria": sangria,
            },
            seccion_path=self._rutas(pila),
        )
        return bloque, j

    def _inicia_tabla(self, lineas: list[str], i: int) -> bool:
        """True si la linea i es cabecera de tabla y la i+1 es la separadora."""
        return (
            "|" in lineas[i]
            and i + 1 < len(lineas)
            and _RE_SEP_TABLA.match(lineas[i + 1]) is not None
            and "-" in lineas[i + 1]
        )

    def _consumir_tabla(
        self, lineas: list[str], i: int, idx_tabla: int, pila: Pila
    ) -> tuple[list[Block], int]:
        """Linealiza una tabla markdown como bloques table_row."""
        cabeceras = [
            celda if celda else f"col{n + 1}"
            for n, celda in enumerate(self._dividir_celdas(lineas[i]))
        ]
        bloques: list[Block] = []
        ruta = self._rutas(pila)

        j = i + 2
        fila = 0
        while j < len(lineas) and lineas[j].strip() and "|" in lineas[j]:
            texto = self._linealizar_fila(cabeceras, self._dividir_celdas(lineas[j]))
            if texto:
                bloques.append(
                    self._bloque(
                        "table_row",
                        texto,
                        ancla={
                            "linea": j + 1,
                            "linea_fin": j + 1,
                            "tabla": idx_tabla,
                            "fila": fila,
                            "columnas": list(cabeceras),
                        },
                        seccion_path=ruta,
                    )
                )
            fila += 1
            j += 1
        return bloques, j

    def _dividir_celdas(self, linea: str) -> list[str]:
        """Trocea una fila markdown, quitando los pipes de borde."""
        partes = _RE_PIPE.split(linea.strip())
        if partes and not partes[0].strip():
            partes = partes[1:]
        if partes and not partes[-1].strip():
            partes = partes[:-1]
        return [parte.strip().replace("\\|", "|") for parte in partes]

    def _linealizar_fila(self, cabeceras: list[str], celdas: list[str]) -> str:
        """Convierte una fila en "columna: valor | columna: valor"."""
        pares = []
        for n, celda in enumerate(celdas):
            if not celda:
                continue
            cabecera = cabeceras[n] if n < len(cabeceras) else f"col{n + 1}"
            pares.append(f"{cabecera}: {celda}")
        return " | ".join(pares)

    # ----------------------------------------------------------- Texto plano

    def _parsear_plano(self, lineas: list[str]) -> list[Block]:
        """Parrafos separados por linea en blanco, con heurstica de encabezado."""
        bloques: list[Block] = []
        pila: Pila = []
        buf: list[str] = []
        buf_inicio = 0

        def flush() -> None:
            nonlocal buf
            if buf and "".join(buf).strip():
                bloques.append(
                    self._bloque(
                        "paragraph",
                        "\n".join(buf),
                        ancla={
                            "linea": buf_inicio,
                            "linea_fin": buf_inicio + len(buf) - 1,
                        },
                        seccion_path=self._rutas(pila),
                    )
                )
            buf = []

        for i, linea in enumerate(lineas):
            if not linea.strip():
                flush()
                continue

            nivel = self._nivel_heading_plano(lineas, i)
            if nivel is not None:
                flush()
                texto = linea.strip()
                ancestros = self._empujar_seccion(pila, nivel, texto)
                bloques.append(
                    self._bloque(
                        "heading",
                        texto,
                        nivel=nivel,
                        ancla={
                            "linea": i + 1,
                            "linea_fin": i + 1,
                            "estilo": "heuristica_txt",
                        },
                        seccion_path=ancestros,
                    )
                )
                continue

            if not buf:
                buf_inicio = i + 1
            buf.append(linea)

        flush()
        return bloques

    def _nivel_heading_plano(self, lineas: list[str], i: int) -> int | None:
        """Nivel inferido si la linea i parece un encabezado, None si no."""
        texto = lineas[i].strip()
        if not texto or not any(c.isalpha() for c in texto):
            return None
        if len(texto) >= _LARGO_MAX_HEADING_TXT:
            return None
        if len(texto.split()) > _PALABRAS_MAX_HEADING_TXT:
            return None
        if texto[-1] in ".,;":
            return None
        if texto.startswith(("- ", "* ", "• ", "> ")):
            return None
        # Debe estar aislado por lineas en blanco. Sin la condicion sobre i-1,
        # cualquier linea en mayusculas dentro de un parrafo (siglas, "NOTA
        # IMPORTANTE") lo partiria en dos y corromperia la pila de secciones.
        if i + 1 < len(lineas) and lineas[i + 1].strip():
            return None
        if i > 0 and lineas[i - 1].strip():
            return None

        # La numerada gana a la de mayusculas: aporta el nivel real.
        numerada = _RE_NUMERACION.match(texto)
        if numerada:
            return min(len(numerada.group(1).split(".")), _NIVEL_MAX)
        if texto.upper() == texto:
            return 1
        return None

    # --------------------------------------------------------------- Comunes

    def _es_hr(self, linea: str) -> bool:
        """True si la linea es una regla horizontal (--- , *** , ___)."""
        limpia = linea.strip().replace(" ", "")
        return len(limpia) >= 3 and len(set(limpia)) == 1 and limpia[0] in "-*_"

    def _tipo_subrayado(self, linea: str) -> int | None:
        """1 si la linea es un subrayado de '=', 2 si es de '-', None si no."""
        limpia = linea.strip()
        if not limpia:
            return None
        if set(limpia) == {"="}:
            return 1
        if set(limpia) == {"-"}:
            return 2
        return None

    def _rutas(self, pila: Pila) -> list[str]:
        """Textos de los encabezados activos, de mas externo a mas interno."""
        return [texto for _, texto in pila]

    def _empujar_seccion(self, pila: Pila, nivel: int, texto: str) -> list[str]:
        """Cierra los niveles >= nivel, devuelve los ancestros y apila el nuevo.

        Los ancestros NO incluyen el propio encabezado: `seccion_path` es la
        ruta HASTA el bloque, nunca su propia identidad.
        """
        while pila and pila[-1][0] >= nivel:
            pila.pop()
        ancestros = self._rutas(pila)
        if texto:
            pila.append((nivel, texto))
        return ancestros

    def _deducir_titulo(self, doc: ParsedDocument, lineas: list[str]) -> str | None:
        """Titulo del documento. Nunca cae al nombre del archivo: `fuente` ya
        lo lleva, y un titulo sintetico solo mete ruido en el indice."""
        datos = doc.meta_extra.get("front_matter_datos", {})
        for clave in ("title", "titulo"):
            valor = datos.get(clave)
            if valor:
                return str(valor)

        headings = [b for b in doc.blocks if b.tipo == "heading" and b.nivel is not None]
        if headings:
            # El de nivel minimo, no el primero: hay documentos que abren con
            # "## Indice" antes del "# Titulo" real.
            minimo = min(b.nivel for b in headings if b.nivel is not None)
            for bloque in headings:
                if bloque.nivel == minimo:
                    return bloque.texto

        if doc.formato == "txt":
            for linea in lineas:
                texto = linea.strip()
                if texto:
                    return texto if len(texto) < _LARGO_MAX_TITULO_TXT else None
        return None
