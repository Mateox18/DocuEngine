"""Carga de los indices FAISS y busqueda de vecinos mas cercanos.

El punto delicado de este archivo es COMO se empareja un vector con su texto.
`encoder/enc.py:96-109` inserta con `add_with_ids(chunk.id_)` sobre un
`IndexIDMap`, asi que `search()` devuelve el `id_` global del chunk y NO la fila
del `.jsonl`. Coinciden solo mientras ningun chunk falle al vectorizar; los que
fallan se descartan en `vectorizar()` (`enc.py:70-76`) y `guardar_metadata` no
los escribe, dejando huecos en la numeracion. Indexar por posicion funcionaria
en las pruebas y entregaria el texto equivocado en el corpus real.

Por eso aqui todo se resuelve por `id_`, y la carga se niega a continuar si el
`.jsonl` y el indice no describen exactamente el mismo conjunto de ids.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import faiss
import numpy as np

from retrieval.encoder import codificar_consulta, obtener_config
from retrieval.errores import IndiceInvalido

logger = logging.getLogger(__name__)

PREFIJO_DIR = "encoder_"
NOMBRE_INDICE = "index.faiss"
NOMBRE_METADATA = "metadata.jsonl"

# Cuantos vectores se muestrean para comprobar que el indice esta normalizado, y
# cuanto se les tolera desviarse de la norma unitaria. 32 son suficientes para
# detectar un indice construido sin normalizar, y el coste es despreciable.
MUESTRA_NORMAS = 32
TOLERANCIA_NORMA = 1e-3


def _aplanar(registro: dict[str, Any]) -> dict[str, Any]:
    """Sube al nivel raiz las claves anidadas bajo `metadata`.

    `Chunk.to_dict()` (`chunker/models.py:39-61`) anida fuente, chunk_id,
    posicion, seccion_path y demas dentro de `metadata`. Aplanarlo una vez al
    cargar evita que cada modulo aguas abajo tenga que recordar la anidacion.
    Las claves de nivel raiz se escriben al final para que ganen ante cualquier
    colision con `meta_extra`.
    """
    plano: dict[str, Any] = dict(registro.get("metadata", {}))
    plano["id_"] = registro["id_"]
    plano["doc_id"] = registro["doc_id"]
    plano["texto"] = registro["texto"]
    return plano


def _como_idmap(indice: faiss.Index) -> faiss.Index:
    """Devuelve el indice con su tipo concreto, para poder leer `id_map`."""
    if hasattr(indice, "id_map"):
        return indice
    concreto = faiss.downcast_index(indice)
    if not hasattr(concreto, "id_map"):
        raise IndiceInvalido(
            "El indice no es un IndexIDMap. La recuperacion empareja vectores "
            "con texto por el id_ del chunk, que solo existe si el indice se "
            "construyo con add_with_ids, como hace encoder/enc.py:80-109."
        )
    return concreto


class IndexStore:
    """Indices y metadata en memoria. Se instancia UNA vez por ejecucion."""

    def __init__(self, ruta_base: Path) -> None:
        self.ruta_base = Path(ruta_base)
        self._indices: dict[str, faiss.Index] = {}
        self._por_id: dict[str, dict[int, dict[str, Any]]] = {}
        self._pos_por_id: dict[str, dict[int, int]] = {}

        if not self.ruta_base.is_dir():
            raise FileNotFoundError(f"No existe la base vectorial: {self.ruta_base}")

        # sorted() y no iterdir() a secas: el orden de los encoders se propaga al
        # de la fusion, y el pliego exige que la ejecucion sea reproducible.
        directorios = sorted(
            d for d in self.ruta_base.iterdir()
            if d.is_dir() and d.name.startswith(PREFIJO_DIR)
        )
        if not directorios:
            raise FileNotFoundError(
                f"No hay ninguna carpeta {PREFIJO_DIR}<nombre>/ en {self.ruta_base}"
            )

        for directorio in directorios:
            self._cargar_encoder(directorio.name[len(PREFIJO_DIR):], directorio)

        self.encoders: list[str] = sorted(self._indices)
        logger.info("Base vectorial cargada. Encoders: %s", ", ".join(self.encoders))

    # ------------------------------------------------------------------ carga

    def _cargar_encoder(self, nombre: str, directorio: Path) -> None:
        """Carga un `encoder_<nombre>/` y valida que indice y metadata cuadren."""
        # Falla ya si el encoder no esta configurado: sin su entrada en
        # CONFIG_ENCODERS no hay forma de codificar consultas contra el, y
        # descubrirlo en la primera busqueda seria mas confuso.
        config = obtener_config(nombre)

        ruta_indice = directorio / NOMBRE_INDICE
        ruta_metadata = directorio / NOMBRE_METADATA
        for ruta in (ruta_indice, ruta_metadata):
            if not ruta.is_file():
                raise FileNotFoundError(f"Falta {ruta}")

        indice = _como_idmap(faiss.read_index(str(ruta_indice)))

        # Un indice de otra dimension es un indice de otro modelo. No se puede
        # detectar el caso contrario -misma dimension, modelo distinto-, pero este
        # si, y es gratis.
        if indice.d != config.dim:
            raise IndiceInvalido(
                f"Encoder {nombre!r}: el indice tiene dimension {indice.d} y "
                f"{config.modelo} produce vectores de {config.dim}. El indice se "
                f"construyo con otro modelo."
            )

        registros: list[dict[str, Any]] = []
        with open(ruta_metadata, encoding="utf-8") as archivo:
            for numero, linea in enumerate(archivo, start=1):
                linea = linea.strip()
                if not linea:
                    continue
                try:
                    registros.append(_aplanar(json.loads(linea)))
                except (json.JSONDecodeError, KeyError) as exc:
                    raise IndiceInvalido(
                        f"{ruta_metadata}, linea {numero}: {exc}"
                    ) from exc

        ids_por_posicion = faiss.vector_to_array(indice.id_map)
        pos_por_id = {int(id_): pos for pos, id_ in enumerate(ids_por_posicion)}
        por_id = {int(r["id_"]): r for r in registros}

        self._validar(nombre, indice, registros, por_id, pos_por_id)
        self._avisar_de_normas(nombre, indice, pos_por_id)

        self._indices[nombre] = indice
        self._por_id[nombre] = por_id
        self._pos_por_id[nombre] = pos_por_id
        logger.info("Encoder %r: %d vectores", nombre, indice.ntotal)

    def _validar(
        self,
        nombre: str,
        indice: faiss.Index,
        registros: list[dict[str, Any]],
        por_id: dict[int, dict[str, Any]],
        pos_por_id: dict[int, int],
    ) -> None:
        """Comprueba que indice y metadata describan el mismo conjunto de chunks.

        Las tres comprobaciones no son redundantes. Comparar solo longitudes deja
        pasar el caso realmente peligroso: un chunk que fallo al vectorizar hace
        que los ids dejen de ser contiguos sin cambiar ningun total, y a partir de
        ahi cualquier lookup posicional devuelve el texto de otro chunk.
        """
        if len(por_id) != len(registros):
            raise IndiceInvalido(
                f"Encoder {nombre!r}: {NOMBRE_METADATA} tiene ids duplicados "
                f"({len(registros)} lineas, {len(por_id)} ids distintos)."
            )
        if len(registros) != indice.ntotal:
            raise IndiceInvalido(
                f"Encoder {nombre!r}: {len(registros)} lineas de metadata frente "
                f"a {indice.ntotal} vectores en el indice. Se construyeron por "
                f"separado o uno de los dos esta a medias."
            )
        if por_id.keys() != pos_por_id.keys():
            solo_metadata = sorted(por_id.keys() - pos_por_id.keys())[:5]
            solo_indice = sorted(pos_por_id.keys() - por_id.keys())[:5]
            raise IndiceInvalido(
                f"Encoder {nombre!r}: los ids de la metadata y los del indice no "
                f"coinciden. Solo en metadata: {solo_metadata}. Solo en indice: "
                f"{solo_indice}. Hay que reconstruir la base vectorial."
            )

    def _avisar_de_normas(
        self,
        nombre: str,
        indice: faiss.Index,
        pos_por_id: dict[int, int],
    ) -> None:
        """Registra un aviso si los vectores del indice no son unitarios.

        No corrige nada ni bloquea la carga. El proyecto asume que el modelo
        normaliza por su cuenta (un modulo `Normalize` al final de su
        `modules.json`), porque `encoder/enc.py:66` llama a `model.encode` con los
        parametros por defecto. Esto convierte esa suposicion en algo falsable:
        si el indice se construyo con un modelo que no normaliza, el
        `IndexFlatIP` mide producto interno y no coseno, los scores dejan de estar
        acotados en [-1, 1] y la fusion y el max pooling heredan la distorsion sin
        que nada mas lo delate.
        """
        if indice.ntotal == 0:
            return

        paso = max(1, indice.ntotal // MUESTRA_NORMAS)
        posiciones = list(range(0, indice.ntotal, paso))[:MUESTRA_NORMAS]

        try:
            interno = faiss.downcast_index(indice.index)
            normas = [
                float(np.linalg.norm(interno.reconstruct(pos))) for pos in posiciones
            ]
        except Exception as exc:  # noqa: BLE001 - es diagnostico, no pipeline
            logger.info(
                "Encoder %r: no se pudieron leer vectores para comprobar sus "
                "normas (%s). Se continua sin la comprobacion.", nombre, exc,
            )
            return

        desviacion = max(abs(norma - 1.0) for norma in normas)
        if desviacion > TOLERANCIA_NORMA:
            logger.warning(
                "Encoder %r: los vectores del indice NO son unitarios (desviacion "
                "maxima %.4f sobre %d muestras). El indice mide producto interno, "
                "no coseno: los documentos de norma mayor ganaran posiciones sin "
                "ser mas relevantes. Reconstruye el indice normalizando.",
                nombre, desviacion, len(normas),
            )
        else:
            logger.debug(
                "Encoder %r: normas unitarias confirmadas sobre %d muestras.",
                nombre, len(normas),
            )

    # --------------------------------------------------------------- busqueda

    def buscar(
        self, query_vector: np.ndarray, encoder_nombre: str, k: int
    ) -> list[dict[str, Any]]:
        """Devuelve los k chunks mas cercanos, de mayor a menor score."""
        if encoder_nombre not in self._indices:
            raise KeyError(
                f"Encoder {encoder_nombre!r} no cargado. Disponibles: "
                f"{', '.join(self.encoders)}"
            )

        indice = self._indices[encoder_nombre]
        por_id = self._por_id[encoder_nombre]
        consulta = np.ascontiguousarray(
            np.asarray(query_vector).reshape(1, -1), dtype=np.float32
        )
        distancias, ids = indice.search(consulta, k)

        resultados: list[dict[str, Any]] = []
        for score, id_ in zip(distancias[0], ids[0]):
            id_ = int(id_)
            # FAISS rellena con -1 cuando el indice tiene menos de k vectores.
            if id_ == -1:
                continue
            registro = dict(por_id[id_])
            registro["score"] = float(score)
            resultados.append(registro)

        # El desempate explicito por id_ es lo que hace el orden reproducible:
        # ante dos scores identicos, el orden en que los devuelve FAISS no forma
        # parte de su contrato.
        resultados.sort(key=lambda r: (-r["score"], r["id_"]))
        return resultados

    def buscar_todos_los_encoders(
        self, query_texto: str, k: int
    ) -> dict[str, list[dict[str, Any]]]:
        """Codifica y busca la consulta en cada encoder configurado."""
        return {
            nombre: self.buscar(codificar_consulta(query_texto, nombre), nombre, k)
            for nombre in self.encoders
        }
