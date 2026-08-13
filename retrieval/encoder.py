"""Codificacion de la consulta en el mismo espacio vectorial que el indice.

La regla que gobierna este archivo: la fuente de verdad del espacio vectorial es
el flujo de INDEXACION, no este modulo. Una consulta codificada con otro modelo,
otro pooling u otro prefijo cae en un espacio distinto, y FAISS devolvera
vecinos sin quejarse de nada. Por eso `codificar_consulta` espeja la llamada de
`lib/encoder/enc.py:66` en vez de inventar la suya.

No reformula, no expande y no reescribe la consulta: la restriccion 8.3 del
pliego prohibe cualquier modelo generativo en la recuperacion.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class ConfigEncoder:
    """Lo que hay que saber de un encoder para reproducir su espacio vectorial."""

    modelo: str
    dim: int
    prefijo_consulta: str
    prefijo_pasaje: str


# Los prefijos NO son un detalle de estilo: forman parte de como se entreno cada
# modelo, y usar el equivocado degrada la recuperacion en silencio.
#
#   bge-m3    no lleva prefijo de instruccion para recuperacion densa. Los
#             documentos se indexaron tal cual, asi que la consulta tampoco.
#
#   e5-large  la convencion de la familia e5 es obligatoria, no opcional: los
#             documentos se indexan con "passage: " y las consultas se codifican
#             con "query: ". Sin ella el modelo trabaja fuera de distribucion.
#
# `prefijo_pasaje` no lo usa este modulo. Esta aqui para dejar CONSTANCIA de con
# que se indexo: la recuperacion no puede imponer el prefijo de los documentos,
# solo documentarlo para que quien construya el indice use el mismo.
CONFIG_ENCODERS: dict[str, ConfigEncoder] = {
    "bge-m3": ConfigEncoder(
        modelo="BAAI/bge-m3",
        dim=1024,
        prefijo_consulta="",
        prefijo_pasaje="",
    ),
    "e5-large": ConfigEncoder(
        modelo="intfloat/multilingual-e5-large",
        dim=1024,
        prefijo_consulta="query: ",
        prefijo_pasaje="passage: ",
    ),
}

# Cache a nivel de modulo: cargar un SentenceTransformer cuesta segundos y varios
# GB de RAM. Con 50 consultas y dos encoders, recargarlo por llamada multiplicaria
# por 100 el coste de la ejecucion entera.
_MODELOS: dict[str, SentenceTransformer] = {}


def obtener_config(encoder_nombre: str) -> ConfigEncoder:
    """Devuelve la configuracion del encoder o falla nombrando los validos."""
    if encoder_nombre not in CONFIG_ENCODERS:
        validos = ", ".join(sorted(CONFIG_ENCODERS))
        raise KeyError(
            f"Encoder desconocido: {encoder_nombre!r}. Configurados: {validos}"
        )
    return CONFIG_ENCODERS[encoder_nombre]


def cargar_modelo(encoder_nombre: str) -> SentenceTransformer:
    """Carga el modelo del encoder una sola vez por proceso."""
    if encoder_nombre not in _MODELOS:
        config = obtener_config(encoder_nombre)
        logger.info("Cargando %s para el encoder %r", config.modelo, encoder_nombre)
        _MODELOS[encoder_nombre] = SentenceTransformer(config.modelo)
    return _MODELOS[encoder_nombre]


def codificar_consulta(texto: str, encoder_nombre: str) -> np.ndarray:
    """Codifica la consulta y devuelve su vector unitario de forma (dim,).

    La normalizacion es idempotente cuando el modelo ya la aplica en su propia
    tubera de modulos (un `Normalize` al final de `modules.json`), que es la
    suposicion de trabajo del proyecto. Se hace igualmente porque en ese caso no
    cuesta nada, y porque los indices son `IndexFlatIP`: el producto interno solo
    equivale al coseno sobre vectores unitarios.
    """
    config = obtener_config(encoder_nombre)
    modelo = cargar_modelo(encoder_nombre)

    # Misma llamada que lib/encoder/enc.py:66, con una lista de un elemento: mismo
    # pooling, mismos parametros por defecto, mismo espacio de salida.
    vectores = modelo.encode([config.prefijo_consulta + texto])

    # ascontiguousarray y no asarray: faiss.normalize_L2 escribe sobre el buffer
    # y exige float32 contiguo en memoria.
    vectores = np.ascontiguousarray(vectores, dtype=np.float32)

    if vectores.shape != (1, config.dim):
        raise ValueError(
            f"El encoder {encoder_nombre!r} devolvio un vector de forma "
            f"{vectores.shape}; se esperaba (1, {config.dim}). Revisa que "
            f"CONFIG_ENCODERS declare la dimension real de {config.modelo}."
        )

    faiss.normalize_L2(vectores)
    return vectores[0]
