"""Tests del modelo de datos intermedio."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from parser.models import (
    FORMATOS_PLIEGO,
    SCHEMA_VERSION,
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


def test_block_to_dict_y_from_dict_round_trip() -> None:
    bloque = Block(
        "heading",
        "Resumen",
        nivel=2,
        ancla={"linea": 10},
        idioma="es",
        seccion_path=["Informe"],
        descartado=True,
        motivo_descarte="duplicado",
    )

    datos = bloque.to_dict()
    reconstruido = Block.from_dict(datos)

    assert datos == {
        "tipo": "heading",
        "texto": "Resumen",
        "nivel": 2,
        "ancla": {"linea": 10},
        "idioma": "es",
        "seccion_path": ["Informe"],
        "descartado": True,
        "motivo_descarte": "duplicado",
    }
    assert reconstruido == bloque


def test_block_to_dict_no_expone_mutables_internos() -> None:
    bloque = Block("paragraph", "texto", ancla={"linea": 1}, seccion_path=["A"])
    datos = bloque.to_dict()

    datos["ancla"]["linea"] = 99
    datos["seccion_path"].append("B")

    assert bloque.ancla == {"linea": 1}
    assert bloque.seccion_path == ["A"]


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


def test_parsed_document_to_dict_y_from_dict_round_trip() -> None:
    doc = _documento(
        titulo="Informe",
        idioma="es",
        hash_contenido="abc123",
        meta_extra={"autor": "Equipo"},
        errores=["warning"],
        blocks=[
            Block("heading", "Informe", nivel=1),
            Block("paragraph", "Contenido", ancla={"linea": 3}),
        ],
    )

    datos = doc.to_dict()
    reconstruido = ParsedDocument.from_dict(datos)

    assert datos["schema_version"] == SCHEMA_VERSION
    assert datos["blocks"] == [bloque.to_dict() for bloque in doc.blocks]
    assert reconstruido == doc


def test_to_dict_es_json_serializable() -> None:
    doc = _documento(
        meta_extra={"escaneado": True},
        blocks=[Block("paragraph", "a", ancla={"bbox": [1.0, 2.0]})],
    )

    json.dumps(doc.to_dict())


def test_block_to_dict_rechaza_ancla_no_json_nativa() -> None:
    bloque = Block("paragraph", "texto", ancla={"ruta": Path("archivo.pdf")})

    with pytest.raises(TypeError, match="Block.ancla.ruta"):
        bloque.to_dict()


def test_block_to_dict_rechaza_tuplas_en_ancla() -> None:
    bloque = Block("paragraph", "texto", ancla={"bbox": (1.0, 2.0)})

    with pytest.raises(TypeError, match="Block.ancla.bbox"):
        bloque.to_dict()


def test_parsed_document_to_dict_rechaza_meta_extra_no_json_nativo() -> None:
    doc = _documento(meta_extra={"formatos": {"pdf", "html"}})

    with pytest.raises(TypeError, match="ParsedDocument.meta_extra.formatos"):
        doc.to_dict()


def test_parsed_document_to_dict_rechaza_claves_no_string_en_meta_extra() -> None:
    doc = _documento(meta_extra={1: "valor"})

    with pytest.raises(TypeError, match="clave no str"):
        doc.to_dict()


def test_parsed_document_from_dict_exige_schema_version() -> None:
    datos = _documento().to_dict()
    datos.pop("schema_version")

    with pytest.raises(ValueError, match="schema_version no soportado"):
        ParsedDocument.from_dict(datos)


def test_parsed_document_from_dict_rechaza_schema_version_incompatible() -> None:
    datos = _documento().to_dict()
    datos["schema_version"] = SCHEMA_VERSION + 1

    with pytest.raises(ValueError, match="schema_version no soportado"):
        ParsedDocument.from_dict(datos)


def test_parsed_document_to_dict_no_expone_mutables_internos() -> None:
    doc = _documento(
        meta_extra={"tema": "orbita"},
        errores=["uno"],
        blocks=[Block("paragraph", "texto", ancla={"linea": 1})],
    )

    datos = doc.to_dict()
    datos["meta_extra"]["tema"] = "cambiado"
    datos["errores"].append("dos")
    datos["blocks"][0]["ancla"]["linea"] = 99

    assert doc.meta_extra == {"tema": "orbita"}
    assert doc.errores == ["uno"]
    assert doc.blocks[0].ancla == {"linea": 1}


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


def test_error_parseo_to_dict_y_from_dict_round_trip() -> None:
    err = ErrorParseo(
        ruta="D:/corpus/roto.pdf",
        formato="pdf",
        excepcion="ValueError: xref invalido",
        traceback="Traceback (most recent call last): ...",
    )

    datos = err.to_dict()

    assert datos == {
        "ruta": "D:/corpus/roto.pdf",
        "formato": "pdf",
        "excepcion": "ValueError: xref invalido",
        "traceback": "Traceback (most recent call last): ...",
    }
    assert ErrorParseo.from_dict(datos) == err
