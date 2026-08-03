"""Tests del parser de JSON y JSONL."""

from __future__ import annotations

import json

import pytest

from parser.models import ParsedDocument
from parser.parsers.base import ParserError
from parser.parsers.json_parser import JsonParser, inspeccionar_esquema

from conftest import Escribir


def _parsear(escribir: Escribir, datos, nombre: str = "doc.json") -> ParsedDocument:
    contenido = datos if isinstance(datos, str) else json.dumps(datos)
    return JsonParser().parse(escribir(nombre, contenido), "DOC-1-00001", 1)


def _textos(doc: ParsedDocument, tipo: str | None = None) -> list[str]:
    return [b.texto for b in doc.blocks if tipo is None or b.tipo == tipo]


# --------------------------------------------------------------- Topologias


def test_objeto_unico_con_titulo_y_cuerpo(escribir: Escribir) -> None:
    doc = _parsear(
        escribir, {"title": "Orbita baja", "content": "Parrafo uno.\n\nParrafo dos."}
    )

    assert [(b.tipo, b.texto) for b in doc.blocks] == [
        ("heading", "Orbita baja"),
        ("paragraph", "Parrafo uno."),
        ("paragraph", "Parrafo dos."),
    ]
    assert doc.meta_extra["topologia"] == "objeto_unico"


def test_lista_de_objetos_en_la_raiz(escribir: Escribir) -> None:
    doc = _parsear(
        escribir,
        [{"title": "Uno", "text": "Cuerpo uno."}, {"title": "Dos", "text": "Cuerpo dos."}],
    )

    assert doc.meta_extra["topologia"] == "lista_raiz"
    assert _textos(doc, "heading") == ["Uno", "Dos"]


@pytest.mark.parametrize("clave", ["articles", "items", "results", "data", "posts"])
def test_lista_anidada_bajo_clave_conocida(escribir: Escribir, clave: str) -> None:
    doc = _parsear(
        escribir,
        {clave: [{"title": "A", "text": "x"}, {"title": "B", "text": "y"}]},
    )

    assert doc.meta_extra["topologia"] == "clave_conocida"
    assert doc.meta_extra["ruta_registros"] == clave
    assert _textos(doc, "heading") == ["A", "B"]


def test_clave_conocida_con_un_solo_elemento_si_cuenta(escribir: Escribir) -> None:
    doc = _parsear(escribir, {"articles": [{"title": "Solo uno", "text": "cuerpo"}]})

    assert doc.meta_extra["topologia"] == "clave_conocida"
    assert _textos(doc, "heading") == ["Solo uno"]


def test_clave_desconocida_de_un_elemento_no_cuenta(escribir: Escribir) -> None:
    doc = _parsear(
        escribir,
        {"title": "Raiz", "content": "Cuerpo raiz.", "tags": [{"name": "politica"}]},
    )

    assert doc.meta_extra["topologia"] == "objeto_unico"
    assert "politica" not in doc.texto_completo()


def test_lista_anidada_a_dos_niveles(escribir: Escribir) -> None:
    doc = _parsear(
        escribir,
        {"response": {"docs": [{"title": "A", "text": "x"}, {"title": "B", "text": "y"}]}},
    )

    assert doc.meta_extra["ruta_registros"] == "response.docs"
    assert _textos(doc, "heading") == ["A", "B"]


# ------------------------------------------------------------------- Cuerpo


def test_lista_de_parrafos_un_bloque_cada_uno(escribir: Escribir) -> None:
    doc = _parsear(escribir, {"title": "T", "body_paragraphs": ["Uno.", "Dos.", "Tres."]})

    assert _textos(doc, "paragraph") == ["Uno.", "Dos.", "Tres."]


def test_lista_de_objetos_con_text(escribir: Escribir) -> None:
    doc = _parsear(
        escribir, {"title": "T", "content": [{"text": "Uno."}, {"text": "Dos."}]}
    )

    assert _textos(doc, "paragraph") == ["Uno.", "Dos."]


def test_string_se_parte_por_linea_en_blanco(escribir: Escribir) -> None:
    doc = _parsear(escribir, {"text": "Uno.\n\nDos."})

    assert _textos(doc, "paragraph") == ["Uno.", "Dos."]


