"""Parser de paginas HTML (.html, .htm).

Cascada de extraccion: trafilatura (markdown, descarta menus/pies/banners) ->
readability -> BeautifulSoup podado. La rama de trafilatura reutiliza el motor
de `markdown_blocks`, el mismo que usa TextParser.

CERO RED: a trafilatura se le pasa siempre contenido en memoria, nunca `url=` ni
fetch_url(). Hay un test que lo verifica parcheando socket.socket.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from lib.parser.models import Block, ParsedDocument
from lib.parser.parsers.base import BaseParser, ParserError
from lib.parser.parsers.lectura import normalizar_saltos
from lib.parser.parsers.markdown_blocks import parsear_markdown
from lib.parser.parsers.secciones import Pila, empujar_seccion, rutas
from lib.parser.parsers.tablas import linealizar_fila, nombrar_cabeceras

logger = logging.getLogger(__name__)

# Por debajo de este umbral la pagina es un shell de JavaScript o puro menu de
# navegacion, y es preferible descartarla a contaminar el indice.
MIN_CARACTERES_UTILES = 200

# Ruido estructural que no es contenido en ninguna pagina.
_ETIQUETAS_RUIDO = (
    "script",
    "style",
    "nav",
    "aside",
    "footer",
    "header",
    "form",
    "iframe",
    "noscript",
    "template",
    "svg",
)

_ETIQUETAS_BLOQUE = (
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "li", "blockquote", "pre", "figcaption", "caption", "dt", "dd",
)
# Un <p> dentro de un <li> ya lo capturo el <li>.
_CONTENEDORES = ("li", "tr", "pre", "figcaption", "caption")

try:  # pragma: no cover - depende del entorno
    import lxml  # noqa: F401

    _PARSER_BS4 = "lxml"
except ImportError:  # pragma: no cover
    _PARSER_BS4 = "html.parser"
    logger.warning("lxml no disponible: se usara html.parser, mas lento y laxo")


@dataclass(frozen=True)
class Extraccion:
    """Resultado de una etapa de la cascada."""

    contenido: str
    tipo: Literal["markdown", "html"]
    extractor: str
    utiles: int


def _utiles(texto: str) -> int:
    """Caracteres utiles: longitud tras colapsar espacios.

    Es una metrica de decision, no limpieza: el texto que se emite no se toca.
    """
    return len(" ".join(texto.split()))


class HtmlParser(BaseParser):
    """Parser de paginas HTML guardadas en disco."""

    EXTENSIONES = (".html", ".htm")
    FORMATO = "html"

    # ------------------------------------------------------------------ API

    def parse(self, path: Path, doc_id: str, fenomeno: int) -> ParsedDocument:
        """Parsea una pagina HTML aplicando la cascada de extractores."""
        doc = self._nuevo_documento(path, doc_id, fenomeno)

        # NO se usa lectura.leer_texto: el HTML declara su encoding en banda
        # (<meta charset>) y forzarle la cascada utf-8 -> latin-1 produce
        # mojibake en paginas legacy donde el navegador acierta. BeautifulSoup
        # respeta la declaracion via UnicodeDammit.
        sopa = self._sopa(path.read_bytes())
        doc.meta_extra["encoding"] = sopa.original_encoding
        html = str(sopa)

        mejor = self._cascada(sopa, html, doc)
        doc.meta_extra["extractor"] = mejor.extractor

        if mejor.tipo == "markdown":
            resultado = parsear_markdown(
                normalizar_saltos(mejor.contenido), bloque=self._bloque
            )
            doc.errores.extend(resultado.avisos)
            doc.blocks = self._reanclar(resultado.bloques, mejor.extractor)
        else:
            doc.blocks = self._bloques_desde_html(mejor.contenido, mejor.extractor)

        metadatos = self._metadatos(sopa, html)
        doc.meta_extra.update(metadatos)
        doc.titulo = self._deducir_titulo(metadatos, doc.blocks)

        if not doc.blocks:
            raise ParserError(f"sin bloques utiles tras la extraccion: {path.name}")
        return doc

    def _sopa(self, datos: bytes):
        """Construye la sopa. Siempre y primero: el <head> se necesita gane
        quien gane la cascada."""
        from bs4 import BeautifulSoup

        return BeautifulSoup(datos, _PARSER_BS4)

    # -------------------------------------------------------------- Cascada

    def _cascada(self, sopa, html: str, doc: ParsedDocument) -> Extraccion:
        """Aplica las tres etapas y devuelve la mejor extraccion.

        Se queda con la MEJOR, no con la ultima: si trafilatura da 180
        caracteres y bs4 da 40, indexar 180 es estrictamente mejor que reventar
        por 40. El umbral se aplica igual sobre la mejor, asi que una pagina
        vacia sigue produciendo ParserError.
        """
        etapas = (
            ("trafilatura", lambda: self._con_trafilatura(html)),
            ("readability", lambda: self._con_readability(html)),
            ("bs4", lambda: self._con_bs4(sopa)),
        )

        mejor: Extraccion | None = None
        traza: dict[str, int] = {}
        for nombre, etapa in etapas:
            try:
                extraccion = etapa()
            except Exception as exc:  # noqa: BLE001 - una libreria rota no
                # puede tumbar el archivo entero.
                doc.errores.append(f"extractor {nombre} fallo: {exc}")
                self.logger.warning("extractor %s fallo en %s: %s", nombre, doc.fuente, exc)
                continue
            if extraccion is None:
                continue
            traza[nombre] = extraccion.utiles
            if mejor is None or extraccion.utiles > mejor.utiles:
                mejor = extraccion
            if extraccion.utiles >= MIN_CARACTERES_UTILES:
                break

        doc.meta_extra["extractores"] = traza
        if mejor is None or mejor.utiles < MIN_CARACTERES_UTILES:
            # TENSION CONOCIDA: TextParser trata "vacio" como dato y no lanza,
            # porque la evaluacion empareja por `fuente`. Aqui lanzamos porque
            # indexar 40 caracteres de menu de navegacion contamina el indice.
            # Consecuencia: selector.py DEBE emitir un ParsedDocument
            # placeholder para todo archivo con ErrorParseo, o perdemos
            # cobertura de `fuente`.  TODO(selector): etapa 3.
            obtenidos = mejor.utiles if mejor else 0
            raise ParserError(
                f"contenido util insuficiente ({obtenidos} < {MIN_CARACTERES_UTILES} "
                f"caracteres) tras trafilatura/readability/bs4"
            )
        return mejor

    def _con_trafilatura(self, html: str) -> Extraccion | None:
        """Etapa a: markdown limpio, sin menus ni banners de cookies."""
        import trafilatura

        # Nunca se pasa `url=`: es lo que garantiza que no haya red.
        contenido = trafilatura.extract(
            html,
            output_format="markdown",
            include_tables=True,
            include_comments=False,
            favor_precision=False,
        )
        if not contenido:
            return None
        return Extraccion(contenido, "markdown", "trafilatura", _utiles(contenido))

    def _con_readability(self, html: str) -> Extraccion | None:
        """Etapa b: el fragmento que readability considera el articulo."""
        from readability import Document

        contenido = Document(html).summary(html_partial=True)
        if not contenido:
            return None
        texto = self._sopa(contenido.encode("utf-8")).get_text(" ", strip=True)
        return Extraccion(contenido, "html", "readability", _utiles(texto))

    def _con_bs4(self, sopa) -> Extraccion | None:
        """Etapa c: la pagina entera con el ruido estructural podado."""
        import copy

        podada = copy.copy(sopa)
        for etiqueta in podada.find_all(_ETIQUETAS_RUIDO):
            etiqueta.decompose()
        texto = podada.get_text(" ", strip=True)
        return Extraccion(str(podada), "html", "bs4", _utiles(texto))

    # -------------------------------------------------------------- Bloques

    def _reanclar(self, bloques: list[Block], extractor: str) -> list[Block]:
        """Sustituye el ancla de lineas por un ordinal de bloque.

        El markdown de trafilatura es sintetico: sus numeros de linea no existen
        en el .html original y fingir trazabilidad es peor que no darla. El
        ordinal si es estable y reproducible dado el mismo extractor.
        """
        for orden, bloque in enumerate(bloques):
            bloque.ancla.pop("linea", None)
            bloque.ancla.pop("linea_fin", None)
            bloque.ancla["orden"] = orden
            bloque.ancla["extractor"] = extractor
        return bloques

    def _bloques_desde_html(self, fragmento: str, extractor: str) -> list[Block]:
        """Recorre el fragmento en orden de documento emitiendo bloques."""
        sopa = self._sopa(fragmento.encode("utf-8"))
        pila: Pila = []
        bloques: list[Block] = []
        consumidos: set[int] = set()

        for indice, tabla in enumerate(sopa.find_all("table")):
            bloques.extend(self._bloques_de_tabla(tabla, indice, pila, consumidos))

        for nodo in sopa.find_all(_ETIQUETAS_BLOQUE):
            if id(nodo) in consumidos:
                continue
            if nodo.find_parent(_CONTENEDORES) is not None:
                continue
            bloque = self._bloque_de_nodo(nodo, pila)
            if bloque is not None:
                bloques.append(bloque)

        return self._reanclar_html(bloques, extractor)

    def _bloques_de_tabla(
        self, tabla, indice: int, pila: Pila, consumidos: set[int]
    ) -> list[Block]:
        """Linealiza una tabla HTML con la misma convencion que markdown."""
        filas = tabla.find_all("tr")
        if not filas:
            return []
        for fila in filas:
            consumidos.add(id(fila))

        cabeceras = nombrar_cabeceras(
            [c.get_text(" ", strip=True) for c in filas[0].find_all(("th", "td"))],
            unicos=True,
        )
        bloques: list[Block] = []
        ruta = rutas(pila)
        for numero, fila in enumerate(filas[1:]):
            celdas = [c.get_text(" ", strip=True) for c in fila.find_all(("th", "td"))]
            texto = linealizar_fila(cabeceras, celdas)
            if not texto:
                continue
            bloques.append(
                self._bloque(
                    "table_row",
                    texto,
                    ancla={
                        "tabla": indice,
                        "fila": numero,
                        "columnas": list(cabeceras),
                        "xpath": _xpath(fila),
                    },
                    seccion_path=ruta,
                )
            )
        return bloques

    def _bloque_de_nodo(self, nodo, pila: Pila) -> Block | None:
        """Convierte un nodo en Block, o None si no aporta texto."""
        # get_text sin colapsar espacios: el parser no limpia.
        texto = nodo.get_text(" ", strip=False)
        if not texto.strip():
            return None

        etiqueta = nodo.name
        ancla: dict[str, Any] = {"xpath": _xpath(nodo)}

        if etiqueta in ("h1", "h2", "h3", "h4", "h5", "h6"):
            nivel = int(etiqueta[1])
            ancestros = empujar_seccion(pila, nivel, texto.strip())
            return self._bloque(
                "heading", texto, nivel=nivel, ancla=ancla, seccion_path=ancestros
            )

        if etiqueta in ("figcaption", "caption"):
            tipo = "caption"
        elif etiqueta in ("li", "dd", "dt"):
            tipo = "list_item"
            if etiqueta == "dt":
                ancla["termino"] = True
        else:
            tipo = "paragraph"
            if etiqueta == "blockquote":
                ancla["cita"] = True
            elif etiqueta == "pre":
                ancla["es_codigo"] = True

        return self._bloque(tipo, texto, ancla=ancla, seccion_path=rutas(pila))

    def _reanclar_html(self, bloques: list[Block], extractor: str) -> list[Block]:
        """Anade el ordinal y el extractor a bloques que ya traen xpath.

        El xpath es aproximado: en la rama bs4 es relativo al documento podado y
        en readability al fragmento resumen, nunca al archivo original. La clave
        fiable en HTML es siempre `orden`.
        """
        for orden, bloque in enumerate(bloques):
            bloque.ancla["orden"] = orden
            bloque.ancla["extractor"] = extractor
        return bloques

    # ------------------------------------------------------------- Metadata

    def _metadatos(self, sopa, html: str) -> dict[str, Any]:
        """Metadata del <head>, con trafilatura primero y selectores despues."""
        datos: dict[str, Any] = {}

        try:
            import trafilatura

            md = trafilatura.extract_metadata(html)
            if md is not None:
                # En clave propia: trafilatura ya recorta el sufijo del sitio
                # ("Noticia | El Diario" -> "Noticia") y eso es limpieza. El
                # valor crudo de og:title / <title> manda; este es el respaldo.
                datos["titulo_trafilatura"] = md.title or None
                datos["descripcion"] = md.description or None
                datos["fecha"] = md.date or None
                datos["autor"] = md.author or None
                datos["sitio"] = md.sitename or None
                datos["canonical"] = md.url or None
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("extract_metadata fallo: %s", exc)

        for clave, valor in (
            ("titulo_og", self._meta(sopa, propiedad="og:title")),
            ("descripcion", self._meta(sopa, propiedad="og:description")
                or self._meta(sopa, nombre="description")),
            ("fecha", self._meta(sopa, propiedad="article:published_time")
                or self._meta(sopa, nombre="date")),
            ("autor", self._meta(sopa, nombre="author")
                or self._meta(sopa, propiedad="article:author")),
            ("sitio", self._meta(sopa, propiedad="og:site_name")),
        ):
            if valor and not datos.get(clave):
                datos[clave] = valor

        etiqueta_html = sopa.find("html")
        if etiqueta_html is not None and etiqueta_html.get("lang"):
            # A meta_extra, NUNCA a doc.idioma: el lang declarado miente con
            # frecuencia y el idioma real lo determina cleaning.
            datos["lang_html"] = etiqueta_html["lang"]

        canonical = sopa.find("link", rel="canonical")
        if canonical is not None and canonical.get("href"):
            datos["canonical"] = canonical["href"]

        titulo = sopa.find("title")
        if titulo is not None and titulo.get_text(strip=True):
            datos["titulo_html"] = titulo.get_text(strip=True)

        return {k: v for k, v in datos.items() if v}

    def _meta(self, sopa, *, nombre: str = "", propiedad: str = "") -> str | None:
        """Contenido de un <meta> por name o por property."""
        atributos = {"property": propiedad} if propiedad else {"name": nombre}
        etiqueta = sopa.find("meta", attrs=atributos)
        if etiqueta is None:
            return None
        contenido = etiqueta.get("content")
        return contenido.strip() if contenido else None

    def _deducir_titulo(
        self, metadatos: dict[str, Any], bloques: list[Block]
    ) -> str | None:
        """Titulo de la pagina. No se recorta el sufijo del sitio: eso es
        trabajo de cleaning, por eso el valor crudo va antes que el de
        trafilatura."""
        for clave in ("titulo_og", "titulo_html", "titulo_trafilatura"):
            valor = metadatos.get(clave)
            if valor:
                return str(valor)

        headings = [b for b in bloques if b.tipo == "heading" and b.nivel is not None]
        if headings:
            minimo = min(b.nivel for b in headings if b.nivel is not None)
            for bloque in headings:
                if bloque.nivel == minimo:
                    return bloque.texto.strip()
        return None


def _xpath(nodo) -> str:
    """Xpath aproximado del nodo, numerando hermanos homonimos."""
    partes: list[str] = []
    actual = nodo
    while actual is not None and getattr(actual, "name", None) is not None:
        padre = actual.parent
        if padre is None or getattr(padre, "name", None) is None:
            partes.append(actual.name)
            break
        hermanos = [h for h in padre.find_all(actual.name, recursive=False)]
        if len(hermanos) > 1:
            posicion = hermanos.index(actual) + 1
            partes.append(f"{actual.name}[{posicion}]")
        else:
            partes.append(actual.name)
        actual = padre
    return "/" + "/".join(reversed(partes))
