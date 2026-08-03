"""Fixtures compartidas de la suite."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

Escribir = Callable[..., Path]


@pytest.fixture
def escribir(tmp_path: Path) -> Escribir:
    """Crea un archivo con contenido, encoding y salto de linea exactos."""

    def _escribir(
        nombre: str,
        contenido: str,
        *,
        encoding: str = "utf-8",
        salto: str = "\n",
    ) -> Path:
        destino = tmp_path / nombre
        # write_bytes y NO write_text: en Windows el modo texto traduce
        # \n -> \r\n y los tests de CRLF y de encoding darian falsos verdes.
        destino.write_bytes(contenido.replace("\n", salto).encode(encoding))
        return destino

    return _escribir
