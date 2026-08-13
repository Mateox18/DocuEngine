"""Filtro de calidad a nivel de bloque."""

from __future__ import annotations

from lib.parser.models import Block

LARGO_MINIMO = 20
RATIO_ALFA_MINIMO = 0.5
RATIO_SIMBOLOS_MAXIMO = 0.7
RATIO_TOKENS_SUELTOS_MAXIMO = 0.3
TIPOS_ESTRUCTURADOS = frozenset({"table_row", "cell", "feature"})


def evaluar_bloque(block: Block) -> tuple[bool, str | None]:
    """Devuelve si debe descartarse y el motivo normalizado."""
    texto = block.texto.strip()
    if len(texto) < LARGO_MINIMO:
        return True, "corto"
    if block.tipo in TIPOS_ESTRUCTURADOS:
        return False, None
    caracteres = [c for c in texto if not c.isspace()]
    alfabeticos = sum(c.isalpha() for c in caracteres)
    if not caracteres or alfabeticos / len(caracteres) < RATIO_ALFA_MINIMO:
        return True, "poco_alfabetico"
    simbolos = sum(not c.isalpha() for c in caracteres)
    if simbolos / len(caracteres) > RATIO_SIMBOLOS_MAXIMO:
        return True, "muchos_simbolos"
    tokens = texto.split()
    sueltos = sum(len(token) == 1 and token.isalpha() for token in tokens)
    if tokens and sueltos / len(tokens) > RATIO_TOKENS_SUELTOS_MAXIMO:
        return True, "basura_ocr"
    return False, None
