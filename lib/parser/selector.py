import logging
from pathlib import Path

from lib.parser.parsers.html_parser import HtmlParser
from lib.parser.parsers.base import BaseParser
from lib.parser.parsers.json_parser import JsonParser
from lib.parser.parsers.pdf_parser import PdfParser
from lib.parser.parsers.pbf_parser import PbfParser
from lib.parser.parsers.image_parser import ImageParser
from lib.parser.parsers.tabular_parser import TabularParser
from lib.parser.parsers.text_parser import TextParser

logger = logging.getLogger(__name__)

PARSERS = [
    TextParser,
    HtmlParser,
    JsonParser,
    PdfParser,
    TabularParser,
    ImageParser,
    PbfParser,
]

def detectar_parser(archivo: Path) -> BaseParser | None:
    """Busca un parser sin detener el procesamiento del lote."""
    for parser_cls in PARSERS:
        if parser_cls.puede_parsear(archivo):
            return parser_cls()

    logger.warning(
        "Archivo omitido: formato no soportado: %s",
        archivo,
    )
    return None

