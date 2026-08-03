"""Pila de encabezados activos, compartida por los parsers con jerarquia.

La invariante del proyecto: `seccion_path` es la ruta HASTA el bloque y nunca
incluye su propia identidad, tampoco cuando el bloque es un heading. El chunker
reconstruye el breadcrumb completo con
`seccion_path + ([texto] if tipo == "heading" else [])`.
"""

from __future__ import annotations

# (nivel del encabezado, texto del encabezado)
Pila = list[tuple[int, str]]


def rutas(pila: Pila) -> list[str]:
    """Textos de los encabezados activos, de mas externo a mas interno."""
    return [texto for _, texto in pila]


def empujar_seccion(pila: Pila, nivel: int, texto: str) -> list[str]:
    """Cierra los niveles >= nivel, devuelve los ancestros y apila el nuevo.

    Los saltos de nivel (h1 -> h3) se resuelven solos. Un encabezado sin texto
    cierra sus niveles pero no se apila, para no meter cadenas vacias en las
    rutas de sus descendientes.
    """
    while pila and pila[-1][0] >= nivel:
        pila.pop()
    ancestros = rutas(pila)
    if texto:
        pila.append((nivel, texto))
    return ancestros
