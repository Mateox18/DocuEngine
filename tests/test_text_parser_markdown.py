"""Tests del modo Markdown de TextParser."""

from __future__ import annotations

from lib.parser import ParsedDocument
from lib.parser.parsers.text_parser import TextParser

from conftest import Escribir


def _parsear(escribir: Escribir, contenido: str, nombre: str = "doc.md") -> ParsedDocument:
    return TextParser().parse(escribir(nombre, contenido), "DOC-1-00001", 1)


def _de_tipo(doc: ParsedDocument, tipo: str) -> list:
    return [b for b in doc.blocks if b.tipo == tipo]


def test_jerarquia_multinivel_seccion_path(escribir: Escribir) -> None:
    doc = _parsear(
        escribir,
        "# Informe X\n\n## 3. Riesgos\n\n### 3.2 Colisiones\n\n"
        "Texto del riesgo.\n\n## 4. Cierre\n\nTexto final.\n",
    )

    esperado = [
        ("heading", "Informe X", 1, []),
        ("heading", "3. Riesgos", 2, ["Informe X"]),
        ("heading", "3.2 Colisiones", 3, ["Informe X", "3. Riesgos"]),
        ("paragraph", "Texto del riesgo.", None, ["Informe X", "3. Riesgos", "3.2 Colisiones"]),
        ("heading", "4. Cierre", 2, ["Informe X"]),
        ("paragraph", "Texto final.", None, ["Informe X", "4. Cierre"]),
    ]
    assert [(b.tipo, b.texto, b.nivel, b.seccion_path) for b in doc.blocks] == esperado


def test_ningun_heading_se_incluye_a_si_mismo(escribir: Escribir) -> None:
    doc = _parsear(escribir, "# A\n\n## B\n\n### C\n")

    for bloque in _de_tipo(doc, "heading"):
        assert bloque.texto not in bloque.seccion_path


def test_salto_de_nivel_h1_a_h3(escribir: Escribir) -> None:
    doc = _parsear(escribir, "# A\n\n### C\n\n## B\n\nTexto.\n")

    parrafo = _de_tipo(doc, "paragraph")[0]
    assert parrafo.seccion_path == ["A", "B"]


def test_setext_h1_y_h2(escribir: Escribir) -> None:
    doc = _parsear(escribir, "Titulo mayor\n===\n\nSubtitulo\n---\n\nCuerpo.\n")

    headings = _de_tipo(doc, "heading")
    assert [(b.texto, b.nivel, b.ancla["estilo"]) for b in headings] == [
        ("Titulo mayor", 1, "setext"),
        ("Subtitulo", 2, "setext"),
    ]
    # Las lineas de subrayado no generan bloque propio.
    assert len(doc.blocks) == 3


def test_hr_no_genera_bloque_ni_es_setext(escribir: Escribir) -> None:
    doc = _parsear(escribir, "parrafo uno\n\n---\n\nparrafo dos\n")

    assert _de_tipo(doc, "heading") == []
    assert [b.texto for b in doc.blocks] == ["parrafo uno", "parrafo dos"]


def test_asteriscos_y_guiones_bajos_siempre_son_hr(escribir: Escribir) -> None:
    doc = _parsear(escribir, "texto\n***\notro\n___\n")

    assert _de_tipo(doc, "heading") == []
    assert [b.texto for b in doc.blocks] == ["texto", "otro"]


def test_setext_solo_toma_la_ultima_linea_del_parrafo(escribir: Escribir) -> None:
    doc = _parsear(escribir, "linea uno\nlinea dos\nSubtitulo\n---\n")

    assert [(b.tipo, b.texto) for b in doc.blocks] == [
        ("paragraph", "linea uno\nlinea dos"),
        ("heading", "Subtitulo"),
    ]


def test_hashtag_sin_espacio_no_es_heading(escribir: Escribir) -> None:
    doc = _parsear(escribir, "#hashtag sin espacio\n")

    assert [(b.tipo, b.texto) for b in doc.blocks] == [
        ("paragraph", "#hashtag sin espacio")
    ]


def test_front_matter_va_a_meta_extra(escribir: Escribir) -> None:
    doc = _parsear(
        escribir,
        '---\ntitle: "Seguridad orbital"\nautor: Juan Perez\n---\n\n'
        "# Encabezado\n\nCuerpo del informe.\n",
    )

    assert doc.meta_extra["front_matter_datos"] == {
        "title": "Seguridad orbital",
        "autor": "Juan Perez",
    }
    assert "autor: Juan Perez" in doc.meta_extra["front_matter"]
    assert doc.titulo == "Seguridad orbital"
    assert all("autor" not in b.texto for b in doc.blocks)


def test_front_matter_sin_cierre_se_trata_como_hr(escribir: Escribir) -> None:
    doc = _parsear(escribir, "---\n\n# Encabezado\n\nCuerpo visible.\n")

    assert "front_matter" not in doc.meta_extra
    assert [b.texto for b in doc.blocks] == ["Encabezado", "Cuerpo visible."]


def test_listas_ordenadas_y_desordenadas(escribir: Escribir) -> None:
    doc = _parsear(escribir, "- primero\n- segundo\n\n1. uno\n2) dos\n")

    items = _de_tipo(doc, "list_item")
    assert [b.texto for b in items] == ["primero", "segundo", "uno", "dos"]
    assert all(b.nivel is None for b in items)
    assert [b.ancla["ordenada"] for b in items] == [False, False, True, True]


