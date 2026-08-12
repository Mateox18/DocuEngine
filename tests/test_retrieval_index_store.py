"""Carga de la base vectorial y busqueda de vecinos."""

from __future__ import annotations

import json
import logging

import pytest

from conftest import chunk_falso, vector_unitario
from retrieval.errores import IndiceInvalido
from retrieval.index_store import IndexStore

ENCODER = "bge-m3"


def test_empareja_cada_vector_con_su_texto_aunque_los_ids_tengan_huecos(
    crear_base_vectorial,
):
    """Es el fallo silencioso que este modulo existe para evitar.

    Los ids 0, 1, 5, 7 son los que deja un corpus donde algunos chunks fallaron al
    vectorizar (encoder/enc.py:70-76). Con un lookup posicional, el id 5 devolveria
    el texto del tercer chunk y nadie se enteraria.
    """
    registros = [
        chunk_falso(id_=id_, doc_id="doc-a", posicion=posicion)
        for posicion, id_ in enumerate([0, 1, 5, 7])
    ]
    store = IndexStore(crear_base_vectorial(registros))

    resultados = store.buscar(vector_unitario(5), ENCODER, k=1)

    assert resultados[0]["id_"] == 5
    assert resultados[0]["texto"] == "contenido del chunk numero 5"


def test_aplana_la_metadata_anidada(crear_base_vectorial):
    registros = [chunk_falso(id_=0, doc_id="doc-x", posicion=3)]
    store = IndexStore(crear_base_vectorial(registros))

    resultado = store.buscar(vector_unitario(0), ENCODER, k=1)[0]

    assert resultado["chunk_id"] == "doc-x-chunk-0003"
    assert resultado["fuente"] == "doc-x.pdf"
    assert resultado["posicion"] == 3
    assert resultado["score"] == pytest.approx(1.0, abs=1e-5)


def test_descarta_los_menos_uno_cuando_k_supera_el_tamano_del_indice(
    crear_base_vectorial,
):
    registros = [chunk_falso(id_=i) for i in range(3)]
    store = IndexStore(crear_base_vectorial(registros))

    resultados = store.buscar(vector_unitario(0), ENCODER, k=10)

    assert len(resultados) == 3
    assert all(r["id_"] != -1 for r in resultados)


def test_devuelve_los_resultados_de_mayor_a_menor_score(crear_base_vectorial):
    registros = [chunk_falso(id_=i) for i in range(5)]
    store = IndexStore(crear_base_vectorial(registros))

    resultados = store.buscar(vector_unitario(2), ENCODER, k=5)

    scores = [r["score"] for r in resultados]
    assert scores == sorted(scores, reverse=True)
    assert resultados[0]["id_"] == 2


def test_aborta_si_los_ids_del_indice_y_de_la_metadata_no_coinciden(
    crear_base_vectorial,
):
    registros = [chunk_falso(id_=i) for i in range(3)]
    base = crear_base_vectorial(registros)

    ruta = base / f"encoder_{ENCODER}" / "metadata.jsonl"
    lineas = ruta.read_text(encoding="utf-8").splitlines()
    ultimo = json.loads(lineas[-1])
    ultimo["id_"] = 999
    lineas[-1] = json.dumps(ultimo, ensure_ascii=False)
    ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8", newline="\n")

    with pytest.raises(IndiceInvalido, match="no coinciden"):
        IndexStore(base)


def test_aborta_si_falta_una_linea_de_metadata(crear_base_vectorial):
    registros = [chunk_falso(id_=i) for i in range(3)]
    base = crear_base_vectorial(registros)

    ruta = base / f"encoder_{ENCODER}" / "metadata.jsonl"
    lineas = ruta.read_text(encoding="utf-8").splitlines()
    ruta.write_text("\n".join(lineas[:-1]) + "\n", encoding="utf-8", newline="\n")

    with pytest.raises(IndiceInvalido, match="lineas de metadata"):
        IndexStore(base)


def test_aborta_si_la_dimension_no_es_la_del_modelo_configurado(crear_base_vectorial):
    registros = [chunk_falso(id_=i) for i in range(2)]
    base = crear_base_vectorial(
        registros, vectores=[vector_unitario(i, 8) for i in range(2)], dim=8
    )

    with pytest.raises(IndiceInvalido, match="dimension"):
        IndexStore(base)


def test_falla_si_el_encoder_no_esta_en_config_encoders(crear_base_vectorial):
    base = crear_base_vectorial([chunk_falso(id_=0)], nombre="inventado")

    with pytest.raises(KeyError, match="desconocido"):
        IndexStore(base)


def test_avisa_si_los_vectores_del_indice_no_son_unitarios(
    crear_base_vectorial, caplog
):
    """La suposicion del proyecto es que el modelo normaliza. Esto la hace falsable."""
    registros = [chunk_falso(id_=i) for i in range(4)]
    base = crear_base_vectorial(
        registros, vectores=[vector_unitario(i) * 3.0 for i in range(4)]
    )

    with caplog.at_level(logging.WARNING):
        IndexStore(base)

    assert "NO son unitarios" in caplog.text


def test_no_avisa_cuando_los_vectores_son_unitarios(crear_base_vectorial, caplog):
    registros = [chunk_falso(id_=i) for i in range(4)]

    with caplog.at_level(logging.WARNING):
        IndexStore(crear_base_vectorial(registros))

    assert "NO son unitarios" not in caplog.text


def test_busca_en_todos_los_encoders_en_orden_estable(
    crear_base_vectorial, monkeypatch
):
    registros = [chunk_falso(id_=i) for i in range(3)]
    store = IndexStore(crear_base_vectorial(registros))

    monkeypatch.setattr(
        "retrieval.index_store.codificar_consulta",
        lambda texto, encoder_nombre: vector_unitario(1),
    )

    por_encoder = store.buscar_todos_los_encoders("una consulta", k=2)

    assert list(por_encoder) == [ENCODER]
    assert por_encoder[ENCODER][0]["id_"] == 1


def test_falla_con_un_directorio_sin_encoders(tmp_path):
    vacio = tmp_path / "base_vectorial"
    vacio.mkdir()

    with pytest.raises(FileNotFoundError, match="encoder_"):
        IndexStore(vacio)
