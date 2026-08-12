"""Tests unitarios para la clasificación estructural de líneas PDF."""

from pathlib import Path

import fitz

from parser.models import BBox, Block, TIPOS_BLOQUE
from parser.parsers.pdf_parser import PdfLine, PdfParser


def linea(
    texto: str,
    *,
    size: float = 10,
    bold: bool = False,
) -> PdfLine:
    """Construye una línea mínima para probar el clasificador."""
    return PdfLine(
        texto=texto,
        bbox=BBox(0, 0, 100, 12),
        font="Arial-Bold" if bold else "Arial",
        size=size,
        bold=bold,
        italic=False,
    )


def test_linea_normal_es_paragraph() -> None:
    parser = PdfParser()

    tipo = parser._tipo_linea(linea("Texto del cuerpo", size=10), 10)

    assert tipo == "paragraph"


def test_linea_grande_o_negrita_es_heading() -> None:
    parser = PdfParser()

    grande = parser._tipo_linea(linea("Sección", size=12), 10)
    negrita = parser._tipo_linea(linea("Sección", size=10, bold=True), 10)

    assert grande == "heading"
    assert negrita == "heading"


def test_caption_se_clasifica_antes_que_heading() -> None:
    parser = PdfParser()

    tipo = parser._tipo_linea(
        linea("Figura 1. Arquitectura del sistema", size=16, bold=True),
        10,
    )

    assert tipo == "caption"


def test_caption_sin_prefijo_se_detecta_cerca_de_imagen() -> None:
    parser = PdfParser()

    tipo = parser._tipo_linea(
        linea("Arquitectura propuesta del sistema", size=10),
        10,
        cerca_de_imagen=True,
    )

    assert tipo == "caption"


def test_heading_cercano_a_imagen_no_es_caption_si_destaca() -> None:
    parser = PdfParser()

    tipo = parser._tipo_linea(
        linea("Arquitectura del sistema", size=16, bold=True),
        10,
        cerca_de_imagen=True,
    )

    assert tipo == "heading"


def test_reconoce_variantes_de_caption() -> None:
    parser = PdfParser()

    tipos = [
        parser._tipo_linea(linea(texto, size=10), 10)
        for texto in (
            "Figura 1. Resultado",
            "Figure 2 - Result",
            "Gráfico 3: Tendencia",
            "Tabla 4. Datos",
            "Table 5: Results",
            "Cuadro 6. Resumen",
        )
    ]

    assert tipos == ["caption"] * 6


def test_agrupar_lineas_fusiona_solo_parrafos_contiguos() -> None:
    parser = PdfParser()
    lineas = [
        linea("Primera línea"),
        linea("Segunda línea"),
        linea("Título", size=14),
        linea("Tercera línea"),
        linea("Figura 1. Esquema"),
        linea("Cuarta línea"),
    ]

    grupos = parser._agrupar_lineas(lineas, 10)

    assert [tipo for tipo, _ in grupos] == [
        "paragraph",
        "heading",
        "paragraph",
        "caption",
        "paragraph",
    ]
    assert [
        [linea.texto for linea in lineas_grupo]
        for _, lineas_grupo in grupos
    ] == [
        ["Primera línea", "Segunda línea"],
        ["Título"],
        ["Tercera línea"],
        ["Figura 1. Esquema"],
        ["Cuarta línea"],
    ]


def test_agrupar_lineas_solo_produce_tipos_de_bloque_validos() -> None:
    parser = PdfParser()
    grupos = parser._agrupar_lineas(
        [linea("Texto"), linea("Título", size=14), linea("Tabla 1. Datos")],
        10,
    )

    assert all(tipo in TIPOS_BLOQUE for tipo, _ in grupos)


def test_pdf_usa_ocr_como_fallback_en_pagina_sin_texto(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ruta = tmp_path / "escaneado.pdf"
    pdf = fitz.open()
    pdf.new_page()
    pdf.save(ruta)
    pdf.close()

    bloque = Block(
        tipo="ocr_text",
        texto="Texto recuperado desde una página escaneada.",
        ancla={"bbox": [10, 20, 100, 40], "ocr": True, "pagina": 1},
    )
    monkeypatch.setattr(
        PdfParser,
        "_ocr_pagina",
        lambda self, page, numero: ([bloque], 91.5, 6),
    )

    doc = PdfParser().parse(ruta, "DOC-1-00001", 1)

    assert [b.texto for b in doc.blocks] == [
        "Texto recuperado desde una página escaneada."
    ]
    assert doc.meta_extra["paginas_ocr"] == [1]
    assert doc.meta_extra["confianza_ocr"] == {"1": 91.5}
    assert doc.meta_extra["psm_ocr"] == {"1": 6}


def test_pdf_no_invoca_ocr_si_la_pagina_tiene_texto(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ruta = tmp_path / "texto.pdf"
    pdf = fitz.open()
    pagina = pdf.new_page()
    pagina.insert_text((72, 72), "Texto seleccionable del documento.")
    pdf.save(ruta)
    pdf.close()

    def ocr_no_deberia_llamarse(*args, **kwargs):
        raise AssertionError("OCR no debía ejecutarse")

    monkeypatch.setattr(PdfParser, "_ocr_pagina", ocr_no_deberia_llamarse)

    doc = PdfParser().parse(ruta, "DOC-1-00001", 1)

    assert doc.blocks
    assert "paginas_ocr" not in doc.meta_extra
