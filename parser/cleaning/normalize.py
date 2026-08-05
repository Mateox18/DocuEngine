from __future__ import annotations

import ftfy
import unicodedata
import re

# Zero-width, BOM suelto y soft hyphen: invisibles que rompen la tokenizacion.
_INVISIBLES = dict.fromkeys(
    [0x200B, 0x200C, 0x200D, 0xFEFF, 0x00AD, 0x2060, 0x180E]
)

# Espacios exoticos -> espacio normal.
_ESPACIOS = dict.fromkeys(
    [
        0x00A0,
        0x1680,
        0x2000,
        0x2001,
        0x2002,
        0x2003,
        0x2004,
        0x2005,
        0x2006,
        0x2007,
        0x2008,
        0x2009,
        0x200A,
        0x202F,
        0x205F,
        0x3000,
    ],
    " ",
)

# Control C0 y C1 salvo \n y \t (tabs y saltos de línea).
_CONTROL = dict.fromkeys(
    [c for c in range(0x00, 0x20) if c not in (0x09, 0x0A)]
    + list(range(0x7F, 0xA0))
)

_TABLA = {**_CONTROL, **_INVISIBLES, **_ESPACIOS}

# Regex para colapsar espacios sin romper parrafos (\n\n).
_RE_ESPACIOS = re.compile(r"[^\S\r\n\t]+", re.UNICODE)
_RE_ESPACIO_FIN_LINEA = re.compile(r"[ \t]+\n", re.UNICODE)
_RE_SALTOS = re.compile(r"\n{3,}", re.UNICODE)


def reparar_mojibake(texto: str) -> str:
    """Corrige mojibake frecuente en textos mal decodificados."""
    return ftfy.fix_text(texto)


def normalizar_unicode(texto: str) -> str:
    """Normaliza Unicode con NFKC."""
    return unicodedata.normalize("NFKC", texto)


def quitar_invisibles(texto: str) -> str:
    """Elimina controles e invisibles y unifica espacios exoticos."""
    return texto.translate(_TABLA)


def colapsar_espacios(texto: str) -> str:
    """Colapsa espacios repetidos conservando la senal de parrafo.

    CRITICO: se preserva "\\n\\n". El chunker lo necesita para saber donde
    empieza y acaba un parrafo; colapsarlo todo a un espacio destruye esa
    informacion y no hay forma de recuperarla despues.
    """
    texto = _RE_ESPACIOS.sub(" ", texto)
    texto = _RE_ESPACIO_FIN_LINEA.sub("\n", texto)
    texto = _RE_SALTOS.sub("\n\n", texto)
    return texto.strip()
