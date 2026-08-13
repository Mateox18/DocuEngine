"""Lectura de archivos de texto sin declaracion de encoding en banda.

La usan los formatos que NO declaran su encoding dentro del propio archivo:
texto plano, markdown, CSV y JSON. El HTML queda deliberadamente fuera: declara
su encoding en `<meta charset>` y forzarle esta cascada produce mojibake en
paginas legacy donde el navegador acierta.
"""

from __future__ import annotations

import codecs
import logging
from dataclasses import dataclass
from pathlib import Path

from lib.parser.parsers.base import ParserError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TextoLeido:
    """Resultado de decodificar un archivo."""

    texto: str
    encoding: str  # "utf-8-sig" | "utf-8" | "latin-1"
    bom: bool


def leer_texto(path: Path, *, log: logging.Logger | None = None) -> TextoLeido:
    """Decodifica el archivo probando utf-8-sig (por BOM), utf-8 y latin-1.

    El BOM se detecta por bytes en lugar de confiar en el orden
    utf-8 -> utf-8-sig: un archivo con BOM decodifica SIN error como utf-8 y
    deja un \\ufeff invisible al inicio que impide reconocer el primer
    encabezado o la apertura del front-matter.
    """
    registro = log or logger
    datos = path.read_bytes()
    if datos.startswith(codecs.BOM_UTF8):
        return TextoLeido(datos.decode("utf-8-sig"), "utf-8-sig", True)
    for encoding in ("utf-8", "latin-1"):
        try:
            return TextoLeido(datos.decode(encoding), encoding, False)
        except UnicodeDecodeError:
            registro.debug("%s no decodifica como %s", path.name, encoding)
    # Inalcanzable: latin-1 decodifica cualquier secuencia de bytes.
    raise ParserError(f"no se pudo decodificar {path.name}")


def normalizar_saltos(texto: str) -> list[str]:
    """Unifica CRLF/CR a LF y parte en lineas.

    No es limpieza de texto sino decodificacion estructural: un \\r colgando
    rompe los regex anclados en $. Se usa split("\\n") y no splitlines() porque
    este ultimo tambien parte en \\v, \\f, \\x1c y U+2028, lo que descuadraria
    los indices de linea de `ancla` respecto a lo que muestra un editor.
    """
    return texto.replace("\r\n", "\n").replace("\r", "\n").split("\n")
