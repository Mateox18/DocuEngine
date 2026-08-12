"""Validacion del esquema de salida (9.3.1)."""

from __future__ import annotations

from typing import Any

from retrieval.schema import LIMITE_PALABRAS, validar_resultado


def resultado_valido(**cambios: Any) -> dict[str, Any]:
    """Resultado que cumple el esquema, con los campos que se quieran alterar."""
    base = {
        "query_id": "q001",
        "documents": [{"rank": i, "doc_id": f"doc-{i}"} for i in range(1, 4)],
        "fragments": [
            {
                "rank": i,
                "chunk_id": f"doc-1-chunk-{i:04d}",
                "doc_id": "doc-1",
                "text": f"texto del fragmento numero {i}",
            }
            for i in range(1, 11)
        ],
    }
    base.update(cambios)
    return base


def test_acepta_un_resultado_bien_formado():
    valido, errores = validar_resultado(resultado_valido())
    assert valido, errores


def test_rechaza_query_id_con_formato_distinto():
    for query_id in ("1", "q1", "q0001", "Q001", "consulta-1"):
        valido, errores = validar_resultado(resultado_valido(query_id=query_id))
        assert not valido
        assert any("query_id" in error for error in errores)


def test_rechaza_numero_de_fragmentos_distinto_de_diez():
    completos = resultado_valido()["fragments"]

    for fragmentos in (completos[:9], completos + [dict(completos[0], rank=11)]):
        valido, errores = validar_resultado(resultado_valido(fragments=fragmentos))
        assert not valido
        assert any("fragments" in error for error in errores)


def test_rechaza_ranks_repetidos():
    fragmentos = resultado_valido()["fragments"]
    fragmentos[3]["rank"] = 5   # ahora hay dos rank=5 y ningun rank=4

    valido, errores = validar_resultado(resultado_valido(fragments=fragmentos))
    assert not valido
    assert any("rank" in error for error in errores)


def test_rechaza_texto_vacio():
    fragmentos = resultado_valido()["fragments"]
    fragmentos[0]["text"] = "   "

    valido, errores = validar_resultado(resultado_valido(fragments=fragmentos))
    assert not valido
    assert any("text" in error for error in errores)


def test_rechaza_documentos_repetidos():
    documentos = [{"rank": i, "doc_id": "doc-igual"} for i in range(1, 4)]

    valido, errores = validar_resultado(resultado_valido(documents=documentos))
    assert not valido
    assert any("duplicado" in error for error in errores)


def test_rechaza_campos_fuera_del_esquema():
    con_extra = resultado_valido(score_fusion=0.9)
    valido, errores = validar_resultado(con_extra)
    assert not valido
    assert any("no contempladas" in error for error in errores)

    fragmentos = resultado_valido()["fragments"]
    fragmentos[0]["encoders"] = ["bge-m3"]
    valido, errores = validar_resultado(resultado_valido(fragments=fragmentos))
    assert not valido
    assert any("no contempladas" in error for error in errores)


def test_rechaza_un_fragmento_por_encima_del_limite_de_palabras():
    """Es el unico rastro del limite de 250 palabras que queda en el modulo.

    Ninguna otra parte de la capa lo comprueba: se asume que los chunks llegan con
    el tamano correcto. Si este test deja de fallar ante 251 palabras, la
    suposicion se vuelve incomprobable y un `resultados.jsonl` invalido podria
    entregarse sin que nada avise.
    """
    fragmentos = resultado_valido()["fragments"]
    fragmentos[0]["text"] = " ".join(f"palabra{i}" for i in range(LIMITE_PALABRAS + 1))

    valido, errores = validar_resultado(resultado_valido(fragments=fragmentos))
    assert not valido
    assert any(str(LIMITE_PALABRAS) in error for error in errores)


def test_acepta_exactamente_el_limite_de_palabras():
    fragmentos = resultado_valido()["fragments"]
    fragmentos[0]["text"] = " ".join(f"palabra{i}" for i in range(LIMITE_PALABRAS))

    valido, errores = validar_resultado(resultado_valido(fragments=fragmentos))
    assert valido, errores


def test_acumula_todos_los_errores_en_vez_de_parar_en_el_primero():
    roto = resultado_valido(query_id="malo", documents=[], fragments=[])
    valido, errores = validar_resultado(roto)

    assert not valido
    assert len(errores) >= 3
