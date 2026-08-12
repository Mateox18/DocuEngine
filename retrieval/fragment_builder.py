"""Ensamblado de los diez fragmentos de salida.

Este modulo asume que los chunks recuperados vienen ya con el tamano correcto, asi
que NO parte, NO expande y NO concatena: el `texto` del chunk se emite tal cual.
Esa decision elimina la busqueda de vecinos y, con ella, la necesidad de acceder al
indice, de reconstruir vectores y de segmentar en oraciones. La funcion queda pura
sobre la lista de candidatos.

Lo unico que sobrevive es decidir CUALES de los candidatos ocupan los diez huecos,
y ahi si hay trabajo: el chunker solapa a proposito unas cuantas oraciones entre
chunks consecutivos (`agrupador` reutiliza `act[-over:]` sin modificarlo,
`chunker/fragmentador.py:62`), de modo que dos chunks adyacentes del mismo
documento comparten texto palabra por palabra. Si los dos entran, gastan dos de
los diez huecos en decir casi lo mismo.
"""

from __future__ import annotations

import logging
from typing import Any

from retrieval.errores import PoolInsuficiente

logger = logging.getLogger(__name__)

NUM_FRAGMENTOS = 10

# Ventana de palabras con la que se mide el parecido entre dos fragmentos. Ocho es
# lo bastante larga para que una coincidencia sea texto compartido de verdad y no
# una frase hecha, y lo bastante corta para detectar el solapamiento aunque el
# chunker solo repita una oracion.
TAM_SHINGLE = 8
UMBRAL_JACCARD = 0.5


def _shingles(texto: str) -> frozenset[tuple[str, ...]]:
    """Conjunto de ventanas de TAM_SHINGLE palabras consecutivas del texto."""
    palabras = texto.split()
    if len(palabras) < TAM_SHINGLE:
        # Un texto mas corto que la ventana se compara consigo mismo entero; si no,
        # no generaria ninguna ventana y pareceria distinto de todo.
        return frozenset({tuple(palabras)}) if palabras else frozenset()
    return frozenset(
        tuple(palabras[inicio:inicio + TAM_SHINGLE])
        for inicio in range(len(palabras) - TAM_SHINGLE + 1)
    )


def _jaccard(a: frozenset[Any], b: frozenset[Any]) -> float:
    """Proporcion de ventanas compartidas entre dos textos."""
    if not a or not b:
        return 0.0
    union = len(a | b)
    return len(a & b) / union if union else 0.0


def _verificar(fragmentos: list[dict[str, Any]]) -> None:
    """Comprueba las invariantes de la salida antes de devolverla.

    El limite de 250 palabras no se comprueba aqui a proposito: es contrato de
    salida y vive en `schema.py`, en un solo sitio, para que no puedan discrepar.
    """
    if len(fragmentos) != NUM_FRAGMENTOS:
        raise AssertionError(
            f"Se construyeron {len(fragmentos)} fragmentos, se exigen {NUM_FRAGMENTOS}"
        )
    ranks = [f["rank"] for f in fragmentos]
    if ranks != list(range(1, NUM_FRAGMENTOS + 1)):
        raise AssertionError(f"Los rank deben ser 1..{NUM_FRAGMENTOS}; son {ranks}")
    for fragmento in fragmentos:
        if not fragmento["text"].strip():
            raise AssertionError(f"Fragmento {fragmento['rank']} con texto vacio")


def construir_fragmentos(
    candidatos_fusionados: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Selecciona los diez fragmentos de salida entre los candidatos fusionados.

    Recorre los candidatos en el orden en que llegan -que es el de su score de
    fusion- y va emitiendo los que no repiten lo ya dicho. El `rank` sale de ese
    orden de emision, sin reordenar despues.
    """
    fragmentos: list[dict[str, Any]] = []
    shingles_emitidos: list[frozenset[tuple[str, ...]]] = []
    descartados = 0

    for candidato in candidatos_fusionados:
        texto = candidato.get("texto") or ""
        if not texto.strip():
            continue

        shingles = _shingles(texto)
        if any(_jaccard(shingles, previo) > UMBRAL_JACCARD for previo in shingles_emitidos):
            descartados += 1
            continue

        fragmentos.append({
            "rank": len(fragmentos) + 1,
            "chunk_id": candidato["chunk_id"],
            "doc_id": candidato["doc_id"],
            "text": texto,
        })
        shingles_emitidos.append(shingles)

        if len(fragmentos) == NUM_FRAGMENTOS:
            break

    if len(fragmentos) < NUM_FRAGMENTOS:
        raise PoolInsuficiente(
            f"Solo se pudieron construir {len(fragmentos)} fragmentos de "
            f"{NUM_FRAGMENTOS} a partir de {len(candidatos_fusionados)} candidatos "
            f"({descartados} descartados por solapamiento)."
        )

    if descartados:
        logger.debug("%d candidatos descartados por solapamiento", descartados)

    _verificar(fragmentos)
    return fragmentos
