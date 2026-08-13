"""Motor de bloques Markdown, compartido por TextParser y HtmlParser.

TextParser lo usa sobre archivos .md/.markdown; HtmlParser sobre el markdown
sintetico que devuelve trafilatura. No conoce ParsedDocument ni BaseParser:
recibe una fabrica de bloques y devuelve bloques mas avisos. Asi es testeable
sin parser y no puede escribir en el documento por accidente.

El motor NO limpia: el marcado inline se conserva literal (**negrita**,
[texto](url), `codigo`) y las lineas de un parrafo se unen con "\\n", no con
espacio. El soft-wrap original es informacion que decide la capa cleaning/.

Los indices de linea de `ancla` son 1-based y relativos a la lista de lineas
recibida. Para TextParser coinciden con el archivo; HtmlParser los sustituye por
un ordinal, porque en markdown sintetico apuntarian a un buffer en memoria.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from lib.parser.models import Block
from lib.parser.parsers.base import FabricaBloques, crear_bloque
from lib.parser.parsers.secciones import Pila, empujar_seccion, rutas
from lib.parser.parsers.tablas import linealizar_fila, nombrar_cabeceras

_RE_ATX = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
_RE_CIERRE_ATX = re.compile(r"\s+#+\s*$")
_RE_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})\s*([^\s`]*)\s*$")
_RE_LISTA = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
_RE_SEP_TABLA = re.compile(r"^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$")
_RE_PIPE = re.compile(r"(?<!\\)\|")
_RE_CITA = re.compile(r"^ {0,3}>\s?")
_RE_CLAVE_YAML = re.compile(r"^([A-Za-z_][\w.-]*)\s*:\s*(.*)$")

_SANGRIA_MIN_CONTINUACION = 2


@dataclass
class ResultadoMarkdown:
    """Bloques extraidos y avisos no fatales de una pasada."""

    bloques: list[Block]
    avisos: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FrontMatter:
    """Front-matter YAML de la cabecera de un markdown."""

    inicio: int  # primera linea de contenido (0 si no hay front-matter)
    crudo: str | None = None
    datos: dict[str, str] = field(default_factory=dict)


def parsear_markdown(
    lineas: list[str],
    *,
    bloque: FabricaBloques = crear_bloque,
    inicio: int = 0,
    pila: Pila | None = None,
) -> ResultadoMarkdown:
    """Maquina de estados de una pasada sobre `lineas`.

    El orden de las ramas importa: el codigo cercado va antes que los
    encabezados (para que un "# comentario" dentro del fence no sea heading) y
    la regla horizontal antes que las listas (porque "* * *" casa con el regex
    de item).
    """
    return _Motor(lineas, bloque, pila if pila is not None else []).ejecutar(inicio)


def extraer_front_matter(lineas: list[str]) -> FrontMatter:
    """Localiza el front-matter de la cabecera. Funcion pura.

    Solo cuenta si la linea 0 es exactamente "---". Si no aparece la linea de
    cierre no se considera front-matter y la linea 0 se reprocesa como
    contenido: asi un documento que abre con una regla horizontal no se pierde
    entero.
    """
    if not lineas or lineas[0].rstrip() != "---":
        return FrontMatter(inicio=0)
    for j in range(1, len(lineas)):
        if lineas[j].rstrip() in ("---", "..."):
            crudo = "\n".join(lineas[1:j])
            return FrontMatter(inicio=j + 1, crudo=crudo, datos=_claves_yaml(crudo))
    return FrontMatter(inicio=0)


def _claves_yaml(crudo: str) -> dict[str, str]:
    """Parseo plano de las claves de primer nivel. Sin PyYAML a proposito."""
    datos: dict[str, str] = {}
    for linea in crudo.split("\n"):
        if linea[:1].isspace():  # anidamiento: fuera de alcance
            continue
        match = _RE_CLAVE_YAML.match(linea.strip())
        if match:
            datos[match.group(1)] = match.group(2).strip().strip("\"'")
    return datos


def es_hr(linea: str) -> bool:
    """True si la linea es una regla horizontal (--- , *** , ___)."""
    limpia = linea.strip().replace(" ", "")
    return len(limpia) >= 3 and len(set(limpia)) == 1 and limpia[0] in "-*_"


def tipo_subrayado(linea: str) -> int | None:
    """1 si la linea es un subrayado de '=', 2 si es de '-', None si no."""
    limpia = linea.strip()
    if not limpia:
        return None
    if set(limpia) == {"="}:
        return 1
    if set(limpia) == {"-"}:
        return 2
    return None


def dividir_celdas(linea: str) -> list[str]:
    """Trocea una fila markdown, quitando los pipes de borde."""
    partes = _RE_PIPE.split(linea.strip())
    if partes and not partes[0].strip():
        partes = partes[1:]
    if partes and not partes[-1].strip():
        partes = partes[:-1]
    return [parte.strip().replace("\\|", "|") for parte in partes]


class _Motor:
    """Estado de una pasada. Privado: la API publica es parsear_markdown."""

    def __init__(
        self, lineas: list[str], bloque: FabricaBloques, pila: Pila
    ) -> None:
        self._lineas = lineas
        self._bloque = bloque
        self._pila = pila
        self._bloques: list[Block] = []
        self._avisos: list[str] = []
        self._buf: list[str] = []
        self._buf_inicio = 0
        self._buf_cita = False
        self._idx_tabla = 0

    def ejecutar(self, inicio: int) -> ResultadoMarkdown:
        """Recorre las lineas desde `inicio` y devuelve bloques y avisos."""
        i = inicio
        while i < len(self._lineas):
            linea = self._lineas[i]

            # 1-2. Codigo cercado. Va primero: es lo que impide que un
            # "# comentario" de Python dentro del fence acabe como heading.
            if _RE_FENCE.match(linea):
                self._flush()
                i = self._consumir_codigo(i)
                continue

            # 3. Linea en blanco.
            if not linea.strip():
                self._flush()
                i += 1
                continue

            # 4. Encabezado ATX. Se exige espacio tras las almohadillas, asi
            # que "#hashtag" no es un encabezado.
            atx = _RE_ATX.match(linea)
            if atx:
                self._flush()
                self._emitir_atx(atx, i)
                i += 1
                continue

            # 5. Subrayado setext. Solo cuenta si hay un parrafo pendiente: si
            # el buffer esta vacio, la linea previa era blanca o un elemento de
            # bloque, y entonces "---" es una regla horizontal.
            nivel_setext = tipo_subrayado(linea)
            if nivel_setext is not None and self._buf:
                self._emitir_setext(nivel_setext, i)
                i += 1
                continue

            # 6. Regla horizontal. Antes que la lista: "* * *" casa con el
            # regex de item. No emite bloque, pero cierra el parrafo pendiente.
            if es_hr(linea):
                self._flush()
                i += 1
                continue

            # 7. Tabla.
            if self._inicia_tabla(i):
                self._flush()
                i = self._consumir_tabla(i)
                continue

            # 8. Item de lista.
            lista = _RE_LISTA.match(linea)
            if lista:
                self._flush()
                i = self._consumir_item(i, lista)
                continue

            # 9. Cita: se quita el marcador para que no acabe en el texto
            # indexado, y el resto se trata como linea de parrafo.
            cita = _RE_CITA.match(linea)
            if cita:
                self._acumular(linea[cita.end() :], i, cita=True)
                i += 1
                continue

            # 10. Cualquier otra cosa: linea de parrafo.
            self._acumular(linea, i)
            i += 1

        self._flush()
        return ResultadoMarkdown(self._bloques, self._avisos)

    # ------------------------------------------------------------- Parrafos

    def _acumular(self, texto: str, i: int, *, cita: bool = False) -> None:
        """Anade una linea al parrafo pendiente."""
        if not self._buf:
            self._buf_inicio = i + 1
        if cita:
            self._buf_cita = True
        self._buf.append(texto)

    def _flush(self) -> None:
        """Cierra el parrafo pendiente y lo emite si tiene contenido."""
        if self._buf and "".join(self._buf).strip():
            ancla: dict[str, Any] = {
                "linea": self._buf_inicio,
                "linea_fin": self._buf_inicio + len(self._buf) - 1,
            }
            if self._buf_cita:
                ancla["cita"] = True
            self._bloques.append(
                self._bloque(
                    "paragraph",
                    "\n".join(self._buf),
                    ancla=ancla,
                    seccion_path=rutas(self._pila),
                )
            )
        self._buf = []
        self._buf_cita = False

    # ----------------------------------------------------------- Encabezados

    def _emitir_atx(self, atx: re.Match[str], i: int) -> None:
        """Emite un encabezado ATX y actualiza la pila."""
        nivel = len(atx.group(1))
        texto = _RE_CIERRE_ATX.sub("", atx.group(2) or "").strip()
        ancestros = empujar_seccion(self._pila, nivel, texto)
        if texto:
            self._bloques.append(
                self._bloque(
                    "heading",
                    texto,
                    nivel=nivel,
                    ancla={"linea": i + 1, "linea_fin": i + 1, "estilo": "atx"},
                    seccion_path=ancestros,
                )
            )

    def _emitir_setext(self, nivel: int, i: int) -> None:
        """Convierte la ultima linea del parrafo pendiente en encabezado.

        A diferencia de CommonMark se toma solo la ULTIMA linea: subrayar sin
        linea en blanco previa fabricaria si no un heading de varias lineas que
        envenena los seccion_path de todos sus descendientes.
        """
        texto = self._buf.pop().strip()
        linea_heading = self._buf_inicio + len(self._buf)
        self._flush()
        ancestros = empujar_seccion(self._pila, nivel, texto)
        self._bloques.append(
            self._bloque(
                "heading",
                texto,
                nivel=nivel,
                ancla={
                    "linea": linea_heading,
                    "linea_fin": i + 1,
                    "estilo": "setext",
                },
                seccion_path=ancestros,
            )
        )

    # --------------------------------------------------------------- Codigo

    def _consumir_codigo(self, i: int) -> int:
        """Consume un bloque de codigo cercado. Devuelve la linea siguiente."""
        fence = _RE_FENCE.match(self._lineas[i])
        assert fence is not None
        cerca = fence.group(1)
        lenguaje = fence.group(2) or None
        caracter = cerca[0]

        cuerpo: list[str] = []
        j = i + 1
        cerrado = False
        while j < len(self._lineas):
            actual = self._lineas[j].strip()
            if actual and set(actual) == {caracter} and len(actual) >= len(cerca):
                cerrado = True
                break
            cuerpo.append(self._lineas[j])
            j += 1

        if not cerrado:
            self._avisos.append(f"bloque de codigo sin cerrar desde la linea {i + 1}")

        siguiente = j + 1 if cerrado else j
        if "".join(cuerpo).strip():
            self._bloques.append(
                self._bloque(
                    "paragraph",
                    "\n".join(cuerpo),
                    ancla={
                        "linea": i + 1,
                        "linea_fin": j,
                        "es_codigo": True,
                        "lenguaje": lenguaje,
                        "cerca": cerca,
                    },
                    seccion_path=rutas(self._pila),
                )
            )
        return siguiente

    # --------------------------------------------------------------- Listas

    def _consumir_item(self, i: int, lista: re.Match[str]) -> int:
        """Consume un item de lista y sus lineas de continuacion."""
        sangria = len(lista.group(1))
        marcador = lista.group(2)
        texto = lista.group(3).strip()

        j = i + 1
        while j < len(self._lineas):
            siguiente = self._lineas[j]
            if not siguiente.strip() or _RE_LISTA.match(siguiente):
                break
            if len(siguiente) - len(siguiente.lstrip()) < _SANGRIA_MIN_CONTINUACION:
                break
            texto += "\n" + siguiente.strip()
            j += 1

        # `nivel` se queda en None a proposito: significa "nivel de encabezado"
        # en todo el resto del sistema. El anidamiento va en ancla["sangria"].
        self._bloques.append(
            self._bloque(
                "list_item",
                texto,
                ancla={
                    "linea": i + 1,
                    "linea_fin": j,
                    "marcador": marcador,
                    "ordenada": marcador[0].isdigit(),
                    "sangria": sangria,
                },
                seccion_path=rutas(self._pila),
            )
        )
        return j

    # --------------------------------------------------------------- Tablas

    def _inicia_tabla(self, i: int) -> bool:
        """True si la linea i es cabecera de tabla y la i+1 es la separadora."""
        return (
            "|" in self._lineas[i]
            and i + 1 < len(self._lineas)
            and _RE_SEP_TABLA.match(self._lineas[i + 1]) is not None
            and "-" in self._lineas[i + 1]
        )

    def _consumir_tabla(self, i: int) -> int:
        """Linealiza una tabla markdown como bloques table_row."""
        cabeceras = nombrar_cabeceras(dividir_celdas(self._lineas[i]))
        ruta = rutas(self._pila)

        j = i + 2
        fila = 0
        while (
            j < len(self._lineas)
            and self._lineas[j].strip()
            and "|" in self._lineas[j]
        ):
            texto = linealizar_fila(cabeceras, dividir_celdas(self._lineas[j]))
            if texto:
                self._bloques.append(
                    self._bloque(
                        "table_row",
                        texto,
                        ancla={
                            "linea": j + 1,
                            "linea_fin": j + 1,
                            "tabla": self._idx_tabla,
                            "fila": fila,
                            "columnas": list(cabeceras),
                        },
                        seccion_path=ruta,
                    )
                )
            fila += 1
            j += 1
        self._idx_tabla += 1
        return j
