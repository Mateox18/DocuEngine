"""Tests de encoding, saltos de linea y casos degenerados de TextParser."""

from __future__ import annotations

import logging

import pytest

from lib.parser.parsers import ParserError
from lib.parser.parsers.text_parser import TextParser

from conftest import Escribir


def test_utf8_sin_bom(escribir: Escribir) -> None:
    ruta = escribir("doc.md", "# Análisis de órbita\n\nCuerpo con acentuación.\n")

    doc = TextParser().parse(ruta, "DOC-1-00001", 1)

    assert doc.meta_extra["encoding"] == "utf-8"
    assert doc.meta_extra["bom"] is False
    assert doc.titulo == "Análisis de órbita"


def test_utf8_con_bom_no_deja_feff(escribir: Escribir) -> None:
    # Con la cascada literal utf-8 -> utf-8-sig, este archivo decodificaria
    # como utf-8 dejando un ﻿ que impediria reconocer el heading.
    ruta = escribir("doc.md", "# Primero\n\nCuerpo.\n", encoding="utf-8-sig")

    doc = TextParser().parse(ruta, "DOC-1-00001", 1)

    assert doc.meta_extra["encoding"] == "utf-8-sig"
    assert doc.meta_extra["bom"] is True
    assert "﻿" not in doc.texto_completo()
    assert doc.blocks[0].tipo == "heading"
    assert doc.blocks[0].texto == "Primero"


def test_bom_no_rompe_el_front_matter(escribir: Escribir) -> None:
    ruta = escribir(
        "doc.md", "---\ntitle: Con BOM\n---\n\nCuerpo.\n", encoding="utf-8-sig"
    )

    doc = TextParser().parse(ruta, "DOC-1-00001", 1)

    assert doc.meta_extra["front_matter_datos"] == {"title": "Con BOM"}
    assert doc.titulo == "Con BOM"


def test_latin1_como_ultimo_recurso(escribir: Escribir) -> None:
    ruta = escribir("doc.md", "Informe de la región andina.\n", encoding="latin-1")

    doc = TextParser().parse(ruta, "DOC-1-00001", 1)

    assert doc.meta_extra["encoding"] == "latin-1"
    assert doc.blocks
    assert "regi" in doc.blocks[0].texto


def test_crlf_produce_el_mismo_resultado_que_lf(escribir: Escribir) -> None:
    contenido = "# Titulo\n\n- item\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"

    lf = TextParser().parse(escribir("lf.md", contenido), "DOC-1-00001", 1)
    crlf = TextParser().parse(
        escribir("crlf.md", contenido, salto="\r\n"), "DOC-1-00002", 1
    )

    assert [(b.tipo, b.texto, b.nivel, b.ancla) for b in lf.blocks] == [
        (b.tipo, b.texto, b.nivel, b.ancla) for b in crlf.blocks
    ]


@pytest.mark.parametrize("contenido", ["", "   \n\n\t\n  \n"])
def test_archivo_vacio(escribir: Escribir, contenido: str) -> None:
    ruta = escribir("doc.md", contenido)

    doc = TextParser().parse(ruta, "DOC-1-00001", 1)

    assert doc.blocks == []
    assert doc.meta_extra["vacio"] is True
    assert doc.errores
    assert doc.titulo is None


def test_extension_no_soportada_lanza_parsererror(escribir: Escribir) -> None:
    ruta = escribir("doc.pdf", "contenido")

    with pytest.raises(ParserError, match="no soporta la extension"):
        TextParser().parse(ruta, "DOC-1-00001", 1)


def test_warning_de_documento_vacio_se_registra(
    escribir: Escribir, caplog: pytest.LogCaptureFixture
) -> None:
    ruta = escribir("doc.md", "")

    with caplog.at_level(logging.WARNING):
        TextParser().parse(ruta, "DOC-1-00001", 1)

    assert any("documento vacio" in r.message for r in caplog.records)
