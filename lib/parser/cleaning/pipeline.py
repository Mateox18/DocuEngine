"""Orquestador de limpieza; el orden de pasos es normativo."""

from __future__ import annotations

from lib.parser.cleaning.boilerplate import detectar_repetidos, eliminar_repetidos
from lib.parser.cleaning.dedup import calcular_hash, deduplicar_documentos
from lib.parser.cleaning.dehyphen import unir_palabras_cortadas
from lib.parser.cleaning.language import detectar_idioma, idioma_dominante
from lib.parser.cleaning.normalize import (
    colapsar_espacios,
    normalizar_unicode,
    quitar_invisibles,
    reparar_mojibake,
)
from lib.parser.cleaning.quality import evaluar_bloque
from lib.parser.models import ParsedDocument


def limpiar_documento(doc: ParsedDocument) -> ParsedDocument:
    """Limpia un documento in place y calcula idioma y hash."""
    for bloque in doc.blocks:
        texto = normalizar_unicode(
            quitar_invisibles(reparar_mojibake(bloque.texto))
        )
        if not bloque.ancla.get("es_codigo"):
            texto = colapsar_espacios(unir_palabras_cortadas(texto))
        else:
            texto = texto.strip("\n")
        bloque.texto = texto

    eliminar_repetidos(doc, detectar_repetidos(doc))
    for bloque in doc.blocks:
        if bloque.descartado:
            continue
        descartar, motivo = evaluar_bloque(bloque)
        if descartar:
            bloque.descartado = True
            bloque.motivo_descarte = motivo
    for bloque in doc.blocks:
        if not bloque.descartado:
            bloque.idioma = detectar_idioma(bloque.texto)
    doc.idioma = idioma_dominante(doc)
    doc.hash_contenido = calcular_hash(doc)
    return doc


def limpiar_corpus(
    docs: list[ParsedDocument],
) -> tuple[list[ParsedDocument], list[str]]:
    """Limpia todos los documentos y deduplica el corpus."""
    for doc in docs:
        limpiar_documento(doc)
    return deduplicar_documentos(docs)
