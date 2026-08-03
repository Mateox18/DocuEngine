"""Fixtures compartidas de la suite."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

Escribir = Callable[..., Path]
EscribirBytes = Callable[[str, bytes], Path]
LibroExcel = Callable[..., Path]
PaginaHtml = Callable[..., str]

# Prosa suficiente para que una pagina supere el umbral de 200 caracteres
# utiles de HtmlParser; sin ella trafilatura la descarta y el test mediria otra
# cosa de la que cree.
RELLENO = (
    "La seguridad espacial en orbita baja se ha convertido en una preocupacion "
    "central para las agencias de la region, que vigilan la densidad creciente "
    "de objetos catalogados y la probabilidad de colision entre satelites "
    "activos y fragmentos de misiones anteriores ya desaparecidas."
)


@pytest.fixture
def escribir(tmp_path: Path) -> Escribir:
    """Crea un archivo con contenido, encoding y salto de linea exactos."""

    def _escribir(
        nombre: str,
        contenido: str,
        *,
        encoding: str = "utf-8",
        salto: str = "\n",
    ) -> Path:
        destino = tmp_path / nombre
        # write_bytes y NO write_text: en Windows el modo texto traduce
        # \n -> \r\n y los tests de CRLF y de encoding darian falsos verdes.
        destino.write_bytes(contenido.replace("\n", salto).encode(encoding))
        return destino

    return _escribir


@pytest.fixture
def escribir_bytes(tmp_path: Path) -> EscribirBytes:
    """Crea un archivo binario tal cual (xlsx, xls falso, bytes invalidos)."""

    def _escribir_bytes(nombre: str, datos: bytes) -> Path:
        destino = tmp_path / nombre
        destino.write_bytes(datos)
        return destino

    return _escribir_bytes


@pytest.fixture
def libro_excel(tmp_path: Path) -> LibroExcel:
    """Genera un .xlsx real con openpyxl.

        ruta = libro_excel("datos.xlsx", {
            "Data 2.1": [["Titulo del dataset"], [], ["pais", "anio"], ["CO", 2023]],
            "Notas":    [["fuente: AI Index"]],
        })

    Los valores se escriben con su tipo Python nativo (int, float, datetime,
    None) para poder testear la serializacion canonica de celdas.
    """

    def _libro_excel(nombre: str, hojas: Mapping[str, Sequence[Sequence[Any]]]) -> Path:
        import openpyxl

        libro = openpyxl.Workbook()
        libro.remove(libro.active)
        for titulo, filas in hojas.items():
            hoja = libro.create_sheet(titulo)
            for fila in filas:
                hoja.append(list(fila))
        destino = tmp_path / nombre
        libro.save(destino)
        return destino

    return _libro_excel


@pytest.fixture
def pagina_html() -> PaginaHtml:
    """Arma un HTML completo con head configurable y boilerplate con centinelas."""

    def _pagina_html(
        *,
        cuerpo: str | None = None,
        head: str = "",
        titulo: str = "Titulo del articulo",
        lang: str = "es",
    ) -> str:
        contenido = cuerpo if cuerpo is not None else f"<p>{RELLENO}</p>"
        return f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
  <meta charset="utf-8">
  <title>{titulo}</title>
  {head}
  <script>var rastreador = "CENTINELA_SCRIPT";</script>
</head>
<body>
  <nav><a href="/">CENTINELA_NAV inicio</a><a href="/x">seccion</a></nav>
  <article>{contenido}</article>
  <footer>CENTINELA_FOOTER derechos reservados</footer>
</body>
</html>"""

    return _pagina_html
