"""Agregacion de chunks a nivel de documento por max pooling (8.6)."""

from __future__ import annotations

import logging
from typing import Any

from retrieval.errores import PoolInsuficiente

logger = logging.getLogger(__name__)

NUM_DOCUMENTOS = 3


def agregar_a_documentos(chunks_fusionados: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Devuelve el top-3 de documentos, de mayor a menor relevancia.

    MAX POOLING: la puntuacion de un documento es la de su MEJOR chunk. Es la
    estrategia elegida por el equipo entre las que permite el pliego. Frente a la
    suma, no premia a los documentos largos por el mero hecho de aportar mas
    chunks al pool; frente a la media, no castiga a un documento que responde la
    consulta en un solo parrafo y habla de otra cosa en el resto.

    Se espera recibir el POOL COMPLETO de candidatos (k=100 tipico), no los diez
    fragmentos finales: un documento con un unico chunk muy relevante que no llega
    a colarse entre los diez debe poder entrar igualmente al top-3.
    """
    mejor_por_doc: dict[str, float] = {}

    for chunk in chunks_fusionados:
        doc_id = chunk["doc_id"]
        score = float(chunk["score_fusion"])
        if doc_id not in mejor_por_doc or score > mejor_por_doc[doc_id]:
            mejor_por_doc[doc_id] = score

    if len(mejor_por_doc) < NUM_DOCUMENTOS:
        raise PoolInsuficiente(
            f"Solo hay {len(mejor_por_doc)} documentos distintos en el pool de "
            f"{len(chunks_fusionados)} chunks; el esquema exige {NUM_DOCUMENTOS}."
        )

    # Desempate por doc_id: dos documentos con el mismo score maximo tienen que
    # quedar siempre en el mismo orden entre ejecuciones.
    ordenados = sorted(mejor_por_doc.items(), key=lambda par: (-par[1], par[0]))

    return [
        {"rank": rank, "doc_id": doc_id}
        for rank, (doc_id, _) in enumerate(ordenados[:NUM_DOCUMENTOS], start=1)
    ]
