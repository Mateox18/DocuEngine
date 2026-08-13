"""Parser de JSON y JSONL.

Cada fuente entrega su propio esquema y un mismo archivo puede traer un articulo
o cientos. El reto define "documento = archivo", asi que el doc_id es del
ARCHIVO, pero cada bloque conserva en `ancla["registro_id"]` a que registro
pertenece y lleva el titulo del registro en `seccion_path`. Eso es lo que
permitira al chunker no cruzar nunca la frontera entre dos articulos.

DECISION PENDIENTE (granularidad del doc_id)
Si un .json trae 400 articulos y el ground truth marca articulos individuales,
tratar el archivo entero como un doc_id hunde el F1@3: el documento recuperado
contiene la respuesta, pero tambien 399 articulos mas. Pendiente de confirmar
con la organizacion. El diseno actual permite explotar a un doc_id por registro
SIN tocar este parser: bastaria reagrupar por registro_id en selector.py. Por eso
el registro_id se guarda siempre, aunque hoy no se use.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from collections import deque
from pathlib import Path
from typing import Any

from lib.parser.models import Block, ParsedDocument
from lib.parser.parsers.base import BaseParser, ParserError
from lib.parser.parsers.lectura import leer_texto

logger = logging.getLogger(__name__)

# Claves bajo las que las fuentes reales cuelgan la lista de registros.
CLAVES_REGISTROS: tuple[str, ...] = (
    "articles",
    "items",
    "results",
    "data",
    "posts",
    "records",
    "documents",
    "entries",
    "rows",
    "hits",
    "docs",
)

# Candidatos por rol, en orden de prioridad.
CAMPOS_TEXTO: dict[str, tuple[str, ...]] = {
    "titulo": ("title", "titulo", "headline", "name"),
    "cuerpo": (
        "body_text",
        "body_paragraphs",
        "content",
        "text",
        "articleBody",
        "cuerpo",
        "descripcion",
    ),
    "resumen": ("summary", "abstract", "resumen", "description", "excerpt"),
}

# Campos descriptivos: van a meta_extra y NUNCA al texto de un bloque. Un
# "tags: politica, seguridad" suelto en medio del cuerpo desplaza el centroide
# del embedding.
CAMPOS_META: tuple[str, ...] = (
    "url",
    "link",
    "date",
    "published_at",
    "fecha",
    "authors",
    "author",
    "tags",
    "categories",
    "section",
    "source",
)

CAMPOS_ID: tuple[str, ...] = (
    "id",
    "_id",
    "registro_id",
    "doc_id",
    "uuid",
    "guid",
    "article_id",
)

# Claves de texto dentro de un parrafo cuando el cuerpo es una lista de objetos.
_CLAVES_PARRAFO: tuple[str, ...] = ("text", "paragraph", "content", "value")

# Titulos a nivel de raiz, hermanos de la lista de registros.
_CLAVES_TITULO_RAIZ: tuple[str, ...] = ("title", "titulo", "feed_title", "dataset")

# El resumen es un casi-duplicado del cuerpo: indexado compite consigo mismo y
# dos chunks del mismo articulo pueden ocupar 2 de los 3 huecos del F1@3.
EMITIR_RESUMEN_SIEMPRE = False

_PROFUNDIDAD_MAX = 3
_MAX_AVISOS_LINEA = 20
_RE_PARRAFOS = re.compile(r"\n\s*\n")


def _normalizar_clave(clave: str) -> str:
    """Clave comparable: minusculas y sin guiones ni guiones bajos."""
    return clave.lower().replace("_", "").replace("-", "")


def _indexar(registro: dict[str, Any]) -> dict[str, tuple[str, Any]]:
    """Indexa un registro por clave normalizada -> (clave original, valor)."""
    return {_normalizar_clave(k): (k, v) for k, v in registro.items()}


def _buscar(
    indice: dict[str, tuple[str, Any]], candidatos: tuple[str, ...]
) -> tuple[str, Any] | None:
    """Primer candidato presente en el indice, en orden de prioridad."""
    for candidato in candidatos:
        encontrado = indice.get(_normalizar_clave(candidato))
        if encontrado is not None and encontrado[1] not in (None, "", [], {}):
            return encontrado
    return None


def _es_lista_de_dicts(valor: Any) -> bool:
    return isinstance(valor, list) and bool(valor) and all(isinstance(x, dict) for x in valor)


def localizar_registros(datos: Any) -> tuple[list[Any], str | None, str]:
    """Localiza la lista de registros. Devuelve (registros, ruta, topologia).

    Topologias: "lista_raiz" | "lista_textos" | "clave_conocida" |
    "clave_inferida" | "objeto_unico".

    Las claves CONOCIDAS cuentan con >=1 elemento y las desconocidas con >1. El
    umbral >1 existe para no capturar una lista incidental como
    "tags": [{...}], pero aplicado a una clave conocida romperia el caso de un
    JSON con un solo articulo bajo "articles".
    """
    if isinstance(datos, list):
        if _es_lista_de_dicts(datos):
            return datos, None, "lista_raiz"
        if datos and all(isinstance(x, str) for x in datos):
            return datos, None, "lista_textos"
        return [datos] if datos else [], None, "objeto_unico"

    if not isinstance(datos, dict):
        raise ParserError(f"JSON escalar en la raiz: {type(datos).__name__}")

    # BFS por niveles: los APIs reales anidan, p.ej. {"response": {"docs": []}}.
    cola: deque[tuple[dict[str, Any], str, int]] = deque([(datos, "", 0)])
    while cola:
        nodo, ruta, nivel = cola.popleft()
        for conocidas in (True, False):
            for clave, valor in nodo.items():
                if not _es_lista_de_dicts(valor):
                    continue
                es_conocida = _normalizar_clave(clave) in {
                    _normalizar_clave(c) for c in CLAVES_REGISTROS
                }
                if conocidas != es_conocida:
                    continue
                if not es_conocida and len(valor) <= 1:
                    continue
                completa = f"{ruta}.{clave}" if ruta else clave
                return valor, completa, "clave_conocida" if es_conocida else "clave_inferida"
        if nivel < _PROFUNDIDAD_MAX:
            for clave, valor in nodo.items():
                if isinstance(valor, dict):
                    cola.append((valor, f"{ruta}.{clave}" if ruta else clave, nivel + 1))

    return [datos], None, "objeto_unico"


def inspeccionar_esquema(
    path: Path, n: int = 3, *, max_profundidad: int = 4, max_valor: int = 60
) -> str:
    """Arbol de claves de los primeros n registros, para configurar el mapeo.

    DEVUELVE el arbol como string y ademas lo emite por logging.INFO; no
    imprime. La convencion del proyecto prohibe print en codigo de libreria, y
    devolver el string es lo que hace la funcion testeable sin capsys.

    USO: correr sobre 3-5 archivos por carpeta de origen ANTES de dar por buena
    la configuracion de CAMPOS_TEXTO para esa fuente. Las fuentes heterogeneas
    son la causa numero uno de cuerpos vacios silenciosos.

        python -m lib.parser.parsers.json_parser ruta/al/archivo.json
    """
    datos = json.loads(leer_texto(path).texto)
    registros, ruta, topologia = localizar_registros(datos)

    lineas = [f"# {path.name}", f"topologia: {topologia}, ruta: {ruta or '(raiz)'}"]
    for indice, registro in enumerate(registros[:n]):
        lineas.append(f"[{indice}]")
        lineas.extend(_arbol(registro, "  ", max_profundidad, max_valor))
    arbol = "\n".join(lineas)
    logger.info("%s", arbol)
    return arbol


def _arbol(valor: Any, sangria: str, restante: int, max_valor: int) -> list[str]:
    """Representacion recursiva de las claves de un valor JSON."""
    if restante <= 0:
        return [f"{sangria}..."]
    if isinstance(valor, dict):
        salida = []
        for clave, sub in valor.items():
            salida.append(f"{sangria}{clave}: {_resumen(sub, max_valor)}")
            if isinstance(sub, dict) or _es_lista_de_dicts(sub):
                objetivo = sub if isinstance(sub, dict) else sub[0]
                salida.extend(_arbol(objetivo, sangria + "  ", restante - 1, max_valor))
        return salida
    return [f"{sangria}{_resumen(valor, max_valor)}"]


def _resumen(valor: Any, max_valor: int) -> str:
    """Tipo y muestra truncada de un valor."""
    if isinstance(valor, list):
        tipos = {type(x).__name__ for x in valor[:5]}
        return f"list[{len(valor)} {'/'.join(sorted(tipos)) or 'vacio'}]"
    if isinstance(valor, dict):
        return f"dict[{len(valor)} claves]"
    texto = repr(valor)
    if len(texto) > max_valor:
        texto = texto[:max_valor] + "..."
    return f"{type(valor).__name__} = {texto}"


class JsonParser(BaseParser):
    """Parser de .json y .jsonl."""

    EXTENSIONES = (".json", ".jsonl")
    FORMATO = "json"
    MAPA_FORMATOS = {".jsonl": "jsonl"}

    # ------------------------------------------------------------------ API

    def parse(self, path: Path, doc_id: str, fenomeno: int) -> ParsedDocument:
        """Parsea un .json/.jsonl respetando las fronteras entre registros."""
        doc = self._nuevo_documento(path, doc_id, fenomeno)
        leido = leer_texto(path, log=self.logger)
        doc.meta_extra["encoding"] = leido.encoding

        datos = self._cargar(leido.texto, path, doc)
        registros, ruta, topologia = localizar_registros(datos)
        doc.meta_extra["topologia"] = topologia
        if ruta:
            doc.meta_extra["ruta_registros"] = ruta

        bloques: list[Block] = []
        resumenes: list[dict[str, Any]] = []
        vacios: list[int] = []
        campos_detectados: dict[str, str] = {}

        for indice, registro in enumerate(registros):
            nuevos = self._parsear_registro(
                registro, indice, resumenes, campos_detectados
            )
            if nuevos:
                bloques.extend(nuevos)
            else:
                vacios.append(indice)

        doc.blocks = bloques
        doc.meta_extra["registros"] = resumenes
        if campos_detectados:
            doc.meta_extra["campos_detectados"] = campos_detectados
        if vacios:
            # Un solo aviso agregado: con 400 registros, 400 lineas de error
            # son ruido que oculta los problemas reales.
            muestra = ", ".join(str(i) for i in vacios[:10])
            sufijo = ", ..." if len(vacios) > 10 else ""
            doc.errores.append(
                f"{len(vacios)} registros sin campos de texto reconocibles "
                f"(indices: {muestra}{sufijo})"
            )
            doc.meta_extra["registros_vacios"] = vacios
            self.logger.warning(
                "%s: %d registros sin campos de texto", doc.fuente, len(vacios)
            )

        doc.titulo = self._deducir_titulo(datos, resumenes)

        if not doc.blocks:
            doc.meta_extra["vacio"] = True
            doc.errores.append("documento vacio: 0 bloques extraidos")
            self.logger.warning("documento vacio: %s", doc.fuente)
        return doc

    # -------------------------------------------------------------- Carga

    def _cargar(self, texto: str, path: Path, doc: ParsedDocument) -> Any:
        """Decodifica el JSON, tolerando lineas corruptas en JSONL."""
        if path.suffix.lower() == ".jsonl":
            registros = self._cargar_jsonl(texto, doc)
            if not registros:
                raise ParserError(f"ningun registro legible en {path.name}")
            return registros

        try:
            return json.loads(texto)
        except json.JSONDecodeError as exc:
            # Muchos volcados .json son en realidad objetos concatenados.
            registros = self._cargar_jsonl(texto, doc, silencioso=True)
            if len(registros) >= 2:
                doc.meta_extra["modo"] = "jsonl_implicito"
                return registros
            raise ParserError(f"JSON ilegible en {path.name}: {exc}") from exc

    def _cargar_jsonl(
        self, texto: str, doc: ParsedDocument, *, silencioso: bool = False
    ) -> list[Any]:
        """Lee linea a linea. Una linea corrupta se descarta, el resto sobrevive.

        Reventar el archivo entero contradice el aislamiento de fallos a escala
        de registro: 9.999 articulos buenos no se tiran por uno malo.
        """
        registros: list[Any] = []
        fallos = 0
        for numero, linea in enumerate(texto.split("\n"), start=1):
            if not linea.strip():
                continue
            try:
                registros.append(json.loads(linea))
            except json.JSONDecodeError as exc:
                fallos += 1
                if not silencioso and fallos <= _MAX_AVISOS_LINEA:
                    doc.errores.append(f"linea {numero} ilegible: {exc.msg}")
        if fallos > _MAX_AVISOS_LINEA and not silencioso:
            doc.errores.append(f"... y {fallos - _MAX_AVISOS_LINEA} lineas ilegibles mas")
        if fallos and not silencioso:
            self.logger.warning("%s: %d lineas ilegibles", doc.fuente, fallos)
        return registros

    # ---------------------------------------------------------- Registros

    def _parsear_registro(
        self,
        registro: Any,
        indice: int,
        resumenes: list[dict[str, Any]],
        campos_detectados: dict[str, str],
    ) -> list[Block]:
        """Convierte un registro en bloques. Lista vacia si no tiene texto."""
        if isinstance(registro, str):
            parrafos = self._parrafos_de(registro)
            if not parrafos:
                return []
            ancla_base = {"registro_id": indice}
            return [
                self._bloque(
                    "paragraph",
                    parrafo,
                    ancla={**ancla_base, "campo": "cuerpo", "parrafo": n},
                )
                for n, parrafo in enumerate(parrafos)
            ]

        if not isinstance(registro, dict):
            return []

        indice_campos = _indexar(registro)
        hallazgo_titulo = _buscar(indice_campos, CAMPOS_TEXTO["titulo"])
        hallazgo_cuerpo = _buscar(indice_campos, CAMPOS_TEXTO["cuerpo"])
        hallazgo_resumen = _buscar(indice_campos, CAMPOS_TEXTO["resumen"])

        for rol, hallazgo in (
            ("titulo", hallazgo_titulo),
            ("cuerpo", hallazgo_cuerpo),
            ("resumen", hallazgo_resumen),
        ):
            if hallazgo and rol not in campos_detectados:
                campos_detectados[rol] = hallazgo[0]

        titulo = str(hallazgo_titulo[1]).strip() if hallazgo_titulo else None
        parrafos = self._parrafos_de(hallazgo_cuerpo[1]) if hallazgo_cuerpo else []
        resumen = str(hallazgo_resumen[1]).strip() if hallazgo_resumen else None

        # El resumen solo se indexa si no hay cuerpo; si hay, va a meta_extra.
        usar_resumen = bool(resumen) and (not parrafos or EMITIR_RESUMEN_SIEMPRE)
        if not titulo and not parrafos and not usar_resumen:
            return []

        registro_id = self._registro_id(indice_campos, indice)
        url = self._meta_valor(indice_campos, ("url", "link"))
        ancla_base: dict[str, Any] = {"registro_id": registro_id}
        if url:
            ancla_base["url"] = url

        resumenes.append(
            {
                "registro_id": registro_id,
                "titulo": titulo,
                "url": url,
                "fecha": self._meta_valor(
                    indice_campos, ("date", "published_at", "fecha")
                ),
                "resumen": resumen if resumen and parrafos else None,
            }
        )

        bloques: list[Block] = []
        ruta = [titulo] if titulo else []
        if titulo:
            # seccion_path vacio: un heading nunca se incluye a si mismo.
            bloques.append(
                self._bloque(
                    "heading",
                    titulo,
                    nivel=1,
                    ancla={**ancla_base, "campo": "titulo"},
                )
            )
        if usar_resumen and resumen:
            bloques.append(
                self._bloque(
                    "paragraph",
                    resumen,
                    ancla={**ancla_base, "campo": "resumen"},
                    seccion_path=ruta,
                )
            )
        for n, parrafo in enumerate(parrafos):
            bloques.append(
                self._bloque(
                    "paragraph",
                    parrafo,
                    ancla={**ancla_base, "campo": "cuerpo", "parrafo": n},
                    seccion_path=ruta,
                )
            )
        return bloques

    def _parrafos_de(self, valor: Any) -> list[str]:
        """Normaliza el cuerpo a una lista de parrafos, sea cual sea su forma."""
        if isinstance(valor, str):
            # Se parte por linea en blanco, NUNCA por \n simple: el soft-wrap
            # se conserva, igual que en text_parser.
            return [p.strip() for p in _RE_PARRAFOS.split(valor) if p.strip()]
        if isinstance(valor, dict):
            return self._parrafos_de(self._texto_de_objeto(valor) or "")
        if isinstance(valor, list):
            parrafos: list[str] = []
            for elemento in valor:
                if isinstance(elemento, str):
                    if elemento.strip():
                        parrafos.append(elemento.strip())
                elif isinstance(elemento, dict):
                    texto = self._texto_de_objeto(elemento)
                    if texto:
                        parrafos.append(texto)
            return parrafos
        return []

    def _texto_de_objeto(self, objeto: dict[str, Any]) -> str | None:
        """Extrae la clave de texto de un parrafo-objeto."""
        indice = _indexar(objeto)
        hallazgo = _buscar(indice, _CLAVES_PARRAFO)
        if hallazgo and isinstance(hallazgo[1], str) and hallazgo[1].strip():
            return hallazgo[1].strip()
        return None

    def _registro_id(self, indice_campos: dict[str, tuple[str, Any]], indice: int) -> Any:
        """Id estable del registro, o su indice si no trae ninguno."""
        hallazgo = _buscar(indice_campos, CAMPOS_ID)
        return str(hallazgo[1]) if hallazgo else indice

    def _meta_valor(
        self, indice_campos: dict[str, tuple[str, Any]], candidatos: tuple[str, ...]
    ) -> Any:
        """Valor del primer campo de metadata presente, o None."""
        hallazgo = _buscar(indice_campos, candidatos)
        return hallazgo[1] if hallazgo else None

    # --------------------------------------------------------------- Titulo

    def _deducir_titulo(self, datos: Any, resumenes: list[dict[str, Any]]) -> str | None:
        """Titulo del documento, si tiene uno propio.

        Un archivo de 400 articulos no tiene titulo; fabricar uno mete ruido.
        """
        if isinstance(datos, dict):
            indice = _indexar(datos)
            hallazgo = _buscar(indice, _CLAVES_TITULO_RAIZ)
            if hallazgo and isinstance(hallazgo[1], str) and hallazgo[1].strip():
                return hallazgo[1].strip()
        if len(resumenes) == 1:
            return resumenes[0]["titulo"]
        return None


if __name__ == "__main__":  # pragma: no cover - utilidad manual
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logger.info("%s", inspeccionar_esquema(Path(sys.argv[1])))
