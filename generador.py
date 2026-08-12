"""Genera `resultados.jsonl` a partir de la base vectorial ya construida.

Entregable #4 del pliego (1.4). Este script SOLO lee: no indexa, no reentrena y no
reconstruye nada. Su unico requisito duro es que dos ejecuciones con los mismos
argumentos produzcan el mismo archivo byte a byte; si los resultados no se pueden
reproducir, el trabajo queda excluido de la evaluacion.

FORMATO DE ENTRADA. `--consultas` espera un JSONL con un objeto por linea:

    {"query_id": "q001", "text": "texto de la consulta"}

Se elige JSONL sobre CSV porque el texto de una consulta puede traer comas,
comillas y saltos de linea, y en CSV cada una de esas tres cosas es una regla de
escapado distinta que hay que acertar en los dos extremos.

De donde sale el no-determinismo, y como se evita aqui:
  - el orden de recorrido de un dict construido sobre la marcha -> todo lo que
    afecta al orden se recorre con sorted();
  - los empates de score -> todos los ordenamientos desempatan por una clave
    estable (id_ del chunk, doc_id del documento);
  - el orden de las lineas de entrada -> las consultas se ordenan por query_id
    antes de procesarlas, no se confia en como venga el archivo.

Ningun modelo generativo interviene en ninguna rama de este script (8.3).
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
import time
from pathlib import Path
from typing import Any

# El paquete retrieval fija los hilos de torch y de faiss al importarse, y para
# que sirva de algo tiene que entrar ANTES que cualquier import de torch o numpy.
# Ver retrieval/__init__.py.
import retrieval  # noqa: F401  (import por su efecto secundario)

import faiss
import numpy as np
import sentence_transformers
import torch

from retrieval import aggregation, fragment_builder, fusion, schema
from retrieval.errores import PoolInsuficiente
from retrieval.index_store import IndexStore

logger = logging.getLogger("generador")

NUM_CONSULTAS = 50
SEMILLA = 0

# Escalera de ampliacion de k cuando el pool no da para llenar la salida. Es una
# lista FIJA y no un incremento adaptativo: el numero de reintentos tiene que
# depender solo de los datos, nunca del reloj ni del orden de ejecucion.
FACTORES_K = (1, 2, 4)


def fijar_semillas() -> None:
    """Fija las semillas de las tres fuentes de aleatoriedad del proceso.

    La inferencia de embeddings es determinista de por si, asi que en teoria esto
    no cambia nada. Es una red de seguridad barata frente a que cualquier
    dependencia decida muestrear algo en una version futura.
    """
    random.seed(SEMILLA)
    np.random.seed(SEMILLA)
    torch.manual_seed(SEMILLA)


def leer_consultas(ruta: Path) -> list[tuple[str, str]]:
    """Lee el JSONL de consultas y lo devuelve ordenado por query_id."""
    consultas: dict[str, str] = {}

    with open(ruta, encoding="utf-8") as archivo:
        for numero, linea in enumerate(archivo, start=1):
            linea = linea.strip()
            if not linea:
                continue
            try:
                objeto = json.loads(linea)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{ruta}, linea {numero}: JSON invalido ({exc})") from exc

            query_id = objeto.get("query_id")
            texto = objeto.get("text")
            if not isinstance(query_id, str) or not isinstance(texto, str):
                raise ValueError(
                    f"{ruta}, linea {numero}: se esperaban las claves 'query_id' "
                    f"(str) y 'text' (str)."
                )
            if query_id in consultas:
                raise ValueError(f"{ruta}, linea {numero}: query_id repetido ({query_id})")
            consultas[query_id] = texto

    if len(consultas) != NUM_CONSULTAS:
        raise ValueError(
            f"{ruta} trae {len(consultas)} consultas y el pliego exige exactamente "
            f"{NUM_CONSULTAS}. El archivo de salida debe tener una linea por cada una."
        )

    return sorted(consultas.items())


def procesar_consulta(
    store: IndexStore, query_id: str, texto: str, k_base: int, metodo: str
) -> tuple[dict[str, Any], int]:
    """Resuelve una consulta y devuelve (resultado, k efectivo).

    Si el pool no da para tres documentos o diez fragmentos, reintenta subiendo k
    por la escalera fija antes de rendirse.
    """
    ultimo: PoolInsuficiente | None = None

    for posicion, factor in enumerate(FACTORES_K):
        k = k_base * factor
        por_encoder = store.buscar_todos_los_encoders(texto, k)
        fusionados = fusion.fusionar(por_encoder, metodo)

        try:
            documentos = aggregation.agregar_a_documentos(fusionados)
            fragmentos = fragment_builder.construir_fragmentos(fusionados)
        except PoolInsuficiente as exc:
            ultimo = exc
            if posicion + 1 < len(FACTORES_K):
                logger.warning(
                    "%s: %s Se reintenta con k=%d.",
                    query_id, exc, k_base * FACTORES_K[posicion + 1],
                )
            continue

        return (
            {"query_id": query_id, "documents": documentos, "fragments": fragmentos},
            k,
        )

    raise PoolInsuficiente(
        f"{query_id}: no se pudo completar la salida ni con k="
        f"{k_base * FACTORES_K[-1]}. Ultimo motivo: {ultimo}"
    )


def construir_parser() -> argparse.ArgumentParser:
    """Define la interfaz de linea de comandos."""
    parser = argparse.ArgumentParser(
        description="Genera resultados.jsonl a partir de la base vectorial.",
    )
    parser.add_argument(
        "--consultas", type=Path, required=True,
        help="JSONL con las 50 consultas: {'query_id': 'q001', 'text': '...'}",
    )
    parser.add_argument(
        "--base", type=Path, default=Path("./base_vectorial"),
        help="Carpeta con los encoder_<nombre>/ (default: ./base_vectorial)",
    )
    parser.add_argument(
        "--salida", type=Path, default=Path("./resultados.jsonl"),
        help="Archivo de salida (default: ./resultados.jsonl)",
    )
    parser.add_argument(
        "--k_busqueda", type=int, default=100,
        help="Vecinos a recuperar por encoder en la busqueda inicial (default: 100)",
    )
    parser.add_argument(
        "--fusion", choices=fusion.METODOS, default="rrf",
        help="Metodo de fusion multi-encoder (default: rrf)",
    )
    parser.add_argument(
        "--estricto", action=argparse.BooleanOptionalAction, default=True,
        help="Detener todo si una linea no pasa la validacion (default: activado)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada. Devuelve el codigo de salida del proceso."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    args = construir_parser().parse_args(argv)
    fijar_semillas()

    # Las versiones van al log para poder diagnosticar por que dos maquinas
    # producen resultados distintos, que es el fallo mas caro posible aqui.
    logger.info(
        "Versiones: faiss=%s numpy=%s sentence-transformers=%s torch=%s",
        faiss.__version__, np.__version__, sentence_transformers.__version__,
        torch.__version__,
    )

    consultas = leer_consultas(args.consultas)
    store = IndexStore(args.base)

    inicio = time.perf_counter()
    resultados: list[dict[str, Any]] = []
    ampliadas: list[str] = []
    invalidas: list[str] = []

    for query_id, texto in consultas:
        resultado, k_efectivo = procesar_consulta(
            store, query_id, texto, args.k_busqueda, args.fusion
        )
        if k_efectivo != args.k_busqueda:
            ampliadas.append(f"{query_id} (k={k_efectivo})")

        valido, errores = schema.validar_resultado(resultado)
        if not valido:
            for error in errores:
                logger.error("%s no cumple el esquema -> %s", query_id, error)
            if args.estricto:
                logger.error("Modo estricto: se detiene sin escribir nada.")
                return 1
            invalidas.append(query_id)
            continue

        resultados.append(resultado)

    # newline="\n" explicito: en Windows el modo texto traduce \n a \r\n, y el
    # archivo entregado no seria el mismo que el generado en Linux. La misma
    # trampa esta documentada en tests/conftest.py:38-40.
    with open(args.salida, "w", encoding="utf-8", newline="\n") as archivo:
        for resultado in resultados:
            archivo.write(
                json.dumps(resultado, ensure_ascii=False, separators=(",", ":")) + "\n"
            )

    transcurrido = time.perf_counter() - inicio
    logger.info("--- Resumen ---")
    logger.info("Consultas procesadas: %d de %d", len(resultados), len(consultas))
    logger.info("Tiempo total: %.1f s", transcurrido)
    logger.info("Tiempo medio por consulta: %.2f s", transcurrido / max(1, len(consultas)))
    logger.info(
        "Consultas que necesitaron ampliar k: %s",
        ", ".join(ampliadas) if ampliadas else "ninguna",
    )
    if invalidas:
        logger.warning(
            "Consultas descartadas por no cumplir el esquema: %s", ", ".join(invalidas)
        )
    logger.info("Escrito %s", args.salida)

    return 0 if len(resultados) == len(consultas) else 1


if __name__ == "__main__":
    raise SystemExit(main())
