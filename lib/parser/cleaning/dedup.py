"""Hash y deduplicacion a nivel de documento."""

from __future__ import annotations

import hashlib
import logging

from lib.parser.models import ParsedDocument

logger = logging.getLogger(__name__)


def calcular_hash(doc: ParsedDocument) -> str:
    """Calcula SHA-256 del texto normalizado de bloques activos."""
    texto = "\n".join(" ".join(b.texto.split()) for b in doc.bloques_activos())
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def deduplicar_documentos(
    docs: list[ParsedDocument],
) -> tuple[list[ParsedDocument], list[str]]:
    """Conserva la mejor extraccion de cada hash y devuelve eliminados."""
    grupos: dict[str, list[ParsedDocument]] = {}
    sin_hash: list[ParsedDocument] = []
    for doc in docs:
        if doc.hash_contenido:
            grupos.setdefault(doc.hash_contenido, []).append(doc)
        else:
            sin_hash.append(doc)
    conservados = list(sin_hash)
    eliminados: list[str] = []
    for grupo in grupos.values():
        mejor = max(grupo, key=_calidad)
        conservados.append(mejor)
        eliminados.extend(doc.doc_id for doc in grupo if doc is not mejor)
    conservados.sort(key=lambda doc: doc.doc_id)
    return conservados, sorted(eliminados)


def _calidad(doc: ParsedDocument) -> tuple[int, int, str]:
    caracteres = sum(len(b.texto) for b in doc.bloques_activos())
    headings = sum(b.tipo == "heading" for b in doc.bloques_activos())
    return caracteres, headings, _invertir(doc.doc_id)


def _invertir(doc_id: str) -> str:
    return "".join(chr(0x10FFFF - ord(c)) for c in doc_id)