def test_soft_wrap_no_se_parte(escribir: Escribir) -> None:
    doc = _parsear(escribir, {"text": "linea uno\nlinea dos"})

    assert _textos(doc, "paragraph") == ["linea uno\nlinea dos"]


# ------------------------------------------------------------------ Resumen


def test_resumen_solo_si_no_hay_cuerpo(escribir: Escribir) -> None:
    doc = _parsear(escribir, {"title": "T", "summary": "El resumen."})

    assert _textos(doc, "paragraph") == ["El resumen."]
    assert doc.blocks[-1].ancla["campo"] == "resumen"


def test_resumen_con_cuerpo_va_a_meta_y_no_a_bloques(escribir: Escribir) -> None:
    doc = _parsear(
        escribir, {"title": "T", "summary": "El resumen.", "content": "El cuerpo."}
    )

    assert _textos(doc, "paragraph") == ["El cuerpo."]
    assert doc.meta_extra["registros"][0]["resumen"] == "El resumen."


# ------------------------------------------------------------ Contaminacion


def test_campos_meta_no_entran_en_el_texto(escribir: Escribir) -> None:
    doc = _parsear(
        escribir,
        {
            "title": "T",
            "content": "El cuerpo.",
            "url": "http://ejemplo.org/a",
            "tags": ["politica", "seguridad"],
            "authors": ["Juan Perez"],
        },
    )

    completo = doc.texto_completo()
    assert "ejemplo.org" not in completo
    assert "politica" not in completo
    assert "Juan Perez" not in completo


# ------------------------------------------------------- Anclas y jerarquia


def test_ancla_lleva_registro_id_y_url(escribir: Escribir) -> None:
    doc = _parsear(
        escribir,
        {"articles": [{"id": "art-0091", "title": "T", "text": "c", "url": "http://x"},
                      {"id": "art-0092", "title": "U", "text": "d"}]},
    )

    assert doc.blocks[0].ancla["registro_id"] == "art-0091"
    assert doc.blocks[0].ancla["url"] == "http://x"
    # Sin url no se mete una clave con None que engorda la salida sin informar.
    assert "url" not in doc.blocks[2].ancla


def test_registro_sin_id_usa_el_indice(escribir: Escribir) -> None:
    doc = _parsear(escribir, [{"title": "A", "text": "x"}, {"title": "B", "text": "y"}])

    assert [b.ancla["registro_id"] for b in doc.blocks] == [0, 0, 1, 1]


def test_seccion_path_es_el_titulo_del_registro(escribir: Escribir) -> None:
    doc = _parsear(
        escribir, [{"title": "A", "text": "x"}, {"title": "B", "text": "y"}]
    )

    parrafos = [b for b in doc.blocks if b.tipo == "paragraph"]
    assert [b.seccion_path for b in parrafos] == [["A"], ["B"]]


def test_heading_no_se_incluye_en_su_propio_seccion_path(escribir: Escribir) -> None:
    doc = _parsear(escribir, {"title": "A", "text": "x"})

    assert doc.blocks[0].seccion_path == []


# --------------------------------------------------------------- Degradados


def test_registros_sin_texto_se_reportan_una_sola_vez(escribir: Escribir) -> None:
    doc = _parsear(
        escribir,
        {"articles": [{"title": "A", "text": "x"}, {"url": "http://y"}, {"tags": []}]},
    )

    assert len(doc.errores) == 1
    assert "2 registros sin campos de texto" in doc.errores[0]
    assert doc.meta_extra["registros_vacios"] == [1, 2]


def test_objeto_unico_sin_titulo_no_emite_heading(escribir: Escribir) -> None:
    doc = _parsear(escribir, {"text": "Solo cuerpo."})

    assert [b.tipo for b in doc.blocks] == ["paragraph"]
    assert doc.blocks[0].seccion_path == []


def test_titulo_documento_multirregistro_es_none(escribir: Escribir) -> None:
    doc = _parsear(escribir, [{"title": "A", "text": "x"}, {"title": "B", "text": "y"}])

    assert doc.titulo is None


