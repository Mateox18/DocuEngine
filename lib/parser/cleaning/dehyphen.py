"""Union de palabras cortadas por guion al final de linea."""

from __future__ import annotations

import re
from collections import Counter

_RE_CORTE = re.compile(r"(\w+)-[ \t]*\n[ \t]*(\w+)")
_RE_PALABRA = re.compile(r"\w+", re.UNICODE)
_MIN_PREFIJO = 3


def unir_palabras_cortadas(texto: str) -> str:
    """Une cortes silabicos, conservando compuestos y nombres propios."""
    vocabulario = _vocabulario(texto)

    def unir(match: re.Match[str]) -> str:
        izquierda, derecha = match.group(1), match.group(2)
        if not derecha[:1].islower() or len(izquierda) < _MIN_PREFIJO:
            return match.group(0)
        if vocabulario[izquierda.casefold()] and vocabulario[derecha.casefold()]:
            return match.group(0)
        return izquierda + derecha

    return _RE_CORTE.sub(unir, texto)


def _vocabulario(texto: str) -> Counter[str]:
    """Cuenta palabras completas, sin contar las partes de cortes."""
    sin_cortes = _RE_CORTE.sub(" ", texto)
    return Counter(p.casefold() for p in _RE_PALABRA.findall(sin_cortes))
