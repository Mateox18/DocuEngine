import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"   # tolera las dos copias de OpenMP
import torch
torch.set_num_threads(1)                      # sin esto, encode() de un batch revienta el proceso
import numpy as np
from lib.chunker.models import Chunk
import faiss
faiss.omp_set_num_threads(1)                  # sin esto, search() revienta despues de usar torch
import json
from pathlib import Path

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
    # El orden de los chunks no afecta FAISS porque cada vector se inserta con
    # su id explícito. Agrupar longitudes parecidas reduce el padding del
    # tokenizer/modelo y evita que un chunk largo ralentice todo el batch.
    ordenados = sorted(
        chunks,
        key=lambda chunk: (chunk.num_tokens, chunk.id_),
    )
    batches = []
    for num in range(0, len(ordenados), salto):
        batches.append(ordenados[num:num+salto])
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


def _guardar_checkpoint(
    idmap, ruta_indice: Path, ruta_estado: Path, siguiente_batch: int,
    metadata_lines: int, fallos: list[Chunk],
) -> None:
    """Persiste un punto de reanudación usando reemplazos atómicos."""
    indice_temporal = ruta_indice.with_suffix(ruta_indice.suffix + ".tmp")
    estado_temporal = ruta_estado.with_suffix(ruta_estado.suffix + ".tmp")
    faiss.write_index(idmap, str(indice_temporal))
    os.replace(indice_temporal, ruta_indice)
    estado = {
        "siguiente_batch": siguiente_batch,
        "metadata_lines": metadata_lines,
        "fallos_ids": [chunk.id_ for chunk in fallos],
    }
    estado_temporal.write_text(
        json.dumps(estado, ensure_ascii=False), encoding="utf-8"
    )
    os.replace(estado_temporal, ruta_estado)


def _truncar_lineas(ruta: Path, lineas: int) -> None:
    """Descarta metadata escrita después del último checkpoint confirmado."""
    contenido = ruta.read_text(encoding="utf-8").splitlines(keepends=True)
    ruta.write_text("".join(contenido[:lineas]), encoding="utf-8", newline="\n")


def armar_indice(
    chunks, model, dim, salto, ruta_indice, ruta_metadata,
    reanudar: bool = True, checkpoint_cada: int = 100,
):
    """Construye el indice completo y lo persiste. Devuelve los chunks fallidos.

    La insercion en FAISS y la escritura de la metadata ocurren en la MISMA
    vuelta del bucle, gobernadas por la misma condicion de exito. Hacerlo en
    dos pasadas separadas abre la puerta a que una incluya un chunk que la otra
    omitio, y ahi el indice devolveria el texto equivocado sin lanzar ningun
    error: fallaria en silencio.
    """

    malos_all = []
    ruta_indice = Path(ruta_indice)
    ruta_metadata = Path(ruta_metadata)
    ruta_indice.parent.mkdir(parents=True, exist_ok=True)
    ruta_estado = ruta_indice.with_suffix(".checkpoint.json")

    validar_ids(chunks)

    batches = generar_batches(chunks, salto)
    inicio_batch = 0
    metadata_lines = 0

    if reanudar and ruta_estado.exists() and ruta_indice.exists() and ruta_metadata.exists():
        estado = json.loads(ruta_estado.read_text(encoding="utf-8"))
        inicio_batch = int(estado["siguiente_batch"])
        metadata_lines = int(estado["metadata_lines"])
        if not 0 <= inicio_batch <= len(batches):
            raise ValueError("Checkpoint fuera del rango de batches actual")
        idmap = faiss.read_index(str(ruta_indice))
        _truncar_lineas(ruta_metadata, metadata_lines)
        fallos_previos = {int(id_) for id_ in estado.get("fallos_ids", [])}
        malos_all = [chunk for chunk in chunks if chunk.id_ in fallos_previos]
        print(
            f"[encoder] reanudando en batch {inicio_batch + 1}/{len(batches)}; "
            f"{idmap.ntotal} vectores ya persistidos", flush=True,
        )
    else:
        idmap = crear_faiss(dim)

    modo_metadata = "a" if inicio_batch else "w"
    with open(ruta_metadata, modo_metadata, encoding="utf-8") as archivo:
        total_batches = len(batches)
        for numero_batch, batch in enumerate(
            batches[inicio_batch:], start=inicio_batch + 1
        ):
            print(
                f"[encoder] batch {numero_batch}/{total_batches}: "
                f"{len(batch)} chunks, generando embeddings...",
                flush=True,
            )
            buenos, malos = vectorizar(batch, model)
            indexar(idmap, buenos)
            guardar_metadata(archivo, buenos)
            archivo.flush()
            metadata_lines += len(buenos)
            malos_all.extend(malos)
            print(
                f"[encoder] batch {numero_batch}/{total_batches} terminado: "
                f"{len(buenos)} OK, {len(malos)} fallidos",
                flush=True,
            )
            if checkpoint_cada > 0 and (
                numero_batch % checkpoint_cada == 0 or numero_batch == total_batches
            ):
                _guardar_checkpoint(
                    idmap, ruta_indice, ruta_estado, numero_batch,
                    metadata_lines, malos_all,
                )

    # El último batch ya escribe checkpoint cuando checkpoint_cada > 0.
    # Evitamos serializar de nuevo un índice potencialmente grande.
    if checkpoint_cada <= 0 or not ruta_indice.exists():
        faiss.write_index(idmap, str(ruta_indice))
    if ruta_estado.exists():
        ruta_estado.unlink()

    return malos_all
