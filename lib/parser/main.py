import json
import os
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
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

def _procesar_uno(
    ruta: Path,
    doc_id: str,
    fenomeno: int,
) -> tuple[ParsedDocument | None, ErrorParseo | None, float]:
    """Parsea y limpia un archivo; apto para ejecutarse en un worker."""
    inicio = time.perf_counter()
    parser = selector.detectar_parser(ruta)
    if parser is None:
        return None, None, time.perf_counter() - inicio

    documento, error = parser.parse_seguro(ruta, doc_id, fenomeno)
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
    return documento, error, time.perf_counter() - inicio


def procesar_archivos(
    raiz: Path,
    workers: int = 1,
) -> Iterator[tuple[ParsedDocument | None, ErrorParseo | None]]:
    """Parsea archivos aislando fallos, opcionalmente con varios workers.

    ``executor.map`` conserva el orden estable de entrada, por lo que los
    doc_id y la reproducibilidad del corpus no cambian al activar workers.
    """
    docs_por_fenomeno: dict[int, int] = {}
    trabajos: list[tuple[Path, str, int]] = []
    for ruta in recorrer_archivos(raiz):
        if selector.detectar_parser(ruta) is None:
            continue

        fenomeno = selector.inferir_fenomeno(ruta, raiz)
        if fenomeno is None:
            continue
        docs_por_fenomeno[fenomeno] = (
                docs_por_fenomeno.get(fenomeno, 0) + 1
        )
        doc_id = f"DOC-{fenomeno}-{docs_por_fenomeno[fenomeno]:05d}"
        trabajos.append((ruta, doc_id, fenomeno))

    workers = max(1, int(workers))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        resultados = executor.map(lambda trabajo: _procesar_uno(*trabajo), trabajos)
        for (ruta, _doc_id, _fenomeno), (documento, error, duracion) in zip(
            trabajos, resultados
        ):
            if error is not None:
                print(
                    f"[parseo] ERROR en {ruta.name} tras {duracion:.1f}s: "
                    f"{error.excepcion}", flush=True,
                )
            elif documento is not None:
                print(
                    f"[parseo] {documento.doc_id} procesado en {duracion:.1f}s: "
                    f"{documento.fuente}", flush=True,
                )
            yield documento, error

def procesar_todo(
    raiz: Path,
    errores_salida: Path | None = None,
    workers: int = 1,
) -> tuple[list[ParsedDocument], list[ErrorParseo]]:
    """Procesa todo el corpus y devuelve documentos válidos y errores.

    Si ``errores_salida`` se proporciona, persiste un error JSON por línea al
    terminar el recorrido. El archivo se escribe aunque no haya errores.
    """
    documentos_procesados: list[ParsedDocument] = []
    errores: list[ErrorParseo] = []
    for documento, error in procesar_archivos(raiz, workers=workers):
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
