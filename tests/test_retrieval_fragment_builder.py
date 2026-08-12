"""Ensamblado de los diez fragmentos de salida."""

from __future__ import annotations

from typing import Any

import pytest

from retrieval.errores import PoolInsuficiente
from retrieval.fragment_builder import NUM_FRAGMENTOS, construir_fragmentos


def palabras(desde: int, hasta: int) -> str:
    """Texto con palabras numeradas, para controlar el solapamiento exacto."""
    return " ".join(f"p{i}" for i in range(desde, hasta))


def candidato(id_: int, texto: str, doc_id: str = "doc-a") -> dict[str, Any]:
    """Un chunk con la forma que devuelve fusion.fusionar()."""
    return {
        "id_": id_,
        "chunk_id": f"{doc_id}-chunk-{id_:04d}",
        "doc_id": doc_id,
        "texto": texto,
        "score_fusion": 1.0 - id_ / 1000,
    }


def candidatos_distintos(cantidad: int, desde: int = 0) -> list[dict[str, Any]]:
    """Candidatos sin nada de texto en comun entre si."""
    return [
        candidato(i, f"contenido completamente propio del candidato numero {i}")
        for i in range(desde, desde + cantidad)
    ]


def test_emite_el_texto_del_chunk_sin_modificarlo():
    """No parte, no expande y no concatena: el texto sale tal cual entro."""
    candidatos = candidatos_distintos(NUM_FRAGMENTOS)

    fragmentos = construir_fragmentos(candidatos)

    assert [f["text"] for f in fragmentos] == [c["texto"] for c in candidatos]
    assert [f["chunk_id"] for f in fragmentos] == [c["chunk_id"] for c in candidatos]


def test_asigna_ranks_del_uno_al_diez_en_orden_de_score():
    fragmentos = construir_fragmentos(candidatos_distintos(NUM_FRAGMENTOS + 5))

    assert len(fragmentos) == NUM_FRAGMENTOS
    assert [f["rank"] for f in fragmentos] == list(range(1, NUM_FRAGMENTOS + 1))


def test_descarta_un_candidato_que_repite_lo_ya_emitido():
    """Dos chunks adyacentes con solapamiento de chunking gastarian dos huecos.

    p2..p21 comparte 18 palabras seguidas con p0..p19: casi tres cuartas partes
    de sus ventanas de ocho palabras coinciden.
    """
    candidatos = [
        candidato(0, palabras(0, 20)),
        candidato(1, palabras(2, 22)),          # casi el mismo texto
        *candidatos_distintos(NUM_FRAGMENTOS, desde=2),
    ]

    fragmentos = construir_fragmentos(candidatos)

    emitidos = [f["chunk_id"] for f in fragmentos]
    assert "doc-a-chunk-0000" in emitidos
    assert "doc-a-chunk-0001" not in emitidos
    assert len(fragmentos) == NUM_FRAGMENTOS


def test_deja_pasar_dos_chunks_que_solo_comparten_el_solape_del_chunker():
    """Un solape corto es normal entre chunks contiguos y no debe costar un hueco.

    p12..p31 comparte solo ocho palabras con p0..p19: una unica ventana de las
    veinticinco, muy por debajo del umbral.
    """
    candidatos = [
        candidato(0, palabras(0, 20)),
        candidato(1, palabras(12, 32)),
        *candidatos_distintos(NUM_FRAGMENTOS, desde=2),
    ]

    fragmentos = construir_fragmentos(candidatos)

    emitidos = [f["chunk_id"] for f in fragmentos]
    assert "doc-a-chunk-0000" in emitidos
    assert "doc-a-chunk-0001" in emitidos


def test_salta_los_candidatos_con_texto_vacio():
    candidatos = [
        candidato(0, "   "),
        *candidatos_distintos(NUM_FRAGMENTOS, desde=1),
    ]

    fragmentos = construir_fragmentos(candidatos)

    assert all(f["text"].strip() for f in fragmentos)
    assert "doc-a-chunk-0000" not in [f["chunk_id"] for f in fragmentos]


def test_falla_si_no_llega_a_diez_fragmentos():
    with pytest.raises(PoolInsuficiente, match="9 fragmentos"):
        construir_fragmentos(candidatos_distintos(NUM_FRAGMENTOS - 1))


def test_falla_si_el_solapamiento_deja_menos_de_diez():
    """Nueve candidatos utiles mas uno repetido siguen siendo nueve."""
    candidatos = [
        *candidatos_distintos(NUM_FRAGMENTOS - 1),
        candidato(99, "contenido completamente propio del candidato numero 0"),
    ]

    with pytest.raises(PoolInsuficiente, match="descartados por solapamiento"):
        construir_fragmentos(candidatos)
