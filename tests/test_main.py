"""Pruebas de integración del flujo de ingesta."""

import json
from pathlib import Path

import lib.parser as main

F1 = "F1_IA_y_Capacidades_Estrategicas"
F2 = "F2_Seguridad_Entorno_Espacial"


def _crear_corpus(raiz: Path) -> None:
    (raiz / F1).mkdir(parents=True)
    (raiz / F2).mkdir(parents=True)
    (raiz / F1 / "zeta.md").write_text("# Zeta\n\nContenido suficiente.", encoding="utf-8")
    (raiz / F1 / "alfa.xyz").write_text("no soportado", encoding="utf-8")
    (raiz / F2 / "beta.md").write_text("# Beta\n\nOtro contenido.", encoding="utf-8")


def test_recorrer_archivos_es_estable_y_no_incluye_directorios(tmp_path: Path) -> None:
    raiz = tmp_path / "docs"
    _crear_corpus(raiz)

    rutas = list(main.recorrer_archivos(raiz))

    assert [ruta.name for ruta in rutas] == ["alfa.xyz", "zeta.md", "beta.md"]
    assert all(ruta.is_file() for ruta in rutas)


def test_procesar_todo_infiere_fenomeno_genera_ids_y_omite_extension_desconocida(
    tmp_path: Path,
) -> None:
    raiz = tmp_path / "docs"
    _crear_corpus(raiz)

    documentos, errores = main.procesar_todo(raiz)

    assert errores == []
    assert [(doc.doc_id, doc.fenomeno) for doc in documentos] == [
        ("DOC-1-00001", 1),
        ("DOC-2-00001", 2),
    ]


def test_procesar_todo_conserva_error_de_parseo_y_continua(tmp_path: Path) -> None:
    raiz = tmp_path / "docs"
    carpeta = raiz / F1
    carpeta.mkdir(parents=True)
    (carpeta / "a_malo.json").write_text("{no es json", encoding="utf-8")
    (carpeta / "b_bueno.md").write_text("# Bueno\n\nContenido.", encoding="utf-8")

    documentos, errores = main.procesar_todo(raiz)

    assert [doc.doc_id for doc in documentos] == ["DOC-1-00002"]
    assert len(errores) == 1
    assert errores[0].ruta.endswith("a_malo.json")
    assert "ParserError" in errores[0].excepcion


def test_procesar_todo_persiste_errores_en_jsonl(tmp_path: Path) -> None:
    raiz = tmp_path / "docs"
    carpeta = raiz / F1
    carpeta.mkdir(parents=True)
    (carpeta / "malo.json").write_text("{no es json", encoding="utf-8")
    (carpeta / "bueno.md").write_text("# Bueno\n\nContenido.", encoding="utf-8")
    salida = tmp_path / "reportes" / "errores_parseo.jsonl"

    documentos, errores = main.procesar_todo(raiz, errores_salida=salida)

    assert len(documentos) == 1
    assert len(errores) == 1
    lineas = salida.read_text(encoding="utf-8").splitlines()
    assert len(lineas) == 1
    assert main.ErrorParseo.from_dict(json.loads(lineas[0])) == errores[0]


def test_procesar_todo_persiste_archivo_vacio_si_no_hay_errores(tmp_path: Path) -> None:
    raiz = tmp_path / "docs"
    carpeta = raiz / F1
    carpeta.mkdir(parents=True)
    (carpeta / "bueno.md").write_text("# Bueno\n\nContenido.", encoding="utf-8")
    salida = tmp_path / "errores_parseo.jsonl"

    _documentos, errores = main.procesar_todo(raiz, errores_salida=salida)

    assert errores == []
    assert salida.exists()
    assert salida.read_text(encoding="utf-8") == ""


def test_fallo_de_limpieza_se_aisla_por_archivo(tmp_path: Path, monkeypatch) -> None:
    raiz = tmp_path / "docs"
    carpeta = raiz / F1
    carpeta.mkdir(parents=True)
    (carpeta / "a.md").write_text("# A\n\nContenido.", encoding="utf-8")

    def limpieza_rota(_documento):
        raise RuntimeError("limpieza rota")

    monkeypatch.setattr(
        "lib.parser.cleaning.pipeline.limpiar_documento", limpieza_rota
    )

    resultados = list(main.procesar_archivos(raiz))
    documentos = [documento for documento, error in resultados if documento is not None]
    errores = [error for documento, error in resultados if error is not None]

    assert documentos == []
    assert len(errores) == 1
    assert errores[0].formato == "md"
    assert "limpieza rota" in errores[0].excepcion
