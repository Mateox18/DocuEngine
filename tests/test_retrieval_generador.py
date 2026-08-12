"""Orquestacion completa y reproducibilidad de resultados.jsonl."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import generador
from conftest import chunk_falso, vector_unitario
from retrieval.schema import validar_resultado

NUM_CHUNKS = 30
NUM_DOCS = 5


def codificador_falso(texto: str, encoder_nombre: str):
    """Sustituye al modelo real: nada de bajar varios GB para probar el flujo.

    Deriva el vector de un sha256 del texto y no de hash(), que Python aleatoriza
    entre procesos: con hash() el test de reproducibilidad pasaria dentro de una
    misma ejecucion y fallaria entre dos, que es justo lo que debe detectar.
    """
    semilla = int(hashlib.sha256(texto.encode("utf-8")).hexdigest()[:8], 16)
    return vector_unitario(semilla % 100_000)


@pytest.fixture
def entorno(tmp_path: Path, crear_base_vectorial, monkeypatch) -> tuple[Path, Path]:
    """Base vectorial sintetica y archivo con las 50 consultas del pliego."""
    registros = [
        chunk_falso(id_=i, doc_id=f"doc-{i % NUM_DOCS}", posicion=i // NUM_DOCS)
        for i in range(NUM_CHUNKS)
    ]
    base = crear_base_vectorial(registros)

    monkeypatch.setattr(
        "retrieval.index_store.codificar_consulta", codificador_falso
    )

    consultas = tmp_path / "consultas.jsonl"
    with open(consultas, "w", encoding="utf-8", newline="\n") as archivo:
        for numero in range(1, 51):
            archivo.write(
                json.dumps(
                    {"query_id": f"q{numero:03d}", "text": f"consulta numero {numero}"},
                    ensure_ascii=False,
                ) + "\n"
            )

    return base, consultas


def ejecutar(base: Path, consultas: Path, salida: Path) -> int:
    return generador.main([
        "--consultas", str(consultas),
        "--base", str(base),
        "--salida", str(salida),
        "--k_busqueda", "20",
    ])


def test_dos_ejecuciones_producen_el_mismo_archivo(entorno, tmp_path):
    """Criterio de aceptacion literal del pliego: si no se reproduce, se excluye."""
    base, consultas = entorno
    primera = tmp_path / "primera.jsonl"
    segunda = tmp_path / "segunda.jsonl"

    assert ejecutar(base, consultas, primera) == 0
    assert ejecutar(base, consultas, segunda) == 0

    assert primera.read_bytes() == segunda.read_bytes()


def test_escribe_cincuenta_lineas_en_orden_y_sin_linea_en_blanco(entorno, tmp_path):
    base, consultas = entorno
    salida = tmp_path / "resultados.jsonl"

    assert ejecutar(base, consultas, salida) == 0

    contenido = salida.read_bytes().decode("utf-8")
    lineas = contenido.split("\n")
    assert lineas[-1] == ""          # termina en \n, sin linea vacia adicional

    objetos = [json.loads(linea) for linea in lineas[:-1]]
    assert len(objetos) == 50
    assert [o["query_id"] for o in objetos] == [f"q{i:03d}" for i in range(1, 51)]


def test_todas_las_lineas_cumplen_el_esquema(entorno, tmp_path):
    base, consultas = entorno
    salida = tmp_path / "resultados.jsonl"
    ejecutar(base, consultas, salida)

    for linea in salida.read_text(encoding="utf-8").splitlines():
        valido, errores = validar_resultado(json.loads(linea))
        assert valido, errores


def test_no_traduce_los_saltos_de_linea_de_windows(entorno, tmp_path):
    """Sin newline="\\n" explicito el archivo saldria con \\r\\n y no coincidiria."""
    base, consultas = entorno
    salida = tmp_path / "resultados.jsonl"
    ejecutar(base, consultas, salida)

    assert b"\r\n" not in salida.read_bytes()


def test_no_escapa_las_tildes_ni_las_enes(entorno, tmp_path, crear_base_vectorial):
    base, consultas = entorno
    salida = tmp_path / "resultados.jsonl"
    ejecutar(base, consultas, salida)

    # ensure_ascii=False: un ñ en el archivo entregado seria valido pero
    # ilegible, y el pliego pide el texto tal cual.
    assert "\\u" not in salida.read_text(encoding="utf-8")


def test_falla_si_el_archivo_no_trae_exactamente_cincuenta_consultas(
    entorno, tmp_path
):
    base, _ = entorno
    cortas = tmp_path / "cortas.jsonl"
    with open(cortas, "w", encoding="utf-8", newline="\n") as archivo:
        for numero in range(1, 4):
            archivo.write(
                json.dumps({"query_id": f"q{numero:03d}", "text": "x"}) + "\n"
            )

    with pytest.raises(ValueError, match="exactamente 50"):
        ejecutar(base, cortas, tmp_path / "salida.jsonl")


def test_falla_si_una_consulta_esta_repetida(entorno, tmp_path):
    base, _ = entorno
    repetidas = tmp_path / "repetidas.jsonl"
    with open(repetidas, "w", encoding="utf-8", newline="\n") as archivo:
        for _ in range(2):
            archivo.write(json.dumps({"query_id": "q001", "text": "x"}) + "\n")

    with pytest.raises(ValueError, match="repetido"):
        ejecutar(base, repetidas, tmp_path / "salida.jsonl")
