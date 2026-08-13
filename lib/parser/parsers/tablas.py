"""Convencion comun de linealizacion de filas de tabla.

Una fila se convierte en "columna: valor | columna: valor". La usan markdown,
HTML y los formatos tabulares: tener una sola implementacion es lo que garantiza
que la misma tabla produzca el mismo texto venga de donde venga.
"""

from __future__ import annotations

from collections.abc import Sequence


def nombrar_cabeceras(celdas: Sequence[str], *, unicos: bool = False) -> list[str]:
    """Nombra las columnas: una cabecera vacia pasa a ser "colN" (1-based).

    Con `unicos=True` ademas desambigua las repetidas ("2020", "2020 (2)").
    Markdown NO desambigua (unicos=False, comportamiento historico); los
    formatos tabulares si, porque los datasets reales traen cabeceras repetidas
    y "x: a | x: b" es ambiguo.
    """
    nombres = [celda if celda else f"col{n + 1}" for n, celda in enumerate(celdas)]
    if not unicos:
        return nombres

    vistos: dict[str, int] = {}
    salida: list[str] = []
    for nombre in nombres:
        vistos[nombre] = vistos.get(nombre, 0) + 1
        salida.append(nombre if vistos[nombre] == 1 else f"{nombre} ({vistos[nombre]})")
    return salida


def linealizar_fila(cabeceras: Sequence[str], celdas: Sequence[str]) -> str:
    """Convierte una fila en "columna: valor | columna: valor".

    Omite las celdas vacias. Las celdas que faltan respecto a las cabeceras
    simplemente no aparecen; las sobrantes reciben la clave "col{n+1}".
    Devuelve cadena vacia si no queda ningun par.
    """
    pares = []
    for n, celda in enumerate(celdas):
        if not celda:
            continue
        cabecera = cabeceras[n] if n < len(cabeceras) else f"col{n + 1}"
        pares.append(f"{cabecera}: {celda}")
    return " | ".join(pares)
