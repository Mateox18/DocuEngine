"""Deteccion y marcado de lineas repetidas."""

from __future__ import annotations

import logging
from collections import Counter

from lib.parser.models import ParsedDocument

logger = logging.getLogger(__name__)
LARGO_MAX_LINEA = 80
LARGO_MIN_LINEA = 3
MIN_GRUPOS = 4


def detectar_repetidos(doc: ParsedDocument, umbral: float = 0.3) -> set[str]:
    """Devuelve lineas cortas repetidas en mas del umbral de grupos."""
    grupos = _grupos(doc)
    if len(grupos) < MIN_GRUPOS:
        return set()
    conteo: Counter[str] = Counter()
    for grupo in grupos:
        conteo.update(grupo)
    minimo = umbral * len(grupos)
    return {linea for linea, veces in conteo.items() if veces > minimo}


def eliminar_repetidos(doc: ParsedDocument, repetidos: set[str]) -> None:
    """Marca bloques compuestos solo por lineas repetidas como boilerplate."""
    for bloque in doc.blocks:
        if bloque.descartado:
            continue
        lineas = _lineas(bloque.texto)
        if lineas and all(linea in repetidos for linea in lineas):
            bloque.descartado = True
            bloque.motivo_descarte = "boilerplate"


def _grupos(doc: ParsedDocument) -> list[set[str]]:
    por_pagina: dict[int, set[str]] = {}
    sueltos: list[set[str]] = []
    for bloque in doc.blocks:
        lineas = set(_lineas(bloque.texto))
        if not lineas:
            continue
        pagina = bloque.ancla.get("pagina")
        if isinstance(pagina, int):
            por_pagina.setdefault(pagina, set()).update(lineas)
        else:
            sueltos.append(lineas)
    return [por_pagina[k] for k in sorted(por_pagina)] + sueltos


def _lineas(texto: str) -> list[str]:
    salida: list[str] = []
    for linea in texto.split("\n"):
        limpia = " ".join(linea.split())
        if LARGO_MIN_LINEA <= len(limpia) <= LARGO_MAX_LINEA:
            salida.append(limpia.casefold())
    return salida
