import logging
from pathlib import Path

from parser.parsers.html_parser import HtmlParser
from parser.parsers.base import BaseParser
from parser.parsers.json_parser import JsonParser
from parser.parsers.pdf_parser import PdfParser
from parser.parsers.pbf_parser import PbfParser
from parser.parsers.image_parser import ImageParser
from parser.parsers.tabular_parser import TabularParser
from parser.parsers.text_parser import TextParser

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

def inferir_fenomeno(ruta: Path, raiz: Path) -> int | None:
    try:
        relativa = ruta.relative_to(raiz)
    except ValueError:
        logger.warning("La ruta está fuera de la raíz: %s", ruta)
        return None

    if not relativa.parts:
        return None

    carpeta = relativa.parts[0]

    fenomenos = {
        "F1_IA_y_Capacidades_Estrategicas": 1,
        "F2_Seguridad_Entorno_Espacial": 2,
        "F3_Dinamicas_Territoriales": 3,
    }

    fenomeno = fenomenos.get(carpeta)

    if fenomeno is None:
        logger.warning("No se pudo inferir el fenómeno de %s", ruta)

    return fenomeno


