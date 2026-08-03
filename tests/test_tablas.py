"""Tests de la convencion compartida de linealizacion de filas."""

from __future__ import annotations

from parser.parsers.tablas import linealizar_fila, nombrar_cabeceras


def test_cabecera_vacia_recibe_nombre_col() -> None:
    assert nombrar_cabeceras(["a", "", "c"]) == ["a", "col2", "c"]


def test_markdown_no_desambigua_repetidas() -> None:
    # unicos=False es el comportamiento historico de markdown; cambiarlo
    # rompería los tests de text_parser.
    assert nombrar_cabeceras(["x", "x"]) == ["x", "x"]


def test_tabular_desambigua_repetidas() -> None:
    assert nombrar_cabeceras(["2020", "2020", "2020"], unicos=True) == [
        "2020",
        "2020 (2)",
        "2020 (3)",
    ]


def test_celdas_vacias_se_omiten() -> None:
    assert linealizar_fila(["a", "b", "c"], ["1", "", "3"]) == "a: 1 | c: 3"


def test_celdas_sobrantes_reciben_col() -> None:
    assert (
        linealizar_fila(["a", "b"], ["1", "2", "3"]) == "a: 1 | b: 2 | col3: 3"
    )


def test_celdas_faltantes_simplemente_no_aparecen() -> None:
    assert linealizar_fila(["a", "b", "c"], ["1"]) == "a: 1"


def test_fila_entera_vacia_da_cadena_vacia() -> None:
    assert linealizar_fila(["a", "b"], ["", ""]) == ""
