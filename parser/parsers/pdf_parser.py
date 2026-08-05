"""
Este modulo se encarga de recuperar los documentos de formato .pdf
Extrae unicamente texto NO limpia ni hace algun proceso adicional.
"""
from dataclasses import dataclass
from pathlib import Path

from nipype.interfaces.minc import BBox

from parser.models import ParsedDocument
from parser.parsers.base import BaseParser
import fitz
from pprint import pprint

class PdfParser(BaseParser):

    EXTENSIONES = (".pdf",)
    FORMATO = "pdf"
    def parse(self, path: Path, doc_id: str, fenomeno: int) -> ParsedDocument:
        doc = self._nuevo_documento(path, doc_id, fenomeno)
        pdf = fitz.open(path)
        for numero_pagina, page in enumerate(pdf, start=1):
            contenido = page.get_text("dict")
            for bloque in contenido["blocks"]:
                self._adaptar_bloque(bloque)

    def _adaptar_bloque(self, pdf_block: dict) -> PdfBlock | None:
        lineas = []
        for pdf_line in pdf_block["lines"]:
            linea = self._adaptar_linea(pdf_line)

            if linea is not None:
                lineas.append(linea)
        if not lineas:
            return None
    def _adaptar_linea(self, pdf_line: dict) -> PdfLine | None:
        texto = ""
        fuentes = {}
        size = 0
        for span in pdf_line["spans"]:
            texto += span["text"]
            fuentes[span["font"]] = (
                    fuentes.get(span["font"], 0)
                    + len(span["text"])
            )
            if span["size"] > size:
                size = span["size"]
        font_predominante = max(fuentes, key=fuentes.get)


@dataclass
class PdfLine:
    texto: str
    bbox: BBox

    font: str
    size: float

    bold: bool
    italic: bool

@dataclass
class PdfBlock:
    pagina: int
    bbox: BBox
    lineas: list[PdfLine]

if __name__ == "__main__":
    parser = PdfParser()

    parser.parse(
        path=Path("<ruta-local>"),
        doc_id="test",
        fenomeno=0,
    )


