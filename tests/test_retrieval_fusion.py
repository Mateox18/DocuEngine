"""Fusion multi-encoder por RRF y CombSUM."""

from __future__ import annotations

from typing import Any

import pytest

from retrieval.fusion import K0_RRF, fusionar


def recuperado(id_: int, score: float = 0.5, doc_id: str = "doc-a") -> dict[str, Any]:
    """Un registro con la forma que devuelve IndexStore.buscar()."""
    return {
        "id_": id_,
        "chunk_id": f"{doc_id}-chunk-{id_:04d}",
        "doc_id": doc_id,
        "texto": f"contenido {id_}",
        "fuente": f"{doc_id}.pdf",
        "seccion_path": [],
        "posicion": id_,
        "score": score,
    }


def test_rrf_combina_rangos_de_los_dos_encoders():
    """Un chunto bien colocado en ambos encoders gana al que solo destaca en uno.

    Con A=[1,2,3] y B=[3,1,4]: el id 1 suma los rangos 1 y 2, el id 3 suma el 3 y
    el 1. El primero gana por muy poco, y ese margen minusculo es justo lo que RRF
    debe saber resolver.
    """
    resultados = {
        "bge-m3": [recuperado(1), recuperado(2), recuperado(3)],
        "e5-large": [recuperado(3), recuperado(1), recuperado(4)],
    }

    fusionados = fusionar(resultados, metodo="rrf")

    assert [c["id_"] for c in fusionados] == [1, 3, 2, 4]
    assert fusionados[0]["score_fusion"] == pytest.approx(
        1 / (K0_RRF + 1) + 1 / (K0_RRF + 2)
    )


def test_rrf_con_un_solo_encoder_conserva_el_orden():
    """El passthrough sale de la formula, no de un caso especial en el codigo."""
    resultados = {"bge-m3": [recuperado(5), recuperado(3), recuperado(9)]}

    fusionados = fusionar(resultados, metodo="rrf")

    assert [c["id_"] for c in fusionados] == [5, 3, 9]


def test_combsum_suma_scores_y_cuenta_cero_los_ausentes():
    resultados = {
        "bge-m3": [recuperado(1, score=0.9), recuperado(2, score=0.5)],
        "e5-large": [recuperado(2, score=0.8)],
    }

    fusionados = fusionar(resultados, metodo="combsum")

    assert [c["id_"] for c in fusionados] == [2, 1]
    assert fusionados[0]["score_fusion"] == pytest.approx(1.3)
    assert fusionados[1]["score_fusion"] == pytest.approx(0.9)


def test_no_deja_chunks_repetidos_y_registra_su_procedencia():
    resultados = {
        "bge-m3": [recuperado(7)],
        "e5-large": [recuperado(7)],
    }

    fusionados = fusionar(resultados)

    assert len(fusionados) == 1
    assert fusionados[0]["encoders"] == ["bge-m3", "e5-large"]


def test_arrastra_los_campos_que_necesitan_las_etapas_siguientes():
    fusionados = fusionar({"bge-m3": [recuperado(1, doc_id="doc-z")]})

    chunk = fusionados[0]
    assert chunk["texto"] == "contenido 1"
    assert chunk["chunk_id"] == "doc-z-chunk-0001"
    assert chunk["doc_id"] == "doc-z"
    assert "score_fusion" in chunk


def test_desempata_por_id_para_ser_reproducible():
    """Dos chunks con el mismo score deben salir siempre en el mismo orden."""
    resultados = {"bge-m3": [recuperado(9), recuperado(2)]}
    fusionados = fusionar(resultados, metodo="combsum")

    assert [c["id_"] for c in fusionados] == [2, 9]


def test_rechaza_un_metodo_desconocido():
    with pytest.raises(ValueError, match="desconocido"):
        fusionar({"bge-m3": []}, metodo="borda")
