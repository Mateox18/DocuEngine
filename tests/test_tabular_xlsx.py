"""Tests del parser tabular sobre libros de Excel."""

from __future__ import annotations

from datetime import datetime

import pytest

from parser.models import ParsedDocument
from parser.parsers import tabular_parser
from parser.parsers.base import ParserError
from parser.parsers.tabular_parser import TabularParser

from conftest import EscribirBytes, LibroExcel


def _parsear(ruta) -> ParsedDocument:
    return TabularParser().parse(ruta, "DOC-1-00001", 1)


def _filas(doc: ParsedDocument) -> list[str]:
    return [b.texto for b in doc.blocks if b.tipo == "table_row"]


def test_todas_las_hojas_se_recorren(libro_excel: LibroExcel) -> None:
    ruta = libro_excel(
        "d.xlsx",
        {
            "Uno": [["pais", "anio"], ["Colombia", 2023]],
            "Dos": [["ciudad", "poblacion"], ["Bogota", 8000000]],
        },
    )

    doc = _parsear(ruta)

    assert len(_filas(doc)) == 2
    assert {b.ancla["hoja"] for b in doc.blocks} == {"Uno", "Dos"}


def test_prefijo_hoja_en_el_texto_y_en_seccion_path(libro_excel: LibroExcel) -> None:
    ruta = libro_excel("d.xlsx", {"Data 2.1": [["pais", "anio"], ["Colombia", 2023]]})

    doc = _parsear(ruta)

    assert _filas(doc)[0].startswith("[Hoja: Data 2.1] ")
    assert doc.blocks[0].seccion_path == ["Data 2.1"]


def test_hoja_vacia_se_ignora_y_se_registra(libro_excel: LibroExcel) -> None:
    ruta = libro_excel(
        "d.xlsx",
        {"Datos": [["pais", "anio"], ["Colombia", 2023]], "Vacia": []},
    )

    doc = _parsear(ruta)

    assert doc.meta_extra["hojas_vacias"] == ["Vacia"]
    assert len(_filas(doc)) == 1


def test_ancla_hoja_y_fila(libro_excel: LibroExcel) -> None:
    ruta = libro_excel(
        "d.xlsx",
        {"H": [["Titulo del dataset"], ["pais", "anio"], ["Colombia", 2023]]},
    )

    doc = _parsear(ruta)

    assert doc.blocks[0].ancla == {
        "hoja": "H",
        "fila": 2,
        "columnas": ["pais", "anio"],
    }


def test_preambulo_por_hoja(libro_excel: LibroExcel) -> None:
    ruta = libro_excel(
        "d.xlsx",
        {
            "A": [["Titulo A"], ["pais", "anio"], ["Colombia", 2023]],
            "B": [["Titulo B"], ["ciudad", "hab"], ["Bogota", 8]],
        },
    )

    doc = _parsear(ruta)

    assert "Titulo A" in doc.meta_extra["preambulo"]
    assert "Titulo B" in doc.meta_extra["preambulo"]
    assert doc.titulo == "Titulo A"


def test_enteros_no_salen_como_punto_cero(libro_excel: LibroExcel) -> None:
    ruta = libro_excel("d.xlsx", {"H": [["pais", "anio"], ["Colombia", 2019]]})

    assert "anio: 2019" in _filas(_parsear(ruta))[0]


def test_float_no_entero_conserva_decimales(libro_excel: LibroExcel) -> None:
    ruta = libro_excel("d.xlsx", {"H": [["pais", "tasa"], ["Colombia", 0.75]]})

    assert "tasa: 0.75" in _filas(_parsear(ruta))[0]


def test_datetime_se_serializa_iso(libro_excel: LibroExcel) -> None:
    ruta = libro_excel(
        "d.xlsx",
        {"H": [["evento", "fecha"], ["lanzamiento", datetime(2024, 3, 15)]]},
    )

    assert "fecha: 2024-03-15" in _filas(_parsear(ruta))[0]


def test_celdas_none_se_omiten(libro_excel: LibroExcel) -> None:
    ruta = libro_excel(
        "d.xlsx", {"H": [["a", "b", "c"], ["1", None, "3"]]}
    )

    assert _filas(_parsear(ruta))[0].endswith("a: 1 | c: 3")


def test_booleanos(libro_excel: LibroExcel) -> None:
    ruta = libro_excel("d.xlsx", {"H": [["pais", "activo"], ["Colombia", True]]})

    assert "activo: true" in _filas(_parsear(ruta))[0]


def test_limite_de_filas_es_global_entre_hojas(
    libro_excel: LibroExcel, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tabular_parser, "LIMITE_FILAS", 3)
    ruta = libro_excel(
        "d.xlsx",
        {
            "A": [["pais", "anio"], *[["Colombia", 2000 + i] for i in range(5)]],
            "B": [["pais", "anio"], *[["Brasil", 2000 + i] for i in range(5)]],
        },
    )

    doc = _parsear(ruta)

    assert len(_filas(doc)) == 3
    assert doc.meta_extra["truncado"] is True
    # El corte es global: la segunda hoja no llega a procesarse.
    assert {b.ancla["hoja"] for b in doc.blocks} == {"A"}


def test_formato_y_pliego(libro_excel: LibroExcel) -> None:
    ruta = libro_excel("d.xlsx", {"H": [["a", "b"], ["1", "2"]]})

    doc = _parsear(ruta)

    assert (doc.formato, doc.formato_pliego()) == ("xlsx", "md")


# ------------------------------------------------------------------- .xls


def test_xls_que_en_realidad_es_xlsx(
    libro_excel: LibroExcel, escribir_bytes: EscribirBytes
) -> None:
    real = libro_excel("real.xlsx", {"H": [["pais", "anio"], ["Colombia", 2023]]})
    disfrazado = escribir_bytes("d.xls", real.read_bytes())

    doc = _parsear(disfrazado)

    assert any("en realidad es .xlsx" in e for e in doc.errores)
    assert len(_filas(doc)) == 1


def test_xls_que_en_realidad_es_html(escribir_bytes: EscribirBytes) -> None:
    ruta = escribir_bytes("d.xls", b"<html><body><table></table></body></html>")

    with pytest.raises(ParserError, match="HtmlParser"):
        _parsear(ruta)


def test_xls_irreconocible(escribir_bytes: EscribirBytes) -> None:
    ruta = escribir_bytes("d.xls", b"basura binaria cualquiera")

    with pytest.raises(ParserError, match="no es un .xls reconocible"):
        _parsear(ruta)
