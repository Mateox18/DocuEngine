"""Agregacion a nivel de documento por max pooling."""

from __future__ import annotations

from typing import Any

import pytest

from retrieval.aggregation import agregar_a_documentos
from retrieval.errores import PoolInsuficiente


def fusionado(id_: int, doc_id: str, score: float) -> dict[str, Any]:
    """Un chunk con la forma que devuelve fusion.fusionar()."""
    return {
        "id_": id_,
        "chunk_id": f"{doc_id}-chunk-{id_:04d}",
        "doc_id": doc_id,
        "texto": f"contenido {id_}",
        "score_fusion": score,
    }


def test_puntua_cada_documento_con_su_mejor_chunk():
    """doc-b gana con un unico chunk fuerte frente a tres mediocres de doc-a.

    Es la diferencia entre max pooling y suma: sumando, doc-a ganaria con 1.2
    frente a 0.9 sin que ninguno de sus chunks responda la consulta.
    """
    chunks = [
        fusionado(1, "doc-a", 0.4),
        fusionado(2, "doc-a", 0.4),
        fusionado(3, "doc-a", 0.4),
        fusionado(4, "doc-b", 0.9),
        fusionado(5, "doc-c", 0.6),
    ]

    documentos = agregar_a_documentos(chunks)

    assert [d["doc_id"] for d in documentos] == ["doc-b", "doc-c", "doc-a"]
    assert [d["rank"] for d in documentos] == [1, 2, 3]


def test_devuelve_exactamente_tres_documentos_sin_repetir():
    chunks = [fusionado(i, f"doc-{i}", 1.0 - i / 10) for i in range(6)]

    documentos = agregar_a_documentos(chunks)

    assert len(documentos) == 3
    assert len({d["doc_id"] for d in documentos}) == 3


def test_usa_el_pool_completo_y_no_solo_los_diez_primeros():
    """Un documento cuyo mejor chunk esta en el puesto 40 debe poder entrar.

    Por eso agregar_a_documentos recibe el pool entero y no los diez fragmentos
    finales.
    """
    chunks = [fusionado(i, "doc-ruidoso", 0.5) for i in range(40)]
    chunks.append(fusionado(99, "doc-escondido", 0.95))
    chunks.append(fusionado(98, "doc-otro", 0.1))

    documentos = agregar_a_documentos(chunks)

    assert documentos[0]["doc_id"] == "doc-escondido"


def test_falla_si_no_hay_tres_documentos_distintos():
    chunks = [fusionado(1, "doc-a", 0.9), fusionado(2, "doc-b", 0.8)]

    with pytest.raises(PoolInsuficiente, match="2 documentos"):
        agregar_a_documentos(chunks)


def test_desempata_por_doc_id_para_ser_reproducible():
    chunks = [
        fusionado(1, "doc-z", 0.5),
        fusionado(2, "doc-a", 0.5),
        fusionado(3, "doc-m", 0.5),
    ]

    documentos = agregar_a_documentos(chunks)

    assert [d["doc_id"] for d in documentos] == ["doc-a", "doc-m", "doc-z"]