def test_titulo_de_la_raiz_gana(escribir: Escribir) -> None:
    doc = _parsear(
        escribir,
        {"title": "Boletin semanal",
         "articles": [{"title": "A", "text": "x"}, {"title": "B", "text": "y"}]},
    )

    assert doc.titulo == "Boletin semanal"


def test_lista_vacia_marca_vacio_sin_excepcion(escribir: Escribir) -> None:
    doc = _parsear(escribir, [])

    assert doc.blocks == []
    assert doc.meta_extra["vacio"] is True
    assert doc.errores


# -------------------------------------------------------------------- JSONL


def test_jsonl_una_linea_por_registro(escribir: Escribir) -> None:
    contenido = '{"title": "A", "text": "x"}\n{"title": "B", "text": "y"}\n'
    doc = _parsear(escribir, contenido, "doc.jsonl")

    assert _textos(doc, "heading") == ["A", "B"]
    assert doc.formato == "jsonl"


def test_jsonl_linea_corrupta_se_descarta_y_el_resto_sobrevive(
    escribir: Escribir,
) -> None:
    contenido = '{"title": "A", "text": "x"}\n{roto\n{"title": "B", "text": "y"}\n'
    doc = _parsear(escribir, contenido, "doc.jsonl")

    assert _textos(doc, "heading") == ["A", "B"]
    assert any("linea 2 ilegible" in e for e in doc.errores)


def test_jsonl_todo_corrupto_lanza_parser_error(escribir: Escribir) -> None:
    with pytest.raises(ParserError, match="ningun registro legible"):
        _parsear(escribir, "{roto\n{tambien roto\n", "doc.jsonl")


def test_json_que_en_realidad_es_jsonl(escribir: Escribir) -> None:
    contenido = '{"title": "A", "text": "x"}\n{"title": "B", "text": "y"}\n'
    doc = _parsear(escribir, contenido, "doc.json")

    assert doc.meta_extra["modo"] == "jsonl_implicito"
    assert _textos(doc, "heading") == ["A", "B"]


def test_json_ilegible_lanza_parser_error(escribir: Escribir) -> None:
    with pytest.raises(ParserError, match="JSON ilegible"):
        _parsear(escribir, "{esto no es json", "doc.json")


# ------------------------------------------------------------------- Mapeo


@pytest.mark.parametrize("clave", ["articleBody", "article_body", "ARTICLE-BODY"])
def test_campos_se_reconocen_ignorando_mayusculas_y_guiones(
    escribir: Escribir, clave: str
) -> None:
    doc = _parsear(escribir, {"title": "T", clave: "El cuerpo."})

    assert _textos(doc, "paragraph") == ["El cuerpo."]
    assert doc.meta_extra["campos_detectados"]["cuerpo"] == clave


def test_formato_y_pliego_por_extension(escribir: Escribir) -> None:
    j = _parsear(escribir, {"text": "cuerpo"}, "a.json")
    jl = _parsear(escribir, '{"text": "cuerpo"}', "a.jsonl")

    assert (j.formato, j.formato_pliego()) == ("json", "md")
    assert (jl.formato, jl.formato_pliego()) == ("jsonl", "md")


def test_el_parser_no_limpia(escribir: Escribir) -> None:
    doc = _parsear(escribir, {"title": "T", "text": "Texto con  espacios."})

    assert "con  espacios" in doc.texto_completo()
    assert all(b.idioma is None for b in doc.blocks)
    assert doc.idioma is None
    assert doc.hash_contenido is None


# ---------------------------------------------------------------- Utilidad


def test_inspeccionar_esquema_devuelve_las_claves(escribir: Escribir) -> None:
    ruta = escribir("a.json", json.dumps({"articles": [{"title": "A", "text": "x"}] * 2}))

    arbol = inspeccionar_esquema(ruta)

    assert "topologia: clave_conocida" in arbol
    assert "title" in arbol and "text" in arbol


def test_inspeccionar_esquema_no_imprime(
    escribir: Escribir, capsys: pytest.CaptureFixture[str]
) -> None:
    ruta = escribir("a.json", json.dumps([{"title": "A"}, {"title": "B"}]))

    inspeccionar_esquema(ruta)

    assert capsys.readouterr().out == ""
