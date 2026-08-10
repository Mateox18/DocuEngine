import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
import torch
torch.set_num_threads(1)
import numpy as np
from sentence_transformers import SentenceTransformer
from chunker.models import Chunk
import faiss
faiss.omp_set_num_threads(1)
import json


"""
if torch.backends.mps.is_available():
    DEVICE = 'mps'
else:
    DEVICE = 'cpu'

print("Usando: " + DEVICE)

MODEL_NAME = "BAAI/bge-m3"

model = SentenceTransformer(MODEL_NAME, device=DEVICE)

print("Modelo cargado")
"""



def validar_ids(chunks: list[Chunk]) -> None:
    vistos = set()
    duplicados = []

    for chunk in chunks:
        if chunk.id_ in vistos:
            duplicados.append(chunk.id_)
        else:
            vistos.add(chunk.id_)

    if len(duplicados) > 0:
        raise ValueError(f"Se encontraron IDs duplicados: {duplicados}")

def generar_batches(chunks: list[Chunk], salto) -> list[list[Chunk]]:
    batches = []
    for num in range(0, len(chunks), salto):
        batches.append(chunks[num:num+salto])
    return batches

def vectorizar (batch: list[Chunk], model):

    textos = []
    buenos = []
    malos = []


    for chunk in batch:
        textos.append(chunk.texto)

    try:
        vectores = model.encode(textos)

        for chunk, vector in zip(batch, vectores):
            buenos.append((chunk, vector))
    except Exception:
        for chunk in batch:
            try:
                vector = model.encode([chunk.texto])[0]
                buenos.append((chunk, vector))
            except Exception:
                malos.append(chunk)

    return buenos, malos

def crear_faiss(dim: int):

    flatip = faiss.IndexFlatIP(dim)
    idmap = faiss.IndexIDMap(flatip)

    return idmap

def indexar (idmap, buenos):

    ids = []
    vectors = []

    for chunk, vector in buenos:
        ids.append(chunk.id_)
        vectors.append(vector)

    vectors_np = np.array(vectors, dtype=np.float32)
    ids_np = np.array(ids, dtype=np.int64)

    idmap.add_with_ids(vectors_np, ids_np)

def guardar_metadata (archivo, buenos):
    for chunk, vector in buenos:
        archivo.write(json.dumps(chunk.to_dict(),
            ensure_ascii=False) + "\n")


def armar_indice (chunks, model, dim, salto, ruta_indice, ruta_metadata):

    malos_all = []

    validar_ids(chunks)

    idmap = crear_faiss(dim)

    batches = generar_batches(chunks, salto)

    with open(ruta_metadata, "w", encoding="utf-8") as archivo:
        for batch in batches:
            buenos, malos = vectorizar(batch, model)
            indexar(idmap, buenos)
            guardar_metadata(archivo, buenos)
            malos_all.extend(malos)

    faiss.write_index(idmap, ruta_indice)

    return malos_all





