"""Pruebas de la capa comun de limpieza."""

from parser.cleaning.boilerplate import detectar_repetidos, eliminar_repetidos
from parser.cleaning.dedup import calcular_hash, deduplicar_documentos
from parser.cleaning.dehyphen import unir_palabras_cortadas
from parser.cleaning.language import detectar_idioma, idioma_dominante
from parser.cleaning.normalize import (
    colapsar_espacios,
    normalizar_unicode,
    quitar_invisibles,
    reparar_mojibake,
)
from parser.cleaning.pipeline import limpiar_documento
from parser.cleaning.quality import evaluar_bloque
from parser.models import Block, ParsedDocument


def documento(*bloques: Block, doc_id: str = "d1") -> ParsedDocument:
    return ParsedDocument(
        doc_id=doc_id,
        fuente=f"{doc_id}.txt",
        formato="txt",
        fenomeno=1,
        ruta_original=f"/{doc_id}.txt",
        blocks=list(bloques),
    )


def test_normalizacion_basica() -> None:
    assert reparar_mojibake("ÃƒÂ³rbita") == "órbita"
    assert normalizar_unicode("ﬁgura") == "figura"
    assert quitar_invisibles("a\u200bb\u00adc") == "abc"
    assert colapsar_espacios("a   b\n\n\n\nc") == "a b\n\nc"


def test_dehyphen_une_corte_y_respeta_compuesto() -> None:
    assert unir_palabras_cortadas("informa-\nción") == "información"
    assert unir_palabras_cortadas("norte-sur") == "norte-sur"
    assert unir_palabras_cortadas("Perú-\nColombia") == "Perú-\nColombia"


def test_quality_descarta_basura_y_preserva_fila_numerica() -> None:
    assert evaluar_bloque(Block("paragraph", "l a s e g u r i d a d e n o r b i t a")) == (
        True,
        "basura_ocr",
    )
    assert evaluar_bloque(Block("table_row", "anio: 2023 | valor: 1200")) == (
        False,
        None,
    )


def test_boilerplate_marca_solo_bloques_completamente_repetidos() -> None:
    bloques = [
        Block("paragraph", "Contenido propio de la pagina."),
    ]
    doc = documento(*bloques)
    for pagina in range(1, 6):
        doc.blocks.append(
            Block(
                "paragraph",
                "Portal institucional",
                ancla={"pagina": pagina},
            )
        )
    repetidos = detectar_repetidos(doc)
    eliminar_repetidos(doc, repetidos)
    assert doc.blocks[-1].motivo_descarte == "boilerplate"


def test_idioma_dominante_pondera_por_caracteres() -> None:
    espanol = "Este es un resumen breve sobre el documento y sus resultados." * 2
    ingles = "This is a longer body of text describing the experiment and results." * 4
    assert detectar_idioma(espanol) == "es"
    assert detectar_idioma(ingles) == "en"
    doc = documento(Block("paragraph", espanol), Block("paragraph", ingles))
    for bloque in doc.blocks:
        bloque.idioma = detectar_idioma(bloque.texto)
    assert idioma_dominante(doc) == "en"


def test_hash_ignora_espaciado_y_descartados() -> None:
    primero = documento(Block("paragraph", "uno  dos"), Block("paragraph", "basura"))
    segundo = documento(Block("paragraph", "uno dos"))
    primero.blocks[-1].descartado = True
    assert calcular_hash(primero) == calcular_hash(segundo)


def test_deduplicar_conserva_mejor_extraccion() -> None:
    corto = documento(Block("paragraph", "contenido"), doc_id="a")
    largo = documento(Block("paragraph", "contenido mucho mas completo"), doc_id="b")
    corto.hash_contenido = largo.hash_contenido = "igual"
    conservados, eliminados = deduplicar_documentos([corto, largo])
    assert conservados == [largo]
    assert eliminados == ["a"]


def test_pipeline_normaliza_marca_calidad_idioma_y_hash() -> None:
    doc = documento(
        Block("paragraph", "Texto con  espacios  repetidos y longitud suficiente para probar.")
    )
    limpiar_documento(doc)
    assert doc.blocks[0].texto == "Texto con espacios repetidos y longitud suficiente para probar."
    assert doc.hash_contenido
