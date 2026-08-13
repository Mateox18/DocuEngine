"""Capa de ingesta: parsers por formato y pipeline de limpieza.

Los modelos son livianos y se reexportan aqui para mantener una API estable;
los parsers concretos siguen sin cargarse al importar `lib.parser`.
"""

from lib.parser.models import (
    BBox,
    Block,
    ErrorParseo,
    ParsedDocument,
    TipoBloque,
    TIPOS_BLOQUE,
)

__all__ = [
    "BBox", "Block", "ErrorParseo", "ParsedDocument", "TipoBloque",
    "TIPOS_BLOQUE",
]
