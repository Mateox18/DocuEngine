"""Tests del parser tabular sobre CSV y TSV."""

from __future__ import annotations

import pytest

from lib.parser import ParsedDocument
from lib.parser.parsers import tabular_parser
from lib.parser.parsers.tabular_parser import TabularParser

from conftest import Escribir


def _parsear(escribir: Escribir, contenido: str, nombre: str = "d.csv") -> ParsedDocument:
    return TabularParser().parse(escribir(nombre, contenido), "DOC-1-00001", 1)


def _filas(doc: ParsedDocument) -> list[str]:
    return [b.texto for b in doc.blocks if b.tipo == "table_row"]


# ------------------------------------------------------------- Cabecera


def test_cabecera_en_fila_0(escribir: Escribir) -> None:
    doc = _parsear(escribir, "pais,anio\nColombia,2023\nBrasil,2024\n")

    assert doc.meta_extra["fila_cabecera"] == 0
    assert _filas(doc) == ["pais: Colombia | anio: 2023", "pais: Brasil | anio: 2024"]


def test_preambulo_de_3_filas_y_cabecera_en_la_4(escribir: Escribir) -> None:
    contenido = (
        "AI conference attendance\n"
        "Fuente: AI Index 2024\n"
        "Notas: datos preliminares\n"
        "pais,anio,valor\n"
        "Colombia,2023,1200\n"
    )
    doc = _parsear(escribir, contenido)

    assert doc.meta_extra["fila_cabecera"] == 3
    assert "AI conference attendance" in doc.meta_extra["preambulo"]
    assert len(_filas(doc)) == 1


def test_preambulo_alimenta_prefijo_tabla_y_titulo(escribir: Escribir) -> None:
    contenido = "AI conference attendance\n\npais,anio\nColombia,2023\n"
    doc = _parsear(escribir, contenido)

    assert doc.titulo == "AI conference attendance"
    assert _filas(doc)[0].startswith("[Tabla: AI conference attendance] ")


def test_sin_cabecera_detectable_usa_coln_y_no_pierde_filas(escribir: Escribir) -> None:
    doc = _parsear(escribir, "1,2\n3,4\n5,6\n")

    assert doc.meta_extra["cabecera_detectada"] is False
    assert len(_filas(doc)) == 3
    assert _filas(doc)[0] == "col1: 1 | col2: 2"


def test_fila_de_numeros_no_se_confunde_con_cabecera(escribir: Escribir) -> None:
    doc = _parsear(escribir, "2019,2020\n10,20\n")

    assert doc.meta_extra["cabecera_detectada"] is False


def test_cabecera_con_celdas_repetidas_se_rechaza(escribir: Escribir) -> None:
    doc = _parsear(escribir, "pais,pais\nColombia,Brasil\n")

    assert doc.meta_extra["cabecera_detectada"] is False


def test_cabecera_repetida_no_se_detecta_asi_que_no_hay_ambiguedad(
    escribir: Escribir,
) -> None:
    # La regla de celdas distintas rechaza la fila; el fallback a colN evita
    # que se emita "x: 1 | x: 2", que seria ambiguo.
    doc = _parsear(escribir, "x,x,y\n1,2,3\n")

    assert doc.meta_extra["cabecera_detectada"] is False
    assert _filas(doc)[0] == "col1: x | col2: x | col3: y"


def test_columna_sin_nombre_recibe_coln(escribir: Escribir) -> None:
    doc = _parsear(escribir, "pais,,valor,nota\nColombia,x,10,ok\n")

    assert "col2: x" in _filas(doc)[0]


def test_una_sola_columna(escribir: Escribir) -> None:
    doc = _parsear(escribir, "frase uno\nfrase dos\n")

    assert doc.meta_extra["cabecera_detectada"] is False
    assert _filas(doc) == ["col1: frase uno", "col1: frase dos"]


# ---------------------------------------------------------- Delimitadores


def test_delimitador_punto_y_coma(escribir: Escribir) -> None:
    doc = _parsear(escribir, "pais;anio\nColombia;2023\nBrasil;2024\n")

    assert doc.meta_extra["delimitador"] == ";"
    assert _filas(doc)[0] == "pais: Colombia | anio: 2023"


def test_tsv_usa_tabulador_sin_sniffer(escribir: Escribir) -> None:
    doc = _parsear(escribir, "pais\tnota\nColombia\tuno, dos\n", "d.tsv")

    assert doc.meta_extra["delimitador"] == "\t"
    assert doc.formato == "tsv"
    assert _filas(doc)[0] == "pais: Colombia | nota: uno, dos"


def test_sniffer_que_falla_cae_a_la_heuristica(escribir: Escribir) -> None:
    # Un preambulo sin delimitadores es lo que suele romper a csv.Sniffer.
    contenido = "Titulo del dataset sin comas\n\npais,anio\nColombia,2023\n"
    doc = _parsear(escribir, contenido)

    assert doc.meta_extra["delimitador"] == ","
    assert _filas(doc)[0].endswith("pais: Colombia | anio: 2023")


# -------------------------------------------------------------- Encodings


def test_encoding_latin1(escribir: Escribir) -> None:
    # El acento es lo que hace los bytes invalidos en utf-8 y fuerza la caida
    # a latin-1; con texto ASCII puro la cascada nunca llegaria ahi.
    ruta = escribir("d.csv", "pais,región\nColombia,andina\n", encoding="latin-1")

    doc = TabularParser().parse(ruta, "DOC-1-00001", 1)

    assert doc.meta_extra["encoding"] == "latin-1"
    assert _filas(doc)[0] == "pais: Colombia | región: andina"


