"""Pruebas del parser de atributos PBF/MVT."""

from pathlib import Path

import mapbox_vector_tile

from lib.parser.parsers import PbfParser


def test_pbf_parser_extrae_atributos_mvt_y_filtra_renderizado(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ruta = tmp_path / "mapa.pbf"
    ruta.write_bytes(b"mvt controlado")
    monkeypatch.setattr(
        mapbox_vector_tile,
        "decode",
        lambda datos: {
            "lugares": {
                "features": [
                    {
                        "id": 7,
                        "properties": {
                            "name": "Bogota",
                            "population": 8000000,
                            "render_fill": "blue",
                            "source_layer": "lugares",
                        },
                    },
                    {
                        "id": 7,
                        "properties": {"name": "duplicado"},
                    },
                    {
                        "id": 8,
                        "properties": {"render_line": "red"},
                    },
                ]
            }
        },
    )

    doc = PbfParser().parse(ruta, "DOC-3-00001", 3)

    assert doc.formato == "pbf"
    assert doc.meta_extra["tipo_pbf"] == "mvt"
    assert doc.meta_extra["features_deduplicados"] == 1
    assert len(doc.blocks) == 1
    assert doc.blocks[0].tipo == "feature"
    assert "name: Bogota" in doc.blocks[0].texto
    assert "population: 8000000" in doc.blocks[0].texto
    assert "render_fill" not in doc.blocks[0].texto
    assert doc.blocks[0].ancla == {"capa": "lugares", "feature_id": 7}


def test_pbf_parser_rechaza_binario_no_reconocido(tmp_path: Path) -> None:
    ruta = tmp_path / "desconocido.pbf"
    ruta.write_bytes(b"no es un tile valido")

    _, error = PbfParser().parse_seguro(ruta, "DOC-3-00001", 3)

    assert error is not None
    assert "no reconocido" in error.excepcion
