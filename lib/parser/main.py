import json
import os
import time
import traceback
from collections.abc import Iterator
from pathlib import Path

from lib.parser import selector
from lib.parser.models import ErrorParseo, ParsedDocument
from lib.parser.cleaning import pipeline

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
        inicio = time.perf_counter()
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
        duracion = time.perf_counter() - inicio
        if error is not None:
            print(
                f"[parseo] ERROR en {ruta.name} tras {duracion:.1f}s: "
                f"{error.excepcion}",
                flush=True,
            )
        elif documento is not None:
            print(
                f"[parseo] {documento.doc_id} procesado en {duracion:.1f}s: "
                f"{documento.fuente}",
                flush=True,
            )
        yield documento, error

def procesar_todo(
    raiz: Path,
    errores_salida: Path | None = None,
) -> tuple[list[ParsedDocument], list[ErrorParseo]]:
    """Procesa todo el corpus y devuelve documentos válidos y errores.

    Si ``errores_salida`` se proporciona, persiste un error JSON por línea al
    terminar el recorrido. El archivo se escribe aunque no haya errores.
    """
    documentos_procesados: list[ParsedDocument] = []
    errores: list[ErrorParseo] = []
    for documento, error in procesar_archivos(raiz):
        if error is not None:
            errores.append(error)
        elif documento is not None:
            documentos_procesados.append(documento)
    if errores_salida is not None:
        persistir_errores(errores, errores_salida)
    if len(documentos_procesados) == 0:
        raise RuntimeError("No se encontraron documentos procesables")

    return documentos_procesados, errores


def persistir_errores(errores: list[ErrorParseo], ruta: Path) -> None:
    """Guarda los errores de ingesta como JSONL UTF-8, uno por línea."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8", newline="\n") as archivo:
        for error in errores:
            archivo.write(
                json.dumps(error.to_dict(), ensure_ascii=False, separators=(",", ":"))
                + "\n"
            )
