"""Tests de la cascada de encoding y la normalizacion de saltos."""

from __future__ import annotations

from parser.parsers.lectura import leer_texto, normalizar_saltos

from conftest import Escribir


def test_utf8_sin_bom(escribir: Escribir) -> None:
    leido = leer_texto(escribir("a.txt", "Análisis de órbita"))

    assert (leido.encoding, leido.bom) == ("utf-8", False)
    assert leido.texto == "Análisis de órbita"


def test_bom_se_detecta_por_bytes(escribir: Escribir) -> None:
    leido = leer_texto(escribir("a.txt", "# Primero", encoding="utf-8-sig"))

    assert (leido.encoding, leido.bom) == ("utf-8-sig", True)
    assert "﻿" not in leido.texto
    assert leido.texto.startswith("#")


def test_latin1_como_ultimo_recurso(escribir: Escribir) -> None:
    leido = leer_texto(escribir("a.txt", "región andina", encoding="latin-1"))

    assert leido.encoding == "latin-1"
    assert "regi" in leido.texto


def test_normalizar_saltos_crlf_y_cr() -> None:
    assert normalizar_saltos("a\r\nb\rc\nd") == ["a", "b", "c", "d"]


def test_normalizar_saltos_no_parte_en_separadores_exoticos() -> None:
    # Regresion del motivo por el que se usa split("\n") y no splitlines():
    # splitlines() partiria aqui y descuadraria los indices de `ancla`.
    assert normalizar_saltos("a b\vc\fd\x1ce") == ["a b\vc\fd\x1ce"]
