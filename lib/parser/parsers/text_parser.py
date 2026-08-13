"""Parser de texto plano y Markdown (.md, .markdown, .txt).

La maquina de estados de markdown vive en `markdown_blocks`, compartida con
HtmlParser (trafilatura devuelve markdown). Aqui se queda el modo texto plano,
que es especifico de este parser.

Extrae estructura; NO limpia. Los indices de linea de `ancla` son 1-based, para
casar con lo que muestran los editores, `grep -n` y los mensajes de error.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from lib.parser.models import Block, ParsedDocument
from lib.parser.parsers.base import BaseParser
from lib.parser.parsers.lectura import leer_texto, normalizar_saltos
from lib.parser.parsers.markdown_blocks import extraer_front_matter, parsear_markdown
from lib.parser.parsers.secciones import Pila, empujar_seccion, rutas

logger = logging.getLogger(__name__)

_RE_NUMERACION = re.compile(r"^(\d+(?:\.\d+)*)[.)]?\s+\S")

_LARGO_MAX_HEADING_TXT = 80
_PALABRAS_MAX_HEADING_TXT = 12
_LARGO_MAX_TITULO_TXT = 120
_NIVEL_MAX = 6


class TextParser(BaseParser):
    """Parser de Markdown y texto plano."""

    EXTENSIONES = (".md", ".markdown", ".txt")
    FORMATO = "md"
    MAPA_FORMATOS = {".txt": "txt"}

    # ------------------------------------------------------------------ API

    def parse(self, path: Path, doc_id: str, fenomeno: int) -> ParsedDocument:
        """Parsea un .md/.markdown/.txt a la representacion intermedia."""
        doc = self._nuevo_documento(path, doc_id, fenomeno)
        leido = leer_texto(path, log=self.logger)
        doc.meta_extra["encoding"] = leido.encoding
        doc.meta_extra["bom"] = leido.bom

        lineas = normalizar_saltos(leido.texto)

        if path.suffix.lower() == ".txt":
            doc.meta_extra["modo"] = "plano"
            doc.blocks = self._parsear_plano(lineas)
        else:
            doc.meta_extra["modo"] = "markdown"
            frente = extraer_front_matter(lineas)
            if frente.crudo is not None:
                doc.meta_extra["front_matter"] = frente.crudo
                doc.meta_extra["front_matter_datos"] = frente.datos
            resultado = parsear_markdown(
                lineas, bloque=self._bloque, inicio=frente.inicio
            )
            doc.blocks = resultado.bloques
            doc.errores.extend(resultado.avisos)
            for aviso in resultado.avisos:
                self.logger.warning("%s: %s", doc.fuente, aviso)

        doc.titulo = self._deducir_titulo(doc, lineas)

        if not doc.blocks:
            # No es un ParserError: la evaluacion empareja por `fuente`, asi que
            # cada archivo del corpus debe aparecer en la salida. "Vacio" es un
            # dato, no un fallo.
            doc.meta_extra["vacio"] = True
            doc.errores.append("documento vacio: 0 bloques extraidos")
            self.logger.warning("documento vacio: %s", doc.fuente)
        return doc

    # ----------------------------------------------------------- Texto plano

    def _parsear_plano(self, lineas: list[str]) -> list[Block]:
        """Parrafos separados por linea en blanco, con heuristica de encabezado."""
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
                        seccion_path=rutas(pila),
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
                ancestros = empujar_seccion(pila, nivel, texto)
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

    # --------------------------------------------------------------- Titulo

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
