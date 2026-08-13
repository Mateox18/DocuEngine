"""Deteccion determinista de idioma por bloque."""

from __future__ import annotations

import logging
from collections import Counter

from langdetect import DetectorFactory, LangDetectException, detect_langs

from lib.parser.models import ParsedDocument

logger = logging.getLogger(__name__)
DetectorFactory.seed = 0
LARGO_MINIMO = 40
CONFIANZA_MINIMA = 0.70


def detectar_idioma(texto: str) -> str | None:
    """Devuelve ISO 639-1 si el texto es suficientemente largo y confiable."""
    limpio = texto.strip()
    if len(limpio) < LARGO_MINIMO:
        return None
    try:
        candidatos = detect_langs(limpio)
    except LangDetectException:
        return None
    if not candidatos or candidatos[0].prob < CONFIANZA_MINIMA:
        return None
    return candidatos[0].lang.split("-")[0]


def idioma_dominante(doc: ParsedDocument) -> str | None:
    """Devuelve el idioma activo con mayor peso de caracteres."""
    pesos: Counter[str] = Counter()
    for bloque in doc.bloques_activos():
        if bloque.idioma:
            pesos[bloque.idioma] += len(bloque.texto)
    return pesos.most_common(1)[0][0] if pesos else None
