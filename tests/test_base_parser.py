"""Tests del contrato de BaseParser.

El test mas importante de este archivo es test_fuente_preserva_el_nombre_exacto:
`fuente` es la clave de emparejamiento de la evaluacion del reto.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path

import pytest

from parser.models import ErrorParseo, ParsedDocument
from parser.parsers.base import BaseParser, ParserError

from conftest import Escribir


class ParserDummy(BaseParser):
    """Parser minimo para ejercitar la base sin depender de un formato."""

    EXTENSIONES = (".md", ".txt")
    FORMATO = "md"
    MAPA_FORMATOS = {".txt": "txt"}

    def parse(self, path: Path, doc_id: str, fenomeno: int) -> ParsedDocument:
        return self._nuevo_documento(path, doc_id, fenomeno)


class ParserRoto(ParserDummy):
    """Parser que siempre revienta, para probar el aislamiento de errores."""

    def parse(self, path: Path, doc_id: str, fenomeno: int) -> ParsedDocument:
        raise RuntimeError("xref corrupto")


@pytest.mark.parametrize(
    ("nombre", "esperado"),
    [(".md", True), (".MD", True), (".Md", True), (".txt", True), (".pdf", False)],
)
def test_puede_parsear_ignora_mayusculas_de_extension(
    nombre: str, esperado: bool
) -> None:
    assert ParserDummy.puede_parsear(Path(f"informe{nombre}")) is esperado


def test_puede_parsear_sin_extension() -> None:
    assert ParserDummy.puede_parsear(Path("README")) is False


def test_base_parser_no_es_instanciable() -> None:
    with pytest.raises(TypeError):
        BaseParser()  # type: ignore[abstract]


@pytest.mark.parametrize(
    "nombre",
    [
        "Informe FINAL Nandu (v2).MD",
        "reporte  con   espacios.md",
        "Analisis Area-2024 v1.0.md",
        "UPPER.MD",
        "Informe Ñandú Órbita.md",
    ],
)
def test_fuente_preserva_el_nombre_exacto(escribir: Escribir, nombre: str) -> None:
    ruta = escribir(nombre, "contenido")

    doc = ParserDummy().parse(ruta, "DOC-1-00001", 1)

    assert doc.fuente == nombre
    assert doc.fuente == ruta.name


def test_fuente_conserva_las_mayusculas(escribir: Escribir) -> None:
    ruta = escribir("Informe FINAL.MD", "contenido")

    doc = ParserDummy().parse(ruta, "DOC-1-00001", 1)

    assert doc.fuente != doc.fuente.lower()
    assert doc.fuente == "Informe FINAL.MD"


def test_fuente_no_se_normaliza_unicode(escribir: Escribir) -> None:
    # "Ñ" descompuesto (N + U+0303) no debe convertirse en su forma NFC.
    nombre_nfd = unicodedata.normalize("NFD", "Ñandu.md")
    assert nombre_nfd != unicodedata.normalize("NFC", nombre_nfd)
    ruta = escribir(nombre_nfd, "contenido")

    doc = ParserDummy().parse(ruta, "DOC-1-00001", 1)

    assert doc.fuente == ruta.name


def test_ruta_original_es_absoluta(escribir: Escribir) -> None:
    ruta = escribir("informe.md", "contenido")

    doc = ParserDummy().parse(ruta, "DOC-1-00001", 1)

    assert Path(doc.ruta_original).is_absolute()
    assert Path(doc.ruta_original).name == doc.fuente


def test_nuevo_documento_campos_base(escribir: Escribir) -> None:
    ruta = escribir("informe.md", "contenido")

    doc = ParserDummy().parse(ruta, "DOC-3-00042", 3)

    assert doc.doc_id == "DOC-3-00042"
    assert doc.fenomeno == 3
    assert doc.formato == "md"
    assert doc.blocks == []
    assert doc.titulo is None
    # Territorio de cleaning: el parser no los toca.
    assert doc.idioma is None
    assert doc.hash_contenido is None
    assert doc.errores == []
    assert doc.meta_extra == {}


@pytest.mark.parametrize(
    ("nombre", "esperado"),
    [("a.txt", "txt"), ("a.md", "md"), ("a.markdown", "md"), ("a.TXT", "txt")],
)
def test_formato_para_usa_mapa_y_fallback(nombre: str, esperado: str) -> None:
    assert ParserDummy.formato_para(Path(nombre)) == esperado


def test_bloque_copia_seccion_path() -> None:
    pila = ["Informe", "Riesgos"]

    bloque = ParserDummy()._bloque("paragraph", "texto", seccion_path=pila)
    pila.pop()

    assert bloque.seccion_path == ["Informe", "Riesgos"]


def test_bloque_copia_ancla() -> None:
    ancla = {"linea": 5}

    bloque = ParserDummy()._bloque("paragraph", "texto", ancla=ancla)
    ancla["linea"] = 99

    assert bloque.ancla == {"linea": 5}


def test_nuevo_documento_archivo_inexistente(tmp_path: Path) -> None:
    with pytest.raises(ParserError, match="no existe"):
        ParserDummy().parse(tmp_path / "fantasma.md", "DOC-1-00001", 1)


def test_nuevo_documento_directorio(tmp_path: Path) -> None:
    with pytest.raises(ParserError, match="no existe o no es un archivo"):
        ParserDummy().parse(tmp_path, "DOC-1-00001", 1)


def test_nuevo_documento_extension_no_soportada(escribir: Escribir) -> None:
    ruta = escribir("informe.pdf", "contenido")

    with pytest.raises(ParserError, match="no soporta la extension"):
        ParserDummy().parse(ruta, "DOC-1-00001", 1)


def test_parse_seguro_aisla_la_excepcion(escribir: Escribir) -> None:
    ruta = escribir("informe.md", "contenido")

    doc, error = ParserRoto().parse_seguro(ruta, "DOC-1-00001", 1)

    assert doc is None
    assert isinstance(error, ErrorParseo)
    assert error.excepcion == "RuntimeError: xref corrupto"
    assert "RuntimeError" in error.traceback
    assert error.formato == "md"
    assert error.ruta == str(ruta)


def test_parse_seguro_camino_feliz(escribir: Escribir) -> None:
    ruta = escribir("informe.md", "contenido")

    doc, error = ParserDummy().parse_seguro(ruta, "DOC-1-00001", 1)

    assert error is None
    assert doc is not None
    assert doc.fuente == "informe.md"
