"""Validacion del objeto de salida contra el esquema del pliego (9.3.1).

Se ejecuta sobre cada linea antes de escribirla. La alternativa -entregar el
archivo y esperar- es peor: un `resultados.jsonl` que el evaluador descarta no da
ninguna senal hasta que ya no hay margen para arreglarlo.

Aqui vive el UNICO rastro del limite de 250 palabras que queda en el modulo. El
resto de la capa asume que los chunks recuperados vienen con el tamano correcto y
no parte ni expande nada; esta comprobacion no corrige, solo delata que la
suposicion se rompio aguas arriba (el caso documentado en
`chunker/fragmentador.py:44-49`, una oracion unica mas larga que el limite).
"""

from __future__ import annotations

import re
from typing import Any

LIMITE_PALABRAS = 250
NUM_DOCUMENTOS = 3
NUM_FRAGMENTOS = 10

FORMATO_QUERY_ID = re.compile(r"^q\d{3}$")

CLAVES_RAIZ = frozenset({"query_id", "documents", "fragments"})
CLAVES_DOCUMENTO = frozenset({"rank", "doc_id"})
CLAVES_FRAGMENTO = frozenset({"rank", "chunk_id", "doc_id", "text"})


def _validar_claves(
    objeto: dict[str, Any], esperadas: frozenset[str], donde: str, errores: list[str]
) -> None:
    """Exige las claves del esquema, ni una menos ni una de mas."""
    faltan = sorted(esperadas - objeto.keys())
    sobran = sorted(objeto.keys() - esperadas)
    if faltan:
        errores.append(f"{donde}: faltan claves {faltan}")
    if sobran:
        errores.append(f"{donde}: claves no contempladas en el esquema {sobran}")


def _validar_ranks(
    elementos: list[Any], cantidad: int, donde: str, errores: list[str]
) -> None:
    """Exige ranks 1..cantidad exactos, sin huecos ni repeticiones."""
    ranks = [e.get("rank") for e in elementos if isinstance(e, dict)]
    if sorted(ranks, key=lambda r: (r is None, r)) != list(range(1, cantidad + 1)):
        errores.append(
            f"{donde}: los rank deben ser exactamente 1..{cantidad} sin repetir; "
            f"se recibio {ranks}"
        )


def _validar_texto_no_vacio(
    valor: Any, donde: str, errores: list[str]
) -> bool:
    """Comprueba que un campo sea una cadena con contenido."""
    if not isinstance(valor, str) or not valor.strip():
        errores.append(f"{donde}: debe ser una cadena no vacia, se recibio {valor!r}")
        return False
    return True


def validar_resultado(obj: dict[str, Any]) -> tuple[bool, list[str]]:
    """Valida un resultado completo y devuelve (es_valido, errores).

    Acumula todos los errores en vez de parar en el primero: al depurar una
    ejecucion de 50 consultas interesa ver todo lo que falla de una vez.
    """
    errores: list[str] = []

    if not isinstance(obj, dict):
        return False, [f"El resultado debe ser un objeto, se recibio {type(obj).__name__}"]

    _validar_claves(obj, CLAVES_RAIZ, "raiz", errores)

    query_id = obj.get("query_id")
    if not isinstance(query_id, str) or not FORMATO_QUERY_ID.match(query_id):
        errores.append(
            f"query_id: debe ser 'q' seguido de 3 digitos, se recibio {query_id!r}"
        )

    documentos = obj.get("documents")
    if not isinstance(documentos, list):
        errores.append(f"documents: debe ser una lista, se recibio {type(documentos).__name__}")
    else:
        if len(documentos) != NUM_DOCUMENTOS:
            errores.append(
                f"documents: debe tener exactamente {NUM_DOCUMENTOS} elementos, "
                f"tiene {len(documentos)}"
            )
        vistos: list[str] = []
        for posicion, documento in enumerate(documentos):
            donde = f"documents[{posicion}]"
            if not isinstance(documento, dict):
                errores.append(f"{donde}: debe ser un objeto")
                continue
            _validar_claves(documento, CLAVES_DOCUMENTO, donde, errores)
            if _validar_texto_no_vacio(documento.get("doc_id"), f"{donde}.doc_id", errores):
                doc_id = documento["doc_id"]
                if doc_id in vistos:
                    errores.append(f"{donde}.doc_id: duplicado ({doc_id!r})")
                vistos.append(doc_id)
        _validar_ranks(documentos, NUM_DOCUMENTOS, "documents", errores)

    fragmentos = obj.get("fragments")
    if not isinstance(fragmentos, list):
        errores.append(f"fragments: debe ser una lista, se recibio {type(fragmentos).__name__}")
    else:
        if len(fragmentos) != NUM_FRAGMENTOS:
            errores.append(
                f"fragments: debe tener exactamente {NUM_FRAGMENTOS} elementos, "
                f"tiene {len(fragmentos)}"
            )
        for posicion, fragmento in enumerate(fragmentos):
            donde = f"fragments[{posicion}]"
            if not isinstance(fragmento, dict):
                errores.append(f"{donde}: debe ser un objeto")
                continue
            _validar_claves(fragmento, CLAVES_FRAGMENTO, donde, errores)
            _validar_texto_no_vacio(fragmento.get("chunk_id"), f"{donde}.chunk_id", errores)
            _validar_texto_no_vacio(fragmento.get("doc_id"), f"{donde}.doc_id", errores)
            if _validar_texto_no_vacio(fragmento.get("text"), f"{donde}.text", errores):
                palabras = len(fragmento["text"].split())
                if palabras > LIMITE_PALABRAS:
                    errores.append(
                        f"{donde}.text: {palabras} palabras, el maximo es "
                        f"{LIMITE_PALABRAS}. El chunk se indexo por encima del "
                        f"limite; hay que corregirlo en el chunker."
                    )
        _validar_ranks(fragmentos, NUM_FRAGMENTOS, "fragments", errores)

    return not errores, errores