def test_lista_anidada_registra_sangria(escribir: Escribir) -> None:
    doc = _parsear(escribir, "- padre\n    - hijo\n")

    assert [b.ancla["sangria"] for b in _de_tipo(doc, "list_item")] == [0, 4]


def test_tabla_linealizada(escribir: Escribir) -> None:
    doc = _parsear(
        escribir,
        "| a | b | c |\n|---|---|---|\n| 1 |   | 3 |\n| 4 | 5 | 6 |\n",
    )

    filas = _de_tipo(doc, "table_row")
    assert [b.texto for b in filas] == ["a: 1 | c: 3", "a: 4 | b: 5 | c: 6"]
    # Ni la cabecera ni la separadora emiten bloque.
    assert len(doc.blocks) == 2
    assert filas[0].ancla["columnas"] == ["a", "b", "c"]
    assert filas[1].ancla["fila"] == 1


def test_tabla_fila_incompleta_y_sobrante(escribir: Escribir) -> None:
    doc = _parsear(
        escribir,
        "| a | b | c |\n|---|---|---|\n| 1 | 2 |\n| 1 | 2 | 3 | 4 |\n",
    )

    assert [b.texto for b in _de_tipo(doc, "table_row")] == [
        "a: 1 | b: 2",
        "a: 1 | b: 2 | c: 3 | col4: 4",
    ]


def test_tabla_cabecera_vacia_recibe_nombre_col(escribir: Escribir) -> None:
    doc = _parsear(escribir, "| a |  | c |\n|---|---|---|\n| 1 | 2 | 3 |\n")

    assert _de_tipo(doc, "table_row")[0].texto == "a: 1 | col2: 2 | c: 3"


def test_tabla_sin_separadora_no_es_tabla(escribir: Escribir) -> None:
    doc = _parsear(escribir, "| a | b |\n| 1 | 2 |\n")

    assert _de_tipo(doc, "table_row") == []
    assert _de_tipo(doc, "paragraph")[0].texto == "| a | b |\n| 1 | 2 |"


def test_linea_con_pipe_en_prosa_no_es_tabla(escribir: Escribir) -> None:
    doc = _parsear(escribir, "El operador | separa alternativas.\n")

    assert [b.tipo for b in doc.blocks] == ["paragraph"]


def test_bloque_de_codigo(escribir: Escribir) -> None:
    doc = _parsear(
        escribir,
        "```python\n# comentario, no es heading\nx = 1\n```\n",
    )

    bloque = doc.blocks[0]
    assert bloque.tipo == "paragraph"
    assert bloque.ancla["es_codigo"] is True
    assert bloque.ancla["lenguaje"] == "python"
    assert bloque.texto == "# comentario, no es heading\nx = 1"
    assert _de_tipo(doc, "heading") == []


def test_codigo_sin_cerrar_registra_error(escribir: Escribir) -> None:
    doc = _parsear(escribir, "```\nx = 1\ny = 2\n")

    assert doc.blocks[0].ancla["es_codigo"] is True
    assert doc.errores
    assert "sin cerrar" in doc.errores[0]


def test_titulo_desde_heading_de_nivel_minimo(escribir: Escribir) -> None:
    doc = _parsear(escribir, "## Indice\n\n# Real\n\nCuerpo.\n")

    assert doc.titulo == "Real"


def test_ancla_linea_es_1_based(escribir: Escribir) -> None:
    doc = _parsear(escribir, "# Primero\n\nParrafo.\n")

    assert doc.blocks[0].ancla["linea"] == 1
    assert doc.blocks[1].ancla["linea"] == 3


def test_cita_pierde_el_marcador(escribir: Escribir) -> None:
    doc = _parsear(escribir, "> citado aqui\n")

    assert doc.blocks[0].texto == "citado aqui"
    assert doc.blocks[0].ancla["cita"] is True


def test_el_parser_no_limpia(escribir: Escribir) -> None:
    doc = _parsear(
        escribir,
        "# Titulo\n\nTexto con **negrita**, [enlace](http://x)  y espacios.\n",
    )

    parrafo = _de_tipo(doc, "paragraph")[0]
    assert "**negrita**" in parrafo.texto
    assert "[enlace](http://x)" in parrafo.texto
    assert "  y espacios" in parrafo.texto
    # Territorio de cleaning: intacto.
    assert all(b.idioma is None for b in doc.blocks)
    assert all(not b.descartado for b in doc.blocks)
    assert doc.idioma is None
    assert doc.hash_contenido is None


def test_parrafo_conserva_el_soft_wrap(escribir: Escribir) -> None:
    doc = _parsear(escribir, "primera linea\nsegunda linea\n")

    assert doc.blocks[0].texto == "primera linea\nsegunda linea"


def test_formato_segun_extension(escribir: Escribir) -> None:
    md = _parsear(escribir, "# A\n", "doc.md")
    markdown = _parsear(escribir, "# A\n", "doc.markdown")
    txt = _parsear(escribir, "TITULO\n", "doc.txt")

    assert (md.formato, md.meta_extra["modo"]) == ("md", "markdown")
    assert (markdown.formato, markdown.meta_extra["modo"]) == ("md", "markdown")
    assert (txt.formato, txt.meta_extra["modo"]) == ("txt", "plano")
