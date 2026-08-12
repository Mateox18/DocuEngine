"""Excepciones propias de la capa de recuperacion."""

from __future__ import annotations


class PoolInsuficiente(Exception):
    """El pool de candidatos no da para llenar la salida exigida.

    La lanzan `aggregation` y `fragment_builder`, que no pueden resolverla por su
    cuenta porque no tienen acceso al indice. La captura `generador.py`, que si
    puede ampliar k y reintentar la busqueda.
    """


class IndiceInvalido(Exception):
    """El indice y su metadata no describen el mismo conjunto de chunks.

    Es preferible a devolver resultados: un indice desalineado no falla, solo
    entrega el texto equivocado para cada vector, y nada lo delata aguas abajo.
    """
