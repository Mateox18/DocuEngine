"""Tests de la pila de encabezados."""

from __future__ import annotations

from lib.parser.parsers import Pila, empujar_seccion, rutas


def test_rutas_devuelve_solo_los_textos() -> None:
    pila: Pila = [(1, "Informe"), (2, "Riesgos")]

    assert rutas(pila) == ["Informe", "Riesgos"]


def test_ancestros_nunca_incluyen_el_propio_encabezado() -> None:
    pila: Pila = []

    assert empujar_seccion(pila, 1, "Informe") == []
    assert empujar_seccion(pila, 2, "Riesgos") == ["Informe"]
    assert empujar_seccion(pila, 3, "Colisiones") == ["Informe", "Riesgos"]


def test_cierra_los_niveles_mayores_o_iguales() -> None:
    pila: Pila = []
    empujar_seccion(pila, 1, "A")
    empujar_seccion(pila, 2, "B")
    empujar_seccion(pila, 3, "C")

    assert empujar_seccion(pila, 2, "D") == ["A"]
    assert rutas(pila) == ["A", "D"]


def test_salto_de_nivel_h1_a_h3() -> None:
    pila: Pila = []
    empujar_seccion(pila, 1, "A")
    empujar_seccion(pila, 3, "C")

    assert empujar_seccion(pila, 2, "B") == ["A"]


def test_texto_vacio_cierra_niveles_pero_no_apila() -> None:
    pila: Pila = []
    empujar_seccion(pila, 1, "A")
    empujar_seccion(pila, 2, "B")

    assert empujar_seccion(pila, 2, "") == ["A"]
    assert rutas(pila) == ["A"]
