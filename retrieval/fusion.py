"""Combinacion de las listas de varios encoders en una sola.

Aritmetica pura sobre rangos o scores. Ningun modelo interviene en la decision:
la restriccion 8.3 del pliego lo prohibe, y ademas no haria falta.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Constante estandar de Reciprocal Rank Fusion. Amortigua las primeras
# posiciones: sin ella, el primer puesto de un encoder valdria el doble que el
# segundo, y la fusion se convertiria en la opinion del encoder mas seguro.
K0_RRF = 60

METODOS = ("rrf", "combsum")

# Lo que se arrastra de cada chunk hacia las etapas siguientes. `texto` viaja sin
# tocar: fragment_builder lo emite tal cual.
CLAVES_ARRASTRADAS = ("id_", "chunk_id", "doc_id", "texto", "fuente", "seccion_path", "posicion")


def _proyectar(registro: dict[str, Any]) -> dict[str, Any]:
    """Copia de un chunk con solo los campos que necesitan las etapas siguientes."""
    return {clave: registro.get(clave) for clave in CLAVES_ARRASTRADAS}


def fusionar(
    resultados_por_encoder: dict[str, list[dict[str, Any]]], metodo: str = "rrf"
) -> list[dict[str, Any]]:
    """Unifica los resultados de todos los encoders, sin chunks repetidos.

    RRF es el metodo por defecto porque combina RANGOS, no scores: dos encoders
    distintos producen similitudes en escalas que no son comparables entre si, y
    sumarlas directamente deja que el de scores mas altos domine la mezcla sin ser
    mejor. CombSUM queda disponible por parametro para poder contrastarlo.

    Con un solo encoder no hace falta ningun caso especial: RRF sobre una unica
    lista da 1/(60+rango), que decrece de forma monotona con el rango y por tanto
    preserva el orden original.
    """
    if metodo not in METODOS:
        raise ValueError(f"Metodo de fusion desconocido: {metodo!r}. Validos: {METODOS}")

    acumulado: dict[int, dict[str, Any]] = {}
    puntuacion: dict[int, float] = {}
    procedencia: dict[int, list[str]] = {}

    # sorted() y no el orden de llegada del dict: el orden de recorrido decide los
    # desempates, y la ejecucion tiene que ser reproducible.
    for nombre in sorted(resultados_por_encoder):
        for rango, registro in enumerate(resultados_por_encoder[nombre], start=1):
            id_ = int(registro["id_"])
            if id_ not in acumulado:
                acumulado[id_] = _proyectar(registro)
                puntuacion[id_] = 0.0
                procedencia[id_] = []

            if metodo == "rrf":
                puntuacion[id_] += 1.0 / (K0_RRF + rango)
            else:
                # CombSUM: un chunk ausente del top-k de un encoder aporta 0, que
                # es exactamente lo que ocurre al no sumar nada por el.
                puntuacion[id_] += float(registro["score"])

            procedencia[id_].append(nombre)

    fusionados: list[dict[str, Any]] = []
    for id_, chunk in acumulado.items():
        chunk["score_fusion"] = puntuacion[id_]
        chunk["encoders"] = procedencia[id_]  # solo depuracion, no va al JSON final
        fusionados.append(chunk)

    fusionados.sort(key=lambda c: (-c["score_fusion"], c["id_"]))
    logger.debug(
        "Fusion %s: %d chunks unicos desde %d encoders",
        metodo, len(fusionados), len(resultados_por_encoder),
    )
    return fusionados
