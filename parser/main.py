import os
import traceback
from collections.abc import Iterator
from pathlib import Path

from dotenv import load_dotenv

import parser.selector as selector
from parser.models import ErrorParseo, ParsedDocument
from parser.cleaning import pipeline
load_dotenv()

docs_path = os.getenv("DOCS_PATH")

if docs_path is None:
    raise RuntimeError("Falta la variable DOCS_PATH en el archivo .env")

raiz = Path(docs_path)


def recorrer_archivos(raiz: Path) -> Iterator[Path]:
    """Recorre archivos en un orden estable y con memoria acotada."""
    for directorio, subdirectorios, archivos in os.walk(raiz):
        subdirectorios.sort()
        archivos.sort()

        for nombre in archivos:
            yield Path(directorio) / nombre

def procesar_archivos(
    raiz: Path,
) -> Iterator[tuple[ParsedDocument | None, ErrorParseo | None]]:
    """Parsea y limpia archivos uno a uno, aislando fallos por archivo."""
    docs_por_fenomeno: dict[int, int] = {}
    for ruta in recorrer_archivos(raiz):
        parser = selector.detectar_parser(ruta)

        if parser is None:
            continue

        fenomeno = selector.inferir_fenomeno(ruta, raiz)
        if fenomeno is None:
            continue
        docs_por_fenomeno[fenomeno] = (
                docs_por_fenomeno.get(fenomeno, 0) + 1
        )
        doc_id = f"DOC-{fenomeno}-{docs_por_fenomeno[fenomeno]:05d}"
        documento, error = parser.parse_seguro(
            ruta,
            doc_id,
            fenomeno,
        )
        if error is None and documento is not None:
            try:
                documento = pipeline.limpiar_documento(documento)
            except Exception as exc:
                error = ErrorParseo(
                    ruta=str(ruta),
                    formato=documento.formato,
                    excepcion=f"{type(exc).__name__}: {exc}",
                    traceback=traceback.format_exc(),
                )
                documento = None
        yield documento, error

def procesar_todo(
    raiz: Path,
) -> tuple[list[ParsedDocument], list[ErrorParseo]]:
    """Procesa todo el corpus y devuelve documentos válidos y errores."""
    documentos_procesados: list[ParsedDocument] = []
    errores: list[ErrorParseo] = []
    for documento, error in procesar_archivos(raiz):
        if error is not None:
            print(error)
            errores.append(error)
        elif documento is not None:
            documentos_procesados.append(documento)
    if len(documentos_procesados) == 0:
        raise RuntimeError("No se encontraron documentos procesables")
    return documentos_procesados, errores
