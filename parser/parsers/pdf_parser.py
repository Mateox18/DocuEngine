"""
Este modulo se encarga de recuperar los documentos de formato .pdf
Extrae unicamente texto NO limpia ni hace algun proceso adicional.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from parser.models import ParsedDocument, BBox
from parser.parsers.base import BaseParser
import fitz


class PdfParser(BaseParser):
    """Parser de PDFs basado en PyMuPDF (fitz).

    Extrae el texto de cada página manteniendo la información de estructura
    (bloques y líneas) y metadatos de formato (fuente, tamaño, estilos).
    """

    EXTENSIONES = (".pdf",)
    FORMATO = "pdf"
    def parse(self, path: Path, doc_id: str, fenomeno: int) -> ParsedDocument:
        """Parsea el archivo PDF y extrae sus bloques de texto.

        Args:
            path: Ruta al archivo .pdf
            doc_id: Identificador único del documento.
            fenomeno: Fenómeno asociado al documento.

        Returns:
            ParsedDocument: El documento con los bloques extraídos.

        Nota: Actualmente el método está en desarrollo y solo extrae la estructura
        intermedia de PdfBlock e PdfLine sin completar la asignación a `doc.blocks`.
        """
        with fitz.open(path) as pdf:
            doc = self._nuevo_documento(path, doc_id, fenomeno)
            pdf_blocks = []
            for numero_pagina, page in enumerate(pdf, start=1):
                contenido = page.get_text("dict")
                for bloque in contenido["blocks"]:
                    pdf_block = self._extraer_bloque(
                        bloque,
                        numero_pagina
                    )
                    if pdf_block is not None:
                        pdf_blocks.append(pdf_block)
            # TODO: Convertir pdf_blocks a doc.blocks y devolver doc
            return doc

    def _extraer_bloque(self, pdf_block: dict, pagina:int) -> PdfBlock | None:
        """Extrae un bloque de texto de la estructura 'dict' de PyMuPDF.

        Args:
            pdf_block: Diccionario con los datos del bloque (contiene 'lines').
            pagina: Número de página donde se encuentra el bloque.

        Returns:
            PdfBlock: Objeto con la información del bloque, o None si está vacío.
        """
        lineas = []
        for pdf_line in pdf_block["lines"]:
            linea = self._extraer_linea(pdf_line)

            if linea is not None:
                lineas.append(linea)
        if not lineas:
            return None
        return PdfBlock(
            pagina=pagina,
            bbox=BBox(*pdf_block["bbox"]),
            lineas=lineas,
        )

    def _extraer_linea(self, pdf_line: dict) -> PdfLine | None:
        """Extrae una línea de texto y calcula sus propiedades de formato.

        Determina la fuente predominante, el tamaño máximo, y si es negrita o cursiva
        basándose en los 'spans' que componen la línea.

        Args:
            pdf_line: Diccionario con los datos de la línea (contiene 'spans').

        Returns:
            PdfLine: Objeto con el texto y metadatos, o None si es solo espacio en blanco.
        """
        if not pdf_line["spans"]:
            raise ValueError("Linea sin spans")
        texto = ""
        fuentes = {}
        size = 0
        bold = False
        italic = False
        for span in pdf_line["spans"]:
            texto += span["text"]
            fuentes[span["font"]] = (
                fuentes.get(span["font"], 0)
                + len(span["text"])
            )
            if span["size"] > size:
                size = span["size"]
        font_predominante = max(fuentes, key=fuentes.get)
        bold = "Bold" in font_predominante
        italic = (
            "Italic" in font_predominante
            or "Oblique" in font_predominante
        )
        if not texto.strip():
            return None
        return PdfLine(texto, BBox(*pdf_line["bbox"]), font_predominante, size, bold, italic)

@dataclass
class PdfLine:
    """Representación de una línea física en un PDF.

    Atributos:
        texto: Contenido textual de la línea.
        bbox: Coordenadas del área que ocupa la línea.
        font: Nombre de la fuente predominante.
        size: Tamaño de fuente máximo detectado en la línea.
        bold: True si la fuente predominante indica negrita.
        italic: True si la fuente predominante indica cursiva u oblicua.
    """
    texto: str
    bbox: BBox

    font: str
    size: float

    bold: bool
    italic: bool

@dataclass
class PdfBlock:
    """Agrupación de líneas que forman un bloque estructural en el PDF.

    Atributos:
        pagina: Número de página (1-based).
        bbox: Coordenadas del área que ocupa el bloque completo.
        lineas: Lista de objetos PdfLine que componen el bloque.
    """
    pagina: int
    bbox: BBox
    lineas: list[PdfLine]



