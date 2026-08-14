"""Construye la base vectorial completa a partir del corpus de documentos.

Flujo:

    documentos -> parseo/limpieza -> chunks -> embeddings -> FAISS + metadata

La recuperación y la generación de ``resultados.jsonl`` se ejecutan después
con ``generador.py``.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import torch
from retrieval.encoder import obtener_config
from lib.chunker.fragmentador import fragmentar_corpus
from lib.encoder import enc
from lib.parser.main import procesar_todo
from sentence_transformers import SentenceTransformer

logger = logging.getLogger("indexador")


class EncoderDePasajes:
    """Adapta el prefijo de pasaje requerido por algunos encoders."""

    def __init__(self, modelo: SentenceTransformer, prefijo: str) -> None:
        self.modelo = modelo
        self.prefijo = prefijo

    def encode(self, textos: list[str]):
        return self.modelo.encode([self.prefijo + texto for texto in textos])


def persistir_fallos_indexacion(fallos: list, ruta: Path) -> None:
    """Guarda los chunks que no pudieron convertirse en embedding."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8", newline="\n") as archivo:
        for chunk in fallos:
            archivo.write(json.dumps({
                "id_": chunk.id_,
                "doc_id": chunk.doc_id,
                "fuente": chunk.fuente,
                "excepcion": "fallo al generar el embedding",
            }, ensure_ascii=False, separators=(",", ":")) + "\n")


def construir_base(
    corpus: Path,
    destino: Path,
    errores_parseo: Path,
    errores_indexacion: Path,
    encoder_nombre: str,
    palabras: int,
    solapamiento: int,
    batch_size: int,
) -> tuple[int, int]:
    """Ejecuta todas las etapas y devuelve (documentos, chunks)."""
    config = obtener_config(encoder_nombre)
    print(f"[main] iniciando parseo del corpus: {corpus}", flush=True)
    documentos, _errores = procesar_todo(corpus, errores_salida=errores_parseo)
    print(f"[main] parseo terminado: {len(documentos)} documentos válidos", flush=True)
    print("[main] fragmentando documentos...", flush=True)
    chunks = fragmentar_corpus(documentos, palabras, solapamiento)
    if not chunks:
        raise RuntimeError("El corpus no produjo ningún chunk indexable")

    logger.info("Documentos válidos: %d; chunks: %d", len(documentos), len(chunks))
    print(f"[main] chunking terminado: {len(chunks)} chunks", flush=True)
    logger.info("Cargando encoder %s (%s)", encoder_nombre, config.modelo)
    dispositivo = "cuda" if torch.cuda.is_available() else "cpu"
    if dispositivo == "cuda":
        nombre_gpu = torch.cuda.get_device_name(0)
        print(f"[main] usando GPU: {nombre_gpu}", flush=True)
    else:
        print("[main] CUDA no disponible; usando CPU", flush=True)
    print(f"[main] cargando encoder {encoder_nombre}: {config.modelo}", flush=True)
    modelo = EncoderDePasajes(
        SentenceTransformer(config.modelo, device=dispositivo), config.prefijo_pasaje
    )
    if dispositivo == "cuda":
        memoria = torch.cuda.memory_allocated() / 1024**3
        print(f"[main] modelo cargado en CUDA; VRAM asignada: {memoria:.2f} GB", flush=True)

    carpeta = destino / f"encoder_{encoder_nombre}"
    carpeta.mkdir(parents=True, exist_ok=True)
    fallos = enc.armar_indice(
        chunks,
        modelo,
        config.dim,
        batch_size,
        carpeta / "index.faiss",
        carpeta / "metadata.jsonl",
    )
    persistir_fallos_indexacion(fallos, errores_indexacion)
    logger.info("Índice escrito en %s; fallos de embedding: %d", carpeta, len(fallos))
    print(
        f"[main] índice terminado: {len(chunks) - len(fallos)} vectores escritos en {carpeta}",
        flush=True,
    )
    return len(documentos), len(chunks) - len(fallos)


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Construye la base vectorial del corpus.")
    parser.add_argument("--corpus", type=Path, default=Path("./docs"))
    parser.add_argument("--salida", type=Path, default=Path("./base_vectorial"))
    parser.add_argument("--errores-parseo", type=Path, default=Path("./errores_parseo.jsonl"))
    parser.add_argument("--errores-indexacion", type=Path, default=Path("./errores_indexacion.jsonl"))
    parser.add_argument("--encoder", choices=("bge-m3", "e5-large"), default="bge-m3")
    parser.add_argument("--palabras", type=int, default=200)
    parser.add_argument("--solapamiento", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=32)
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = construir_parser().parse_args(argv)
    construir_base(
        args.corpus, args.salida, args.errores_parseo, args.errores_indexacion,
        args.encoder, args.palabras, args.solapamiento, args.batch_size,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
