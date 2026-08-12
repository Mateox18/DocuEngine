"""Fixtures compartidas de la suite."""

from __future__ import annotations

import json
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


# ---------------------------------------------------------------------------
# Fixtures de la capa de recuperacion
#
# La suite no puede depender de base_vectorial/ ni de los modelos reales: los
# indices se construyen en otra etapa del pipeline y bajar bge-m3 son varios GB.
# Lo que sigue fabrica un indice con el MISMO formato que produce
# encoder/enc.py -un IndexIDMap(IndexFlatIP) mas un metadata.jsonl con el esquema
# de Chunk.to_dict()- sin importar ni ejecutar ninguno de los dos modulos.
#
# faiss y numpy se importan DENTRO de las funciones: si no estan instalados, solo
# fallan los tests de recuperacion en vez de romper la recoleccion entera.
# ---------------------------------------------------------------------------

DIM_FALSA = 1024   # la que CONFIG_ENCODERS declara para bge-m3


def vector_unitario(semilla: int, dim: int = DIM_FALSA) -> Any:
    """Vector de norma 1 reproducible. La semilla fija lo hace determinista."""
    import numpy as np

    generador = np.random.default_rng(semilla)
    vector = generador.standard_normal(dim).astype("float32")
    return vector / np.linalg.norm(vector)


def chunk_falso(
    *,
    id_: int,
    doc_id: str = "doc-a",
    texto: str | None = None,
    posicion: int = 0,
) -> dict[str, Any]:
    """Registro con el esquema exacto de Chunk.to_dict() (chunker/models.py:39-61)."""
    contenido = texto if texto is not None else f"contenido del chunk numero {id_}"
    return {
        "id_": id_,
        "doc_id": doc_id,
        "texto": contenido,
        "metadata": {
            "fuente": f"{doc_id}.pdf",
            "chunk_id": f"{doc_id}-chunk-{posicion:04d}",
            "num_tokens": len(contenido.split()),
            "formato": "pdf",
            "fenomeno": 1,
            "posicion": posicion,
            "seccion_path": [],
            "pagina": None,
            "tipo": "paragraph",
        },
    }


@pytest.fixture
def crear_base_vectorial(tmp_path: Path) -> Callable[..., Path]:
    """Escribe una base_vectorial/ sintetica y devuelve su ruta.

        base = crear_base_vectorial([chunk_falso(id_=0), chunk_falso(id_=1)])

    Por defecto cada chunk recibe un vector unitario derivado de su id_, asi que
    dos llamadas con los mismos registros producen el mismo indice.
    """

    def _crear(
        registros: Sequence[Mapping[str, Any]],
        *,
        vectores: Sequence[Any] | None = None,
        nombre: str = "bge-m3",
        dim: int = DIM_FALSA,
    ) -> Path:
        import faiss
        import numpy as np

        raiz = tmp_path / "base_vectorial"
        directorio = raiz / f"encoder_{nombre}"
        directorio.mkdir(parents=True, exist_ok=True)

        if vectores is None:
            vectores = [vector_unitario(r["id_"], dim) for r in registros]

        indice = faiss.IndexIDMap(faiss.IndexFlatIP(dim))
        indice.add_with_ids(
            np.ascontiguousarray(vectores, dtype="float32"),
            np.array([r["id_"] for r in registros], dtype="int64"),
        )
        faiss.write_index(indice, str(directorio / "index.faiss"))

        ruta_metadata = directorio / "metadata.jsonl"
        with open(ruta_metadata, "w", encoding="utf-8", newline="\n") as archivo:
            for registro in registros:
                archivo.write(json.dumps(registro, ensure_ascii=False) + "\n")

        return raiz

    return _crear
