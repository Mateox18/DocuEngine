"""Capa de recuperacion: consume la base vectorial y produce los resultados.

Este `__init__` no esta vacio a proposito. Fija los hilos de torch y de faiss
antes de que ningun submodulo los use, replicando el preambulo de
`encoder/enc.py:1-9`, cuyos comentarios documentan que sin esto el proceso
muere: `encode()` de un batch revienta con varios hilos de torch, y `search()`
revienta despues de haber usado torch si faiss no esta tambien fijado a uno.

Se REPLICA en vez de importar `encoder.enc`, que lo haria gratis, porque ese
modulo importa `chunker.models` y este ultimo hace `import chunk` en su linea 3:
un modulo eliminado de la stdlib en Python 3.13, asi que la cadena entera es
inimportable en esta maquina. Ver `retrieval-pendiente.md`, hecho 4.

El ORDEN de las tres lineas es lo que importa, no el hecho de que esten:
la variable de entorno antes de torch, y faiss despues de torch.
"""

import os

os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"   # tolera las dos copias de OpenMP

import torch

torch.set_num_threads(1)

import faiss

faiss.omp_set_num_threads(1)
