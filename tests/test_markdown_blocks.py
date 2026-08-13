"""Tests del motor de markdown en aislamiento, sin parser."""

from __future__ import annotations

from typing import Any

from lib.parser import Block, TipoBloque
from lib.parser.parsers.markdown_blocks import (
    extraer_front_matter,
    parsear_markdown,
)
from lib.parser.parsers import Pila


def _lineas(texto: str) -> list[str]:
    return texto.split("\n")


def test_motor_no_necesita_parser() -> None:
    # El motor se ejecuta pelado: es lo que permite testearlo sin BaseParser.
    res = parsear_markdown(_lineas("# Titulo\n\nCuerpo del informe."))

    assert [(b.tipo, b.texto) for b in res.bloques] == [
        ("heading", "Titulo"),
        ("paragraph", "Cuerpo del informe."),
    ]
    assert res.avisos == []


def test_inicio_desplaza_el_recorrido_pero_el_ancla_sigue_1_based() -> None:
    res = parsear_markdown(_lineas("saltada\nsaltada\n# Real"), inicio=2)

    assert len(res.bloques) == 1
    assert res.bloques[0].ancla["linea"] == 3


def test_pila_externa_se_respeta() -> None:
    pila: Pila = [(1, "Externo")]

    res = parsear_markdown(_lineas("Cuerpo."), pila=pila)

    assert res.bloques[0].seccion_path == ["Externo"]


def test_pila_externa_se_muta_para_el_llamante() -> None:
    pila: Pila = []

    parsear_markdown(_lineas("# A\n\n## B"), pila=pila)

    assert pila == [(1, "A"), (2, "B")]


def test_codigo_sin_cerrar_devuelve_aviso_y_no_lanza() -> None:
    res = parsear_markdown(_lineas("```\nx = 1"))

    assert res.bloques[0].ancla["es_codigo"] is True
    assert res.avisos == ["bloque de codigo sin cerrar desde la linea 1"]


def test_camino_feliz_no_deja_avisos() -> None:
    res = parsear_markdown(_lineas("```python\nx = 1\n```"))

    assert res.avisos == []
    assert res.bloques[0].ancla["lenguaje"] == "python"


def test_tabla_usa_la_convencion_compartida() -> None:
    res = parsear_markdown(_lineas("| a | b | c |\n|---|---|---|\n| 1 |   | 3 |"))

    assert res.bloques[0].texto == "a: 1 | c: 3"
    assert res.bloques[0].ancla["columnas"] == ["a", "b", "c"]


def test_los_bloques_no_comparten_la_pila_viva() -> None:
    res = parsear_markdown(_lineas("# A\n\nuno\n\n# B\n\ndos"))

    rutas = [b.seccion_path for b in res.bloques if b.tipo == "paragraph"]
    assert rutas == [["A"], ["B"]]


def test_fabrica_personalizada_se_usa_para_todos_los_bloques() -> None:
    usados: list[str] = []

    def fabrica(
        tipo: TipoBloque,
        texto: str,
        *,
        nivel: int | None = None,
        ancla: dict[str, Any] | None = None,
        seccion_path: list[str] | None = None,
    ) -> Block:
        usados.append(tipo)
        return Block(tipo=tipo, texto=texto, nivel=nivel)

    res = parsear_markdown(_lineas("# A\n\ntexto\n\n- item"), bloque=fabrica)

    assert usados == ["heading", "paragraph", "list_item"]
    assert len(res.bloques) == 3


def test_extraer_front_matter_es_pura() -> None:
    frente = extraer_front_matter(_lineas("---\ntitle: X\n---\n\nCuerpo."))

    assert frente.inicio == 3
    assert frente.crudo == "title: X"
    assert frente.datos == {"title": "X"}


def test_front_matter_sin_cierre_devuelve_inicio_0_y_crudo_none() -> None:
    frente = extraer_front_matter(_lineas("---\n\n# Encabezado"))

    assert frente.inicio == 0
    assert frente.crudo is None
    assert frente.datos == {}
