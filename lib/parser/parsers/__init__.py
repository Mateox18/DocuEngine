"""Parsers por formato. Extraen y estructuran; la limpieza es de cleaning/.

Deliberadamente sin imports para no forzar la carga de dependencias pesadas
(pymupdf, pytesseract, pyosmium) al importar un solo parser.
"""

from lib.parser.parsers.base import BaseParser, ParserError
from lib.parser.parsers.pbf_parser import PbfParser
from lib.parser.parsers.secciones import Pila, empujar_seccion, rutas

__all__ = [
    "BaseParser", "ParserError", "PbfParser", "Pila", "empujar_seccion", "rutas",
]
