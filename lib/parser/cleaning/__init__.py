"""Capa comun de limpieza posterior al parseo.

Deliberadamente sin imports: algunas funciones cargan dependencias opcionales
como ftfy o langdetect, y no queremos forzarlas al importar `lib.parser.cleaning`.
"""

from lib.parser.cleaning.dedup import calcular_hash, deduplicar_documentos
from lib.parser.cleaning.dehyphen import unir_palabras_cortadas

__all__ = ["calcular_hash", "deduplicar_documentos", "unir_palabras_cortadas"]
