import os
from pathlib import Path

from dotenv import load_dotenv

import parser.selector as selector
from parser.models import ParsedDocument

load_dotenv()

docs_path = os.getenv("DOCS_PATH")

if docs_path is None:
    raise RuntimeError("Falta la variable DOCS_PATH en el archivo .env")

raiz = Path(docs_path)
def recorrer_archivos(raiz: Path):
    for directorio, subdirectorios, archivos in os.walk(raiz):
        subdirectorios.sort()
        archivos.sort()

        for nombre in archivos:
            yield Path(directorio) / nombre

def procesar_archivos(raiz: Path):
    docs_por_fenomeno = {}
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
        yield documento, error

def procesar_todo(raiz: Path):
    documentos_procesados: list[ParsedDocument] = []
    for documento, error in procesar_archivos(raiz):
        if error is not None:
            print(error)
        else:
            documentos_procesados.append(documento)
    return documentos_procesados