def test_bom_utf8(escribir: Escribir) -> None:
    ruta = escribir("d.csv", "pais,anio\nColombia,2023\n", encoding="utf-8-sig")

    doc = TabularParser().parse(ruta, "DOC-1-00001", 1)

    assert doc.meta_extra["encoding"] == "utf-8-sig"
    assert doc.meta_extra["bom"] is True
    assert _filas(doc)[0].startswith("pais: Colombia")


# ------------------------------------------------------------- Contenido


def test_valores_no_se_convierten(escribir: Escribir) -> None:
    doc = _parsear(escribir, "a,b,c,d\n0.10,007,NaN,1;5\n")

    fila = _filas(doc)[0]
    assert "a: 0.10" in fila
    assert "b: 007" in fila
    assert "c: NaN" in fila


def test_celdas_vacias_se_omiten(escribir: Escribir) -> None:
    doc = _parsear(escribir, "a,b,c\n1,,3\n")

    assert _filas(doc)[0] == "a: 1 | c: 3"


def test_ancla_fila_es_el_indice_original(escribir: Escribir) -> None:
    contenido = "Titulo\nFuente\nNotas\npais,anio\nColombia,2023\n"
    doc = _parsear(escribir, contenido)

    assert doc.blocks[0].ancla["fila"] == 4
    assert doc.blocks[0].ancla["hoja"] == ""


def test_filas_ragged_no_revientan(escribir: Escribir) -> None:
    # Ni las celdas de menos ni las de mas tumban la fila; las sobrantes
    # reciben colN en vez de perderse en silencio.
    doc = _parsear(escribir, "a,b,c\n1,2\n1,2,3,4\n")

    assert _filas(doc) == ["a: 1 | b: 2", "a: 1 | b: 2 | c: 3 | col4: 4"]


def test_comillas_y_salto_dentro_de_celda(escribir: Escribir) -> None:
    doc = _parsear(escribir, 'a,b\n"con, coma","con\nsalto"\n')

    assert _filas(doc)[0] == "a: con, coma | b: con\nsalto"


def test_archivo_vacio_marca_vacio_sin_excepcion(escribir: Escribir) -> None:
    doc = _parsear(escribir, "")

    assert doc.blocks == []
    assert doc.meta_extra["vacio"] is True
    assert doc.errores


def test_solo_cabecera_emite_la_fila_en_vez_de_perderla(escribir: Escribir) -> None:
    # Sin fila siguiente no hay cabecera detectable, asi que la unica fila se
    # trata como dato: perder la unica linea del archivo seria peor.
    doc = _parsear(escribir, "pais,anio\n")

    assert _filas(doc) == ["col1: pais | col2: anio"]


# ------------------------------------------------------- Tablas anchas


def _ancha(nombres: list[str], valores: list[str]) -> str:
    return ",".join(nombres) + "\n" + ",".join(valores) + "\n"


def test_tabla_ancha_descarta_columnas_no_informativas(escribir: Escribir) -> None:
    nombres = [f"campo_util_{i}" for i in range(20)] + [
        f"unnamed_{i}" for i in range(15)
    ]
    doc = _parsear(escribir, _ancha(nombres, ["v"] * 35))

    descartadas = doc.meta_extra["columnas_descartadas"]
    assert len(descartadas) == 15
    assert all(n.startswith("unnamed") for n in descartadas)
    assert "unnamed_0" not in _filas(doc)[0]


def test_filtro_de_columnas_se_omite_si_descarta_demasiado(escribir: Escribir) -> None:
    # 18 de 35 columnas se descartarian: mas de la mitad. Sin la valvula, la
    # tabla perderia la mayor parte de sus datos en silencio.
    nombres = [f"campo_{i}" for i in range(17)] + [f"unnamed_{i}" for i in range(18)]
    doc = _parsear(escribir, _ancha(nombres, ["v"] * 35))

    assert doc.meta_extra["filtro_columnas"] == "omitido"
    assert "columnas_descartadas" not in doc.meta_extra
    assert "unnamed_0: v" in _filas(doc)[0]
    assert "campo_0: v" in _filas(doc)[0]


def test_columnas_de_anios_no_detectan_cabecera_pero_no_pierden_filas(
    escribir: Escribir,
) -> None:
    # Limitacion documentada: una cabecera toda numerica no supera el umbral
    # textual, asi que los anios se emiten como una fila de datos mas.
    nombres = [str(1990 + i) for i in range(35)]
    doc = _parsear(escribir, _ancha(nombres, ["v"] * 35))

    assert doc.meta_extra["cabecera_detectada"] is False
    assert len(_filas(doc)) == 2
    assert "1990" in _filas(doc)[0]


# ---------------------------------------------------------------- Limite


def test_limite_de_filas(escribir: Escribir, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tabular_parser, "LIMITE_FILAS", 5)
    filas = "\n".join(f"Colombia,{2000 + i}" for i in range(20))
    doc = _parsear(escribir, f"pais,anio\n{filas}\n")

    assert len(_filas(doc)) == 5
    assert doc.meta_extra["truncado"] is True
    assert any("truncado" in e for e in doc.errores)


# --------------------------------------------------------------- Formato


def test_formato_y_pliego_por_extension(escribir: Escribir) -> None:
    c = _parsear(escribir, "a,b\n1,2\n", "d.csv")
    t = _parsear(escribir, "a\tb\n1\t2\n", "d.tsv")

    assert (c.formato, c.formato_pliego()) == ("csv", "md")
    assert (t.formato, t.formato_pliego()) == ("tsv", "md")


def test_el_parser_no_limpia(escribir: Escribir) -> None:
    doc = _parsear(escribir, "pais,anio\nColombia,2023\n")

    assert all(b.idioma is None for b in doc.blocks)
    assert all(not b.descartado for b in doc.blocks)
    assert doc.idioma is None
    assert doc.hash_contenido is None
