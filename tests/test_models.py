"""Tests del modelo de datos intermedio."""

from __future__ import annotations

import pytest

from parser.models import (
    FORMATOS_PLIEGO,
    Block,
    ErrorParseo,
    ParsedDocument,
)


def _documento(**kwargs) -> ParsedDocument:
    """Documento minimo para los tests."""
    base = {
        "doc_id": "DOC-1-00001",
        "fuente": "informe.md",
        "formato": "md",
        "fenomeno": 1,
        "ruta_original": "D:/corpus/informe.md",
    }
    base.update(kwargs)
    return ParsedDocument(**base)


def test_defaults_mutables_no_se_comparten() -> None:
    b1 = Block("paragraph", "uno")
    b2 = Block("paragraph", "dos")

    b1.ancla["pagina"] = 3
    b1.seccion_path.append("Seccion")

    assert b2.ancla == {}
    assert b2.seccion_path == []


def test_tipo_de_bloque_invalido_lanza_valueerror() -> None:
    with pytest.raises(ValueError, match="tipo de bloque no permitido"):
        Block("table-row", "x")


def test_parsed_document_es_kw_only() -> None:
    # Congela la decision de kw_only: doc_id/fuente/formato/ruta_original son
    # todos str y un swap posicional pasaria desapercibido.
    with pytest.raises(TypeError):
        ParsedDocument("DOC-1-00001", "informe.md", "md", 1, "D:/x.md")  # type: ignore[misc]


def test_texto_completo_excluye_descartados() -> None:
    doc = _documento(
        blocks=[
            Block("paragraph", "primero"),
            Block("paragraph", "basura", descartado=True, motivo_descarte="calidad"),
            Block("paragraph", "segundo"),
        ]
    )

    assert doc.texto_completo() == "primero\n\nsegundo"


def test_texto_completo_sin_bloques_es_cadena_vacia() -> None:
    assert _documento().texto_completo() == ""


def test_bloques_activos_preserva_orden() -> None:
    activos = [Block("heading", "A", nivel=1), Block("paragraph", "C")]
    doc = _documento(
        blocks=[activos[0], Block("paragraph", "B", descartado=True), activos[1]]
    )

    assert doc.bloques_activos() == activos


def test_num_palabras_ignora_descartados() -> None:
    doc = _documento(
        blocks=[
            Block("paragraph", "una dos tres"),
            Block("paragraph", "cuatro cinco", descartado=True),
            Block("paragraph", "seis"),
        ]
    )

    assert doc.num_palabras() == 4


@pytest.mark.parametrize(
    ("formato", "esperado"),
    [
        ("pdf", "pdf"),
        ("html", "html"),
        ("htm", "html"),
        ("md", "md"),
        ("txt", "md"),
        ("json", "md"),
        ("xlsx", "md"),
        ("imagen", "md"),
        ("pbf", "md"),
        ("formato_desconocido", "md"),
    ],
)
def test_formato_pliego_mapeo(formato: str, esperado: str) -> None:
    resultado = _documento(formato=formato).formato_pliego()

    assert resultado == esperado
    assert resultado in FORMATOS_PLIEGO


def test_error_parseo_campos() -> None:
    err = ErrorParseo(
        ruta="D:/corpus/roto.pdf",
        formato="pdf",
        excepcion="ValueError: xref invalido",
        traceback="Traceback (most recent call last): ...",
    )

    assert err.ruta == "D:/corpus/roto.pdf"
    assert err.formato == "pdf"
    assert err.excepcion.startswith("ValueError")
    assert "Traceback" in err.traceback
