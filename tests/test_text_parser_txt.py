"""Tests del modo texto plano de TextParser."""

from __future__ import annotations

import pytest

from parser.models import ParsedDocument
from parser.parsers.text_parser import TextParser

from conftest import Escribir


def _parsear(escribir: Escribir, contenido: str) -> ParsedDocument:
    return TextParser().parse(escribir("doc.txt", contenido), "DOC-1-00001", 1)


def test_parrafos_separados_por_linea_en_blanco(escribir: Escribir) -> None:
    doc = _parsear(escribir, "Primer parrafo largo.\n\nSegundo parrafo largo.\n")

    assert [(b.tipo, b.texto) for b in doc.blocks] == [
        ("paragraph", "Primer parrafo largo."),
        ("paragraph", "Segundo parrafo largo."),
    ]


def test_heading_en_mayusculas(escribir: Escribir) -> None:
    doc = _parsear(escribir, "RESUMEN EJECUTIVO\n\nContenido del resumen.\n")

    heading = doc.blocks[0]
    assert (heading.tipo, heading.nivel) == ("heading", 1)
    assert heading.ancla["estilo"] == "heuristica_txt"


@pytest.mark.parametrize(
    ("linea", "nivel"),
    [
        ("1. Introduccion", 1),
        ("3.2 Colisiones", 2),
        ("3.2.1 Detalle tecnico", 3),
    ],
)
def test_heading_numerado_infiere_nivel(
    escribir: Escribir, linea: str, nivel: int
) -> None:
    doc = _parsear(escribir, f"{linea}\n\nCuerpo de la seccion.\n")

    assert doc.blocks[0].nivel == nivel


def test_numerada_gana_a_mayusculas(escribir: Escribir) -> None:
    doc = _parsear(escribir, "3.2 RIESGOS\n\nCuerpo.\n")

    assert doc.blocks[0].nivel == 2


def test_no_es_heading_si_termina_en_punto(escribir: Escribir) -> None:
    doc = _parsear(escribir, "ESTO TERMINA EN PUNTO.\n\nCuerpo.\n")

    assert doc.blocks[0].tipo == "paragraph"


def test_no_es_heading_si_supera_80_caracteres(escribir: Escribir) -> None:
    largo = "A" * 85
    doc = _parsear(escribir, f"{largo}\n\nCuerpo.\n")

    assert doc.blocks[0].tipo == "paragraph"


def test_no_es_heading_si_no_esta_aislado(escribir: Escribir) -> None:
    doc = _parsear(escribir, "Contexto previo\nNOTA IMPORTANTE\nsigue el texto\n")

    assert [b.tipo for b in doc.blocks] == ["paragraph"]
    assert doc.blocks[0].texto == "Contexto previo\nNOTA IMPORTANTE\nsigue el texto"


def test_txt_no_interpreta_markdown(escribir: Escribir) -> None:
    doc = _parsear(escribir, "# Hola\n\n| a | b |\n\n- item de lista\n")

    assert [b.tipo for b in doc.blocks] == ["paragraph", "paragraph", "paragraph"]
    assert doc.blocks[0].texto == "# Hola"


def test_seccion_path_en_txt(escribir: Escribir) -> None:
    doc = _parsear(
        escribir,
        "1. Introduccion\n\nTexto uno.\n\n1.1 Alcance\n\nTexto dos.\n\n"
        "2. Metodo\n\nTexto tres.\n",
    )

    rutas = [b.seccion_path for b in doc.blocks if b.tipo == "paragraph"]
    assert rutas == [
        ["1. Introduccion"],
        ["1. Introduccion", "1.1 Alcance"],
        ["2. Metodo"],
    ]


def test_titulo_txt_primera_linea_si_no_hay_heading(escribir: Escribir) -> None:
    doc = _parsear(escribir, "Informe sobre orbita baja.\n\nCuerpo del informe.\n")

    assert doc.titulo == "Informe sobre orbita baja."
