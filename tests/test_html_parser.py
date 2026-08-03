"""Tests del parser de HTML.

La mecanica de la cascada y la estructura se testean con las etapas parcheadas,
que es determinista. Los tests marcados `externo` ejercitan trafilatura de
verdad y por eso solo asertan propiedades (presencia/ausencia, umbrales), nunca
strings exactos ni que extractor gano: una version nueva puede cambiar eso sin
que el parser este roto.
"""

from __future__ import annotations

import socket

import pytest

from parser.models import ParsedDocument
from parser.parsers.base import ParserError
from parser.parsers.html_parser import Extraccion, HtmlParser

from conftest import RELLENO, Escribir, PaginaHtml

CENTINELA = "El satelite Nandu-2 completo su decimoquinta orbita de control"


def _parsear(escribir: Escribir, html: str, nombre: str = "p.html") -> ParsedDocument:
    return HtmlParser().parse(escribir(nombre, html), "DOC-2-00001", 2)


def _forzar_bs4(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deja solo la etapa bs4, que es la unica totalmente determinista."""
    monkeypatch.setattr(HtmlParser, "_con_trafilatura", lambda self, html: None)
    monkeypatch.setattr(HtmlParser, "_con_readability", lambda self, html: None)


# ------------------------------------------------------------ Basicos


def test_extensiones_y_formato(escribir: Escribir, pagina_html: PaginaHtml) -> None:
    for nombre in ("p.html", "p.htm"):
        doc = _parsear(escribir, pagina_html(), nombre)
        assert (doc.formato, doc.formato_pliego()) == ("html", "html")


@pytest.mark.externo
def test_pagina_simple_extrae_el_texto_principal(
    escribir: Escribir, pagina_html: PaginaHtml
) -> None:
    doc = _parsear(escribir, pagina_html(cuerpo=f"<p>{CENTINELA}. {RELLENO}</p>"))

    assert CENTINELA in doc.texto_completo()


@pytest.mark.externo
def test_boilerplate_no_aparece(escribir: Escribir, pagina_html: PaginaHtml) -> None:
    doc = _parsear(escribir, pagina_html(cuerpo=f"<p>{CENTINELA}. {RELLENO}</p>"))

    completo = doc.texto_completo()
    assert "CENTINELA_NAV" not in completo
    assert "CENTINELA_FOOTER" not in completo
    assert "CENTINELA_SCRIPT" not in completo


@pytest.mark.externo
def test_extractor_registrado(escribir: Escribir, pagina_html: PaginaHtml) -> None:
    doc = _parsear(escribir, pagina_html())

    assert doc.meta_extra["extractor"] in {"trafilatura", "readability", "bs4"}
    assert doc.meta_extra["extractores"]


# ------------------------------------------------------------- Cascada


def test_cascada_pasa_a_readability_si_trafilatura_da_poco(
    escribir: Escribir, pagina_html: PaginaHtml, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(HtmlParser, "_con_trafilatura", lambda self, html: None)

    doc = _parsear(escribir, pagina_html())

    assert doc.meta_extra["extractor"] in {"readability", "bs4"}
    assert "trafilatura" not in doc.meta_extra["extractores"]


def test_cascada_llega_a_bs4_si_las_dos_primeras_revientan(
    escribir: Escribir, pagina_html: PaginaHtml, monkeypatch: pytest.MonkeyPatch
) -> None:
    def revienta(self, html):
        raise RuntimeError("libreria rota")

    monkeypatch.setattr(HtmlParser, "_con_trafilatura", revienta)
    monkeypatch.setattr(HtmlParser, "_con_readability", revienta)

    doc = _parsear(escribir, pagina_html())

    assert doc.meta_extra["extractor"] == "bs4"
    assert doc.blocks
    assert len(doc.errores) == 2
    assert all("libreria rota" in e for e in doc.errores)


def test_se_queda_con_la_mejor_no_con_la_ultima(
    escribir: Escribir, pagina_html: PaginaHtml, monkeypatch: pytest.MonkeyPatch
) -> None:
    largo = "<p>" + RELLENO * 3 + "</p>"
    monkeypatch.setattr(
        HtmlParser,
        "_con_trafilatura",
        lambda self, html: Extraccion(largo, "html", "trafilatura", 900),
    )
    monkeypatch.setattr(
        HtmlParser, "_con_readability", lambda self, html: Extraccion("x", "html", "readability", 1)
    )

    doc = _parsear(escribir, pagina_html())

    assert doc.meta_extra["extractor"] == "trafilatura"


def test_pagina_vacia_lanza_parser_error(
    escribir: Escribir, pagina_html: PaginaHtml
) -> None:
    with pytest.raises(ParserError, match="insuficiente"):
        _parsear(escribir, pagina_html(cuerpo="<p>Hola.</p>"))


def test_umbral_cuenta_caracteres_utiles(
    escribir: Escribir, pagina_html: PaginaHtml
) -> None:
    # Miles de espacios y &nbsp; no salvan una pagina sin contenido.
    relleno = "&nbsp; " * 500
    with pytest.raises(ParserError, match="insuficiente"):
        _parsear(escribir, pagina_html(cuerpo=f"<p>Hola.{relleno}</p>"))


# ------------------------------------------------------------ Metadata


def test_metadata_de_head(escribir: Escribir, pagina_html: PaginaHtml) -> None:
    head = (
        '<meta property="og:title" content="Titulo OG">'
        '<meta property="og:description" content="Descripcion OG">'
        '<meta property="article:published_time" content="2024-03-15">'
        '<meta name="author" content="Observatorio Regional">'
        '<link rel="canonical" href="https://ejemplo.org/nota">'
    )
    doc = _parsear(escribir, pagina_html(head=head))

    assert doc.meta_extra["titulo_og"] == "Titulo OG"
    assert doc.meta_extra["descripcion"] == "Descripcion OG"
    assert doc.meta_extra["autor"] == "Observatorio Regional"
    assert doc.meta_extra["canonical"] == "https://ejemplo.org/nota"
    assert "2024-03-15" in str(doc.meta_extra["fecha"])


def test_lang_html_no_llena_doc_idioma(
    escribir: Escribir, pagina_html: PaginaHtml
) -> None:
    doc = _parsear(escribir, pagina_html(lang="es"))

    assert doc.meta_extra["lang_html"] == "es"
    # El idioma lo determina cleaning: el lang declarado miente con frecuencia.
    assert doc.idioma is None
    assert all(b.idioma is None for b in doc.blocks)


def test_titulo_prioriza_og_title_sobre_title(
    escribir: Escribir, pagina_html: PaginaHtml
) -> None:
    head = '<meta property="og:title" content="Desde OG">'
    doc = _parsear(escribir, pagina_html(head=head, titulo="Desde title"))

    assert doc.titulo == "Desde OG"


def test_titulo_no_recorta_el_sufijo_del_sitio(
    escribir: Escribir, pagina_html: PaginaHtml
) -> None:
    doc = _parsear(escribir, pagina_html(titulo="Noticia | El Diario"))

    assert doc.titulo == "Noticia | El Diario"


# ------------------------------------------------------------- Bloques


def test_seccion_path_desde_encabezados(
    escribir: Escribir, pagina_html: PaginaHtml, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forzar_bs4(monkeypatch)
    cuerpo = (
        "<h1>Informe</h1><h2>Riesgos</h2>"
        f"<p>{RELLENO}</p>"
    )
    doc = _parsear(escribir, pagina_html(cuerpo=cuerpo))

    parrafo = next(b for b in doc.blocks if b.tipo == "paragraph")
    assert parrafo.seccion_path == ["Informe", "Riesgos"]
    heading = next(b for b in doc.blocks if b.tipo == "heading")
    assert heading.seccion_path == []


def test_tabla_html_se_linealiza_igual_que_markdown(
    escribir: Escribir, pagina_html: PaginaHtml, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forzar_bs4(monkeypatch)
    cuerpo = (
        "<table><tr><th>a</th><th>b</th><th>c</th></tr>"
        "<tr><td>1</td><td></td><td>3</td></tr></table>"
        f"<p>{RELLENO}</p>"
    )
    doc = _parsear(escribir, pagina_html(cuerpo=cuerpo))

    fila = next(b for b in doc.blocks if b.tipo == "table_row")
    assert fila.texto == "a: 1 | c: 3"
    assert fila.ancla["columnas"] == ["a", "b", "c"]


def test_listas_generan_list_item_sin_duplicar_el_p_interior(
    escribir: Escribir, pagina_html: PaginaHtml, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forzar_bs4(monkeypatch)
    cuerpo = f"<ul><li><p>primero</p></li><li>segundo</li></ul><p>{RELLENO}</p>"
    doc = _parsear(escribir, pagina_html(cuerpo=cuerpo))

    items = [b for b in doc.blocks if b.tipo == "list_item"]
    assert [b.texto.strip() for b in items] == ["primero", "segundo"]
    parrafos = [b.texto.strip() for b in doc.blocks if b.tipo == "paragraph"]
    assert "primero" not in parrafos


def test_ancla_bs4_tiene_xpath_y_orden(
    escribir: Escribir, pagina_html: PaginaHtml, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forzar_bs4(monkeypatch)
    doc = _parsear(escribir, pagina_html())

    assert doc.blocks[0].ancla["orden"] == 0
    assert doc.blocks[0].ancla["xpath"].startswith("/")
    assert doc.blocks[0].ancla["extractor"] == "bs4"


def test_ancla_markdown_no_tiene_linea(
    escribir: Escribir, pagina_html: PaginaHtml, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Un numero de linea de un buffer sintetico es trazabilidad falsa.
    markdown = f"# Titulo\n\n{RELLENO}\n"
    monkeypatch.setattr(
        HtmlParser,
        "_con_trafilatura",
        lambda self, html: Extraccion(markdown, "markdown", "trafilatura", 400),
    )
    doc = _parsear(escribir, pagina_html())

    for bloque in doc.blocks:
        assert "linea" not in bloque.ancla
        assert "linea_fin" not in bloque.ancla
        assert bloque.ancla["extractor"] == "trafilatura"
    assert [b.ancla["orden"] for b in doc.blocks] == list(range(len(doc.blocks)))


def test_blockquote_y_pre(
    escribir: Escribir, pagina_html: PaginaHtml, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forzar_bs4(monkeypatch)
    cuerpo = f"<blockquote>citado</blockquote><pre>x = 1</pre><p>{RELLENO}</p>"
    doc = _parsear(escribir, pagina_html(cuerpo=cuerpo))

    anclas = {b.texto.strip(): b.ancla for b in doc.blocks}
    assert anclas["citado"]["cita"] is True
    assert anclas["x = 1"]["es_codigo"] is True


# --------------------------------------------------------------- Robustez


def test_no_hay_peticiones_de_red(
    escribir: Escribir, pagina_html: PaginaHtml, monkeypatch: pytest.MonkeyPatch
) -> None:
    def prohibido(*args, **kwargs):
        raise AssertionError("el parser intento abrir un socket")

    monkeypatch.setattr(socket, "socket", prohibido)
    monkeypatch.setattr(socket, "create_connection", prohibido)

    doc = _parsear(escribir, pagina_html(cuerpo=f"<p>{CENTINELA}. {RELLENO}</p>"))

    assert doc.blocks


def test_html_roto_no_lanza(escribir: Escribir) -> None:
    roto = f"<html><body><p>{RELLENO}<div><span>sin cerrar"

    doc = _parsear(escribir, roto)

    assert doc.blocks


def test_el_parser_no_limpia(
    escribir: Escribir, pagina_html: PaginaHtml, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forzar_bs4(monkeypatch)
    doc = _parsear(escribir, pagina_html(cuerpo=f"<p>{RELLENO}</p>"))

    assert all(b.idioma is None for b in doc.blocks)
    assert all(not b.descartado for b in doc.blocks)
    assert doc.idioma is None
    assert doc.hash_contenido is None


def test_encoding_se_registra(escribir: Escribir, pagina_html: PaginaHtml) -> None:
    doc = _parsear(escribir, pagina_html())

    assert doc.meta_extra["encoding"]
