import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"   # tolera las dos copias de OpenMP
import torch
torch.set_num_threads(1)                      # sin esto, encode() de un batch revienta el proceso
import numpy as np
from lib.chunker.models import Chunk
import faiss
faiss.omp_set_num_threads(1)                  # sin esto, search() revienta despues de usar torch
import json

def validar_ids(chunks: list[Chunk]) -> None:
    """Falla si hay id_ repetidos en el lote.

    Un id duplicado no se puede "saltar y seguir": no habria forma de saber
    cual de los dos chunks le corresponde a ese vector, y el indice quedaria
    apuntando al texto equivocado sin que nada lo delate. A diferencia de un
    chunk que falla al vectorizar (aislado y esperable), esto indica un bug
    aguas arriba, asi que corta el proceso para que se arregle en el origen.
    """
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
    """Parte la lista de chunks en grupos de `salto` elementos.

    Se hace a mano en vez de delegarlo al batch_size de sentence-transformers
    porque vectorizar() necesita controlar cada grupo por separado para poder
    reintentarlo uno a uno cuando falla.
    """
    batches = []
    for num in range(0, len(chunks), salto):
        batches.append(chunks[num:num+salto])
    return batches

def vectorizar (batch: list[Chunk], model):
    """Vectoriza un batch y devuelve (exitosos, fallidos).

    Dos niveles: primero se intenta el batch completo, que es lo rapido porque
    aprovecha el paralelismo del hardware. Si ese intento falla, un solo chunk
    conflictivo se habria llevado por delante a todos sus companeros, asi que
    se reintenta uno por uno para aislar al culpable y rescatar al resto.

    Los exitosos salen como pares (chunk, vector); los fallidos, como el chunk
    solo. Ningun fallo detiene el lote.
    """

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
    """Crea el indice vacio de dimension `dim`.

    IndexFlatIP es el motor (busqueda exacta por producto interno) e
    IndexIDMap lo envuelve. Sin el envoltorio, FAISS numera los vectores por
    orden de insercion, y si un chunk falla al vectorizar todos los siguientes
    se corren de posicion y el indice queda desalineado con metadata.jsonl.
    Con IndexIDMap cada vector lleva su propio id, y un chunk que falla solo
    deja un hueco inofensivo en la numeracion.
    """

    flatip = faiss.IndexFlatIP(dim)
    idmap = faiss.IndexIDMap(flatip)

    return idmap

def indexar (idmap, buenos):
    """Inserta en el indice los pares (chunk, vector) de un batch."""

    if not buenos:
        return

    ids = []
    vectors = []

    for chunk, vector in buenos:
        ids.append(chunk.id_)
        vectors.append(vector)

    vectors_np = np.array(vectors, dtype=np.float32)
    # IndexFlatIP equivale a similitud coseno solo con vectores unitarios.
    faiss.normalize_L2(vectors_np)
    ids_np = np.array(ids, dtype=np.int64)

    idmap.add_with_ids(vectors_np, ids_np)

def guardar_metadata (archivo, buenos):
    """Escribe una linea de metadata.jsonl por cada chunk del batch.

    Recibe el archivo ya abierto: se abre una sola vez en armar_indice, no una
    vez por batch. Chunk.to_dict() excluye el embedding a proposito, para no
    duplicar en texto plano lo que FAISS ya guarda en binario.
    """
    for chunk, vector in buenos:
        archivo.write(json.dumps(chunk.to_dict(),
            ensure_ascii=False) + "\n")


def armar_indice (chunks, model, dim, salto, ruta_indice, ruta_metadata):
    """Construye el indice completo y lo persiste. Devuelve los chunks fallidos.

    La insercion en FAISS y la escritura de la metadata ocurren en la MISMA
    vuelta del bucle, gobernadas por la misma condicion de exito. Hacerlo en
    dos pasadas separadas abre la puerta a que una incluya un chunk que la otra
    omitio, y ahi el indice devolveria el texto equivocado sin lanzar ningun
    error: fallaria en silencio.
    """

    malos_all = []

    validar_ids(chunks)

    idmap = crear_faiss(dim)

    batches = generar_batches(chunks, salto)

    with open(ruta_metadata, "w", encoding="utf-8") as archivo:
        total_batches = len(batches)
        for numero_batch, batch in enumerate(batches, start=1):
            print(
                f"[encoder] batch {numero_batch}/{total_batches}: "
                f"{len(batch)} chunks, generando embeddings...",
                flush=True,
            )
            buenos, malos = vectorizar(batch, model)
            indexar(idmap, buenos)
            guardar_metadata(archivo, buenos)
            malos_all.extend(malos)
            print(
                f"[encoder] batch {numero_batch}/{total_batches} terminado: "
                f"{len(buenos)} OK, {len(malos)} fallidos",
                flush=True,
            )

    faiss.write_index(idmap, ruta_indice)

    return malos_all
