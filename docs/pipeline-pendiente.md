# Pipeline de parseo y limpieza — cambios pendientes

**CODEFEST AD ASTRA 2026 · Etapa 1 del reto (hasta `ParsedDocument`)**

Este documento contiene, textualmente, lo que falta para cerrar el pipeline. No incluye chunking, embeddings ni FAISS.

---

## Estado actual

Implementado y con **222 tests en verde**:

```
parser/
  models.py                    Block, ParsedDocument, ErrorParseo, TipoBloque
  parsers/
    base.py                    BaseParser, ParserError, crear_bloque, FabricaBloques
    secciones.py               Pila, rutas, empujar_seccion
    tablas.py                  nombrar_cabeceras, linealizar_fila
    lectura.py                 TextoLeido, leer_texto, normalizar_saltos
    markdown_blocks.py         parsear_markdown, extraer_front_matter
    text_parser.py             .md .markdown .txt
    html_parser.py             .html .htm
    json_parser.py             .json .jsonl
    tabular_parser.py          .csv .tsv .xlsx .xls
```

Pendiente: `selector.py`, `main.py`, `qa_report.py`, y los parsers de imagen y PBF. `cleaning/` y el parser de PDF ya están implementados.

### API existente que hay que respetar

```python
# parser/models.py
TipoBloque = Literal["heading","paragraph","table_row","caption",
                     "list_item","cell","ocr_text","feature"]
TIPOS_BLOQUE: frozenset[str]
FORMATOS_PLIEGO: frozenset[str]                 # {"pdf","html","md"}

@dataclass
class Block:
    tipo: TipoBloque; texto: str; nivel: int | None = None
    ancla: dict[str, Any]; idioma: str | None = None
    seccion_path: list[str]; descartado: bool = False
    motivo_descarte: str | None = None

@dataclass(kw_only=True)
class ParsedDocument:
    doc_id: str; fuente: str; formato: str; fenomeno: int; ruta_original: str
    titulo: str | None = None; idioma: str | None = None
    hash_contenido: str | None = None
    meta_extra: dict[str, Any]; errores: list[str]; blocks: list[Block]
    def bloques_activos(self) -> list[Block]
    def texto_completo(self) -> str
    def num_palabras(self) -> int
    def formato_pliego(self) -> str

@dataclass
class ErrorParseo:                               # registro, NO excepcion
    ruta: str; formato: str; excepcion: str; traceback: str
```

```python
# parser/parsers/base.py
class ParserError(Exception): ...                # la excepcion
def crear_bloque(tipo, texto, *, nivel=None, ancla=None, seccion_path=None) -> Block

class BaseParser(ABC):
    EXTENSIONES: ClassVar[tuple[str, ...]]
    FORMATO: ClassVar[str]
    MAPA_FORMATOS: ClassVar[dict[str, str]]
    @classmethod
    def puede_parsear(cls, path: Path) -> bool
    @classmethod
    def formato_para(cls, path: Path) -> str
    @abstractmethod
    def parse(self, path: Path, doc_id: str, fenomeno: int) -> ParsedDocument
    def parse_seguro(self, path, doc_id, fenomeno) -> tuple[ParsedDocument | None, ErrorParseo | None]
    def _nuevo_documento(self, path, doc_id, fenomeno) -> ParsedDocument
    def _bloque(self, tipo, texto, *, nivel=None, ancla=None, seccion_path=None) -> Block
```

### Invariantes que no se pueden romper

1. `fuente` es `path.name` EXACTO. Sin `lower()`, sin `strip()`, sin normalización Unicode. Es la clave de emparejamiento de la evaluación.
2. Los parsers extraen; **solo `cleaning/` limpia**. Un parser nunca llena `idioma`, `hash_contenido` ni `descartado`.
3. `seccion_path` contiene solo ancestros, nunca el texto del propio bloque.
4. Tras `limpiar_documento`, el campo `texto` de cada bloque queda **congelado**.
5. Todo debe ser determinista entre ejecuciones: `generador.py` tiene que reproducir los resultados.
6. Logging con `logging`, nunca `print`.

---

## Parte A — `parser/models.py`: serialización

Añadir al final de `models.py`, y `SCHEMA_VERSION` arriba junto a las constantes.

```python
SCHEMA_VERSION = 1
```

Métodos nuevos en `Block`:

```python
    def to_dict(self) -> dict[str, Any]:
        """Serializa el bloque a un dict JSON-nativo."""
        return {
            "tipo": self.tipo,
            "texto": self.texto,
            "nivel": self.nivel,
            "ancla": dict(self.ancla),
            "idioma": self.idioma,
            "seccion_path": list(self.seccion_path),
            "descartado": self.descartado,
            "motivo_descarte": self.motivo_descarte,
        }

    @classmethod
    def from_dict(cls, datos: dict[str, Any]) -> Block:
        """Reconstruye un bloque producido por to_dict()."""
        return cls(**datos)
```

Métodos nuevos en `ParsedDocument`:

```python
    def to_dict(self) -> dict[str, Any]:
        """Serializa el documento a un dict JSON-nativo (round-trip exacto)."""
        return {
            "schema_version": SCHEMA_VERSION,
            "doc_id": self.doc_id,
            "fuente": self.fuente,
            "formato": self.formato,
            "fenomeno": self.fenomeno,
            "ruta_original": self.ruta_original,
            "titulo": self.titulo,
            "idioma": self.idioma,
            "hash_contenido": self.hash_contenido,
            "meta_extra": dict(self.meta_extra),
            "errores": list(self.errores),
            "blocks": [b.to_dict() for b in self.blocks],
        }

    @classmethod
    def from_dict(cls, datos: dict[str, Any]) -> ParsedDocument:
        """Reconstruye un documento producido por to_dict()."""
        campos = {k: v for k, v in datos.items() if k != "schema_version"}
        campos["blocks"] = [Block.from_dict(b) for b in campos.get("blocks", [])]
        return cls(**campos)
```

Y en `ErrorParseo`:

```python
    def to_dict(self) -> dict[str, Any]:
        """Serializa el registro de error."""
        return {
            "ruta": self.ruta,
            "formato": self.formato,
            "excepcion": self.excepcion,
            "traceback": self.traceback,
        }
```

> **Serialización explícita, no `dataclasses.asdict()`.** `asdict` es recursivo y hace `deepcopy` de todo, lo que con 10⁵ bloques cuesta; además no deja añadir `schema_version` ni controlar el orden de claves.
>
> **Invariante que estos métodos fuerzan:** todo lo que entre en `ancla` o `meta_extra` debe ser JSON-nativo. El riesgo concreto es el `bbox` del PDF parser: tiene que ser `list`, nunca `tuple`, y nunca un `Path`.

**Tests a añadir en `tests/test_models.py`:**

```python
def test_to_dict_es_json_serializable() -> None:
    doc = _documento(blocks=[Block("paragraph", "á", ancla={"bbox": [1.0, 2.0]})])
    json.dumps(doc.to_dict())          # no debe lanzar

def test_round_trip_to_dict_from_dict() -> None:
    doc = _documento(
        titulo="T", meta_extra={"origen": "pdf"}, errores=["aviso"],
        blocks=[Block("heading", "Á", nivel=1, ancla={"pagina": 3},
                      seccion_path=["X"], descartado=True, motivo_descarte="calidad")],
    )
    assert ParsedDocument.from_dict(doc.to_dict()) == doc

def test_to_dict_incluye_schema_version() -> None:
    assert _documento().to_dict()["schema_version"] == SCHEMA_VERSION
```

---

## Parte B — `parser/cleaning/` — implementado

Capa común implementada: se aplica idéntica a todos los `ParsedDocument` sin importar de qué parser vengan. **El orden de las operaciones importa.**

`parser/cleaning/__init__.py` conserva solo el docstring y **sin imports** (misma razón que en `parsers/`: evitar ciclos y no forzar la carga de ftfy/langdetect al importar el paquete).

### B.1 `parser/cleaning/normalize.py`

```python
"""Normalizacion de caracteres, previa a cualquier otro paso de limpieza."""

from __future__ import annotations

import re
import unicodedata

import ftfy

# Zero-width, BOM suelto y soft hyphen: invisibles que rompen la tokenizacion
# sin que nadie los vea al leer el texto.
_INVISIBLES = dict.fromkeys(
    [0x200B, 0x200C, 0x200D, 0xFEFF, 0x00AD, 0x2060, 0x180E]
)
# Espacios exoticos -> espacio normal. NFKC ya convierte U+00A0, pero no todos
# estos, y quitar_invisibles debe funcionar tambien si se llama por separado.
_ESPACIOS = dict.fromkeys(
    [0x00A0, 0x1680, 0x2000, 0x2001, 0x2002, 0x2003, 0x2004, 0x2005, 0x2006,
     0x2007, 0x2008, 0x2009, 0x200A, 0x202F, 0x205F, 0x3000],
    " ",
)
# Control C0 y C1 salvo \n y \t.
_CONTROL = dict.fromkeys(
    [c for c in range(0x00, 0x20) if c not in (0x09, 0x0A)]
    + list(range(0x7F, 0xA0))
)
_TABLA = {**_CONTROL, **_INVISIBLES, **_ESPACIOS}

_RE_ESPACIOS = re.compile(r"[ \t]+")
_RE_ESPACIO_FIN_LINEA = re.compile(r"[ \t]+\n")
_RE_SALTOS = re.compile(r"\n{3,}")


def reparar_mojibake(texto: str) -> str:
    """Corrige "Ã³" -> "ó". DEBE ir antes de NFKC.

    El mojibake es texto UTF-8 decodificado como latin-1: si se normaliza
    primero, NFKC fija los caracteres erroneos y ftfy ya no puede recuperarlos.
    Muy frecuente en HTML latinoamericano mal servido.
    """
    return ftfy.fix_text(texto)


def normalizar_unicode(texto: str) -> str:
    """NFKC: resuelve ligaduras (ﬁ -> fi), comillas tipograficas y guiones."""
    return unicodedata.normalize("NFKC", texto)


def quitar_invisibles(texto: str) -> str:
    """Elimina controles e invisibles y unifica los espacios exoticos."""
    return texto.translate(_TABLA)


def colapsar_espacios(texto: str) -> str:
    """Colapsa espacios repetidos conservando la senal de parrafo.

    CRITICO: se preserva "\\n\\n". El chunker lo necesita para saber donde
    empieza y acaba un parrafo; colapsarlo todo a un espacio destruye esa
    informacion y no hay forma de recuperarla despues.
    """
    texto = _RE_ESPACIOS.sub(" ", texto)
    texto = _RE_ESPACIO_FIN_LINEA.sub("\n", texto)
    texto = _RE_SALTOS.sub("\n\n", texto)
    return texto.strip()
```

### B.2 `parser/cleaning/dehyphen.py`

```python
"""Union de palabras cortadas por guion al final de linea."""

from __future__ import annotations

import re
from collections import Counter

# Guion al final de linea, con espacios opcionales alrededor del salto.
_RE_CORTE = re.compile(r"(\w+)-[ \t]*\n[ \t]*(\w+)")
_RE_PALABRA = re.compile(r"\w+", re.UNICODE)

_MIN_PREFIJO = 3


def unir_palabras_cortadas(texto: str) -> str:
    """Convierte "informa-\\nción" en "información".

    Sin esto, los PDF a dos columnas destrozan el vocabulario: "informa" y
    "ción" se convierten en tokens que no existen en el idioma y arruinan los
    embeddings del fragmento entero.

    NO se une cuando:
      - la letra siguiente es mayuscula ("Perú-\\nColombia" es un compuesto),
      - ambas partes existen como palabras independientes en el documento,
      - la parte previa al guion tiene menos de 3 caracteres.
    """
    vocabulario = _vocabulario(texto)

    def unir(match: re.Match[str]) -> str:
        izquierda, derecha = match.group(1), match.group(2)
        if not derecha[:1].islower():
            return match.group(0)
        if len(izquierda) < _MIN_PREFIJO:
            return match.group(0)
        if vocabulario[izquierda.lower()] and vocabulario[derecha.lower()]:
            return match.group(0)
        return izquierda + derecha

    return _RE_CORTE.sub(unir, texto)


def _vocabulario(texto: str) -> Counter[str]:
    """Palabras del documento, EXCLUYENDO las partidas por guion.

    Si no se excluyeran, "informa" y "ción" contarian como palabras
    independientes por su propia aparicion partida y la regla de excepcion
    bloquearia siempre la union.
    """
    sin_cortes = _RE_CORTE.sub(" ", texto)
    return Counter(p.lower() for p in _RE_PALABRA.findall(sin_cortes))
```

### B.3 `parser/cleaning/boilerplate.py`

```python
"""Deteccion de lineas repetidas: cabeceras, pies y boilerplate de sitio web.

Funciona igual para PDF y para HTML, por eso vive en la capa comun. En PDF los
grupos son paginas (via ancla["pagina"]); en el resto, cada bloque es un grupo.
"""

from __future__ import annotations

import logging
from collections import Counter

from parser.models import Block, ParsedDocument

logger = logging.getLogger(__name__)

LARGO_MAX_LINEA = 80
LARGO_MIN_LINEA = 3
MIN_GRUPOS = 4


def detectar_repetidos(doc: ParsedDocument, umbral: float = 0.3) -> set[str]:
    """Lineas cortas que aparecen en mas del `umbral` de paginas o secciones.

    Solo se consideran lineas de menos de 80 caracteres: una cabecera o un pie
    son cortos por definicion, y un parrafo largo repetido casi siempre es
    contenido legitimo (una cita, una nota al pie con valor).
    """
    grupos = _grupos(doc)
    if len(grupos) < MIN_GRUPOS:
        # Con dos o tres grupos, "aparece en el 30%" no significa nada.
        return set()

    conteo: Counter[str] = Counter()
    for grupo in grupos:
        conteo.update(grupo)

    minimo = umbral * len(grupos)
    return {linea for linea, veces in conteo.items() if veces > minimo}


def eliminar_repetidos(doc: ParsedDocument, repetidos: set[str]) -> None:
    """Marca como descartados los bloques cuyo contenido es todo boilerplate.

    Se exige que TODAS las lineas del bloque sean repetidas. Descartar un
    parrafo entero porque una de sus lineas coincide con un pie de pagina
    perderia contenido real.
    """
    if not repetidos:
        return
    descartados = 0
    for bloque in doc.blocks:
        if bloque.descartado:
            continue
        lineas = _lineas(bloque.texto)
        if lineas and all(linea in repetidos for linea in lineas):
            bloque.descartado = True
            bloque.motivo_descarte = "boilerplate"
            descartados += 1
    if descartados:
        logger.debug("%s: %d bloques de boilerplate", doc.fuente, descartados)


def _grupos(doc: ParsedDocument) -> list[set[str]]:
    """Conjuntos de lineas por pagina (si la hay) o por bloque."""
    por_pagina: dict[int, set[str]] = {}
    sueltos: list[set[str]] = []
    for bloque in doc.blocks:
        lineas = set(_lineas(bloque.texto))
        if not lineas:
            continue
        pagina = bloque.ancla.get("pagina")
        if isinstance(pagina, int):
            por_pagina.setdefault(pagina, set()).update(lineas)
        else:
            sueltos.append(lineas)
    return [por_pagina[k] for k in sorted(por_pagina)] + sueltos


def _lineas(texto: str) -> list[str]:
    """Lineas cortas normalizadas de un texto, candidatas a boilerplate."""
    salida = []
    for linea in texto.split("\n"):
        limpia = " ".join(linea.split())
        if LARGO_MIN_LINEA <= len(limpia) <= LARGO_MAX_LINEA:
            salida.append(limpia.casefold())
    return salida
```

> **Nota sobre el orden.** `detectar_repetidos` compara con `casefold()` y espacios colapsados, pero `eliminar_repetidos` **no modifica el texto**: solo marca. El texto emitido sigue siendo el original.

### B.4 `parser/cleaning/quality.py`

```python
"""Filtro de calidad a nivel de bloque."""

from __future__ import annotations

from parser.models import Block

LARGO_MINIMO = 20
RATIO_ALFA_MINIMO = 0.5
RATIO_SIMBOLOS_MAXIMO = 0.7
RATIO_TOKENS_SUELTOS_MAXIMO = 0.3

# Estos tipos son mayoritariamente numericos POR NATURALEZA: una fila de tabla
# o un feature geografico no tienen por que parecer prosa. Solo se les aplica
# el minimo de caracteres.
TIPOS_ESTRUCTURADOS = frozenset({"table_row", "cell", "feature"})


def evaluar_bloque(block: Block) -> tuple[bool, str | None]:
    """Devuelve (descartar, motivo)."""
    texto = block.texto.strip()
    if len(texto) < LARGO_MINIMO:
        return True, "corto"

    if block.tipo in TIPOS_ESTRUCTURADOS:
        return False, None

    caracteres = [c for c in texto if not c.isspace()]
    if not caracteres:
        return True, "corto"

    alfabeticos = sum(1 for c in caracteres if c.isalpha())
    if alfabeticos / len(caracteres) < RATIO_ALFA_MINIMO:
        return True, "poco_alfabetico"

    simbolos = sum(1 for c in caracteres if not c.isalpha() and not c.isspace())
    if simbolos / len(caracteres) > RATIO_SIMBOLOS_MAXIMO:
        return True, "muchos_simbolos"

    tokens = texto.split()
    if tokens:
        sueltos = sum(1 for t in tokens if len(t) == 1 and t.isalpha())
        if sueltos / len(tokens) > RATIO_TOKENS_SUELTOS_MAXIMO:
            # Firma tipica de OCR mal segmentado: "l a s e g u r i d a d".
            return True, "basura_ocr"

    return False, None
```

### B.5 `parser/cleaning/language.py`

```python
"""Deteccion de idioma a nivel de bloque.

Se detecta POR BLOQUE, no por documento: muchos informes traen el resumen en
espanol y el cuerpo en ingles, y marcar el documento entero con un solo idioma
degrada la recuperacion cruzada.
"""

from __future__ import annotations

import logging
from collections import Counter

from langdetect import DetectorFactory, LangDetectException, detect_langs

from parser.models import ParsedDocument

logger = logging.getLogger(__name__)

# Sin esto langdetect es no determinista y la ejecucion no se puede reproducir,
# que es requisito del reto.
DetectorFactory.seed = 0

LARGO_MINIMO = 40
CONFIANZA_MINIMA = 0.70


def detectar_idioma(texto: str) -> str | None:
    """Codigo ISO 639-1, o None si el bloque es corto o la confianza es baja."""
    limpio = texto.strip()
    if len(limpio) < LARGO_MINIMO:
        return None
    try:
        candidatos = detect_langs(limpio)
    except LangDetectException:
        return None
    if not candidatos:
        return None
    mejor = candidatos[0]
    if mejor.prob < CONFIANZA_MINIMA:
        return None
    return mejor.lang.split("-")[0]


def idioma_dominante(doc: ParsedDocument) -> str | None:
    """Idioma mas frecuente ponderado por numero de caracteres."""
    pesos: Counter[str] = Counter()
    for bloque in doc.bloques_activos():
        if bloque.idioma:
            pesos[bloque.idioma] += len(bloque.texto)
    if not pesos:
        return None
    return pesos.most_common(1)[0][0]
```

> **Por qué langdetect y no fasttext.** El modelo `lid.176` de fasttext es un binario de 126 MB que hay que descargar. Eso choca con la regla "sin dependencias de red en tiempo de ejecución" y obliga a versionar un blob en el repo. `langdetect` es Python puro y trae sus perfiles dentro del paquete. Si más adelante hace falta más precisión, la firma de `detectar_idioma` no cambia: se sustituye el cuerpo.

### B.6 `parser/cleaning/dedup.py`

```python
"""Deduplicacion a nivel de DOCUMENTO.

El mismo informe llega con frecuencia como PDF y como HTML. Si no se detecta,
ambos compiten por las posiciones del top-3 y desperdician dos de los tres
huecos con el mismo contenido.
"""

from __future__ import annotations

import hashlib
import logging

from parser.models import ParsedDocument

logger = logging.getLogger(__name__)


def calcular_hash(doc: ParsedDocument) -> str:
    """SHA-256 del texto normalizado de los bloques activos, concatenado."""
    normalizado = "\n".join(
        " ".join(b.texto.split()) for b in doc.bloques_activos()
    )
    return hashlib.sha256(normalizado.encode("utf-8")).hexdigest()


def deduplicar_documentos(
    docs: list[ParsedDocument],
) -> tuple[list[ParsedDocument], list[str]]:
    """Agrupa por hash_contenido y conserva el de MEJOR extraccion.

    Criterio de desempate, en orden: mas caracteres utiles tras el filtro de
    calidad; a igualdad, mas encabezados (mas estructura); a igualdad, el
    doc_id menor, para que el resultado sea determinista.

    Devuelve (documentos conservados, doc_ids eliminados).
    """
    por_hash: dict[str, list[ParsedDocument]] = {}
    sin_hash: list[ParsedDocument] = []
    for doc in docs:
        if doc.hash_contenido:
            por_hash.setdefault(doc.hash_contenido, []).append(doc)
        else:
            sin_hash.append(doc)

    conservados: list[ParsedDocument] = list(sin_hash)
    eliminados: list[str] = []
    for grupo in por_hash.values():
        if len(grupo) == 1:
            conservados.append(grupo[0])
            continue
        mejor = max(grupo, key=_calidad)
        conservados.append(mejor)
        for doc in grupo:
            if doc is not mejor:
                eliminados.append(doc.doc_id)
                logger.info(
                    "duplicado: %s (%s) eliminado en favor de %s (%s)",
                    doc.doc_id, doc.fuente, mejor.doc_id, mejor.fuente,
                )

    # Orden estable por doc_id: el pipeline debe ser reproducible.
    conservados.sort(key=lambda d: d.doc_id)
    return conservados, sorted(eliminados)


def _calidad(doc: ParsedDocument) -> tuple[int, int, str]:
    """Clave de desempate. El doc_id va negado via orden inverso del max()."""
    caracteres = sum(len(b.texto) for b in doc.bloques_activos())
    headings = sum(1 for b in doc.bloques_activos() if b.tipo == "heading")
    # doc_id invertido para que, a igualdad, gane el menor lexicograficamente.
    return caracteres, headings, _invertir(doc.doc_id)


def _invertir(doc_id: str) -> str:
    """Cadena que ordena al reves que doc_id, para usarla dentro de max()."""
    return "".join(chr(0x10FFFF - ord(c)) for c in doc_id)
```

### B.7 `parser/cleaning/pipeline.py`

```python
"""Orquestador de la limpieza. El orden de las operaciones es normativo."""

from __future__ import annotations

import logging

from parser.cleaning.boilerplate import detectar_repetidos, eliminar_repetidos
from parser.cleaning.dedup import calcular_hash, deduplicar_documentos
from parser.cleaning.dehyphen import unir_palabras_cortadas
from parser.cleaning.language import detectar_idioma, idioma_dominante
from parser.cleaning.normalize import (
    colapsar_espacios,
    normalizar_unicode,
    quitar_invisibles,
    reparar_mojibake,
)
from parser.cleaning.quality import evaluar_bloque
from parser.models import ParsedDocument

logger = logging.getLogger(__name__)


def limpiar_documento(doc: ParsedDocument) -> ParsedDocument:
    """Aplica la limpieza completa a un documento, in place.

    Al terminar, el campo `texto` de cada bloque queda CONGELADO: ningun
    proceso posterior debe modificarlo.
    """
    for bloque in doc.blocks:
        texto = reparar_mojibake(bloque.texto)
        texto = normalizar_unicode(texto)
        texto = quitar_invisibles(texto)
        if not bloque.ancla.get("es_codigo"):
            # En un bloque de codigo la sangria es significativa y las palabras
            # con guion al final de linea no son cortes de silabas.
            texto = unir_palabras_cortadas(texto)
            texto = colapsar_espacios(texto)
        else:
            texto = texto.strip("\n")
        bloque.texto = texto

    repetidos = detectar_repetidos(doc)
    eliminar_repetidos(doc, repetidos)

    for bloque in doc.blocks:
        if bloque.descartado:
            continue
        descartar, motivo = evaluar_bloque(bloque)
        if descartar:
            bloque.descartado = True
            bloque.motivo_descarte = motivo

    for bloque in doc.blocks:
        if not bloque.descartado:
            bloque.idioma = detectar_idioma(bloque.texto)
    doc.idioma = idioma_dominante(doc)

    doc.hash_contenido = calcular_hash(doc)
    return doc


def limpiar_corpus(
    docs: list[ParsedDocument],
) -> tuple[list[ParsedDocument], list[str]]:
    """Limpia todos los documentos y deduplica.

    DESVIACION del enunciado, que devolvia solo la lista: main.py y qa_report.py
    necesitan los doc_id eliminados para el informe, y recalcularlos despues
    obligaria a rehacer el agrupado por hash.
    """
    for indice, doc in enumerate(docs, start=1):
        limpiar_documento(doc)
        if indice % 100 == 0:
            logger.info("limpiados %d/%d documentos", indice, len(docs))
    return deduplicar_documentos(docs)
```

### B.8 Qué NO hacer en `cleaning/`

- Nada de stemming, lematización ni eliminación de stopwords: los encoders modernos los necesitan.
- No pasar a minúsculas.
- No traducir.
- No deduplicar a nivel de fragmento: eso ocurre después del chunking, con MinHash.

### B.9 Tests de `cleaning/`

`tests/test_cleaning_normalize.py`

| Test | Aserción |
|---|---|
| `test_mojibake_se_repara` | `"Ã³rbita"` → `"órbita"` |
| `test_mojibake_antes_de_nfkc` | Aplicar NFKC primero y luego ftfy **no** recupera el texto; el orden del pipeline sí |
| `test_nfkc_resuelve_ligaduras` | `"ﬁgura"` → `"figura"` |
| `test_zero_width_y_soft_hyphen_desaparecen` | `"a​b­c"` → `"abc"` |
| `test_nbsp_pasa_a_espacio_normal` | `"a b"` → `"a b"` |
| `test_control_c0_se_elimina_salvo_tab_y_salto` | `"a\x00b\tc\nd"` → `"ab\tc\nd"` |
| `test_espacios_multiples_se_colapsan` | `"a   b"` → `"a b"` |
| `test_doble_salto_se_preserva` | `"a\n\n\n\n\nb"` → `"a\n\n b"`… exactamente `"a\n\nb"` |
| `test_salto_simple_se_preserva` | `"a\nb"` → `"a\nb"` |

`tests/test_cleaning_dehyphen.py`

| Test | Aserción |
|---|---|
| `test_une_palabra_cortada` | `"informa-\nción"` → `"información"` |
| `test_no_une_si_la_siguiente_es_mayuscula` | `"Perú-\nColombia"` intacto |
| `test_no_une_si_el_prefijo_es_corto` | `"de-\nsierto"` intacto |
| `test_no_une_si_ambas_partes_existen_solas` | Texto que ya contiene `"casa"` y `"blanca"` sueltos |
| `test_el_vocabulario_ignora_las_propias_partes_cortadas` | Regresión: `"informa-\nción"` sin otras apariciones **sí** se une |
| `test_guion_a_mitad_de_linea_no_se_toca` | `"norte-sur"` intacto |

`tests/test_cleaning_quality.py`

| Test | Aserción |
|---|---|
| `test_bloque_corto_se_descarta` | 19 caracteres → `(True, "corto")` |
| `test_table_row_corto_tambien_se_descarta` | El mínimo sí aplica a los estructurados |
| `test_table_row_numerico_no_se_descarta` | `"anio: 2023 \| valor: 1200 \| pib: 3.4"` sobrevive |
| `test_feature_numerico_no_se_descarta` | Ídem con `tipo="feature"` |
| `test_paragraph_numerico_si_se_descarta` | El mismo texto como `paragraph` cae |
| `test_basura_de_ocr_se_descarta` | `"l a s e g u r i d a d e n o r b i t a"` → `"basura_ocr"` |

`tests/test_cleaning_boilerplate.py`

| Test | Aserción |
|---|---|
| `test_pie_repetido_en_muchas_paginas_se_descarta` | Bloque con `ancla["pagina"]` en 5 páginas → `motivo_descarte == "boilerplate"` |
| `test_linea_larga_no_es_boilerplate` | 120 caracteres repetidos sobreviven |
| `test_bloque_mixto_no_se_descarta` | Párrafo con una línea repetida y otra única sobrevive |
| `test_menos_de_cuatro_grupos_no_dispara` | Documento de 3 bloques: nada se descarta |
| `test_el_texto_no_se_modifica` | Solo se marca `descartado`, `texto` intacto |

`tests/test_cleaning_language.py`

| Test | Aserción |
|---|---|
| `test_detecta_espanol_e_ingles` | Dos párrafos largos, códigos `es` y `en` |
| `test_bloque_corto_devuelve_none` | 30 caracteres → `None` |
| `test_es_determinista` | Diez llamadas seguidas dan el mismo resultado |
| `test_idioma_dominante_pondera_por_caracteres` | Resumen corto en `es` + cuerpo largo en `en` → `en` |
| `test_documento_sin_idioma_detectable` | `idioma_dominante` → `None` |

`tests/test_cleaning_dedup.py`

| Test | Aserción |
|---|---|
| `test_hash_ignora_diferencias_de_espaciado` | Dos docs con distinto whitespace, mismo hash |
| `test_hash_ignora_bloques_descartados` | |
| `test_conserva_el_de_mas_caracteres_utiles` | No el primero |
| `test_desempate_por_numero_de_headings` | A igualdad de caracteres |
| `test_desempate_final_es_determinista` | A igualdad total, gana el `doc_id` menor, y repetir da lo mismo |
| `test_devuelve_los_doc_id_eliminados` | |

`tests/test_cleaning_pipeline.py`

| Test | Aserción |
|---|---|
| `test_orden_mojibake_antes_de_nfkc` | Bloque con `"Ã³"` acaba en `"ó"` |
| `test_dehyphen_antes_de_colapsar` | `"informa-\nción"` se une, y no queda un espacio suelto |
| `test_bloques_de_codigo_no_se_colapsan` | `ancla["es_codigo"]` conserva la sangría interna |
| `test_llena_idioma_y_hash` | Ambos dejan de ser `None` |
| `test_no_pasa_a_minusculas` | Las mayúsculas sobreviven |
| `test_texto_congelado` | Llamar dos veces a `limpiar_documento` no cambia el texto (idempotencia) |
| `test_limpiar_corpus_deduplica` | Dos docs idénticos → uno, y su id en la lista de eliminados |

---

## Parte C — `parser/selector.py`

```python
"""Registry de parsers y procesamiento por lote.

El descubrimiento es EXPLICITO (import + lista) y no por introspeccion: es mas
facil de depurar y hace evidente que parser cubre que extension.
"""

from __future__ import annotations

import logging
import traceback
from pathlib import Path

from parser.models import ErrorParseo, ParsedDocument
from parser.parsers.base import BaseParser
from parser.parsers.html_parser import HtmlParser
from parser.parsers.json_parser import JsonParser
from parser.parsers.tabular_parser import TabularParser
from parser.parsers.text_parser import TextParser

logger = logging.getLogger(__name__)

# El orden importa solo si dos parsers reclaman la misma extension; hoy no
# ocurre. Al anadir PdfParser, ImageParser y PbfParser, incluirlos aqui.
PARSERS: tuple[type[BaseParser], ...] = (
    TextParser,
    HtmlParser,
    JsonParser,
    TabularParser,
)

# Firmas de los primeros bytes, solo como RESPALDO cuando la extension no
# resuelve (archivos sin extension, .txt que en realidad son JSON).
_FIRMAS: tuple[tuple[bytes, str], ...] = (
    (b"%PDF-", ".pdf"),
    (b"PK\x03\x04", ".xlsx"),
    (b"\xd0\xcf\x11\xe0", ".xls"),
    (b"\x89PNG", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
)
_INTERVALO_LOG = 50


def obtener_parser(path: Path) -> BaseParser | None:
    """Primer parser cuyo puede_parsear() acepte la ruta, o None."""
    for clase in PARSERS:
        if clase.puede_parsear(path):
            return clase()
    extension = detectar_por_magic(path)
    if extension is not None:
        sustituta = path.with_suffix(extension)
        for clase in PARSERS:
            if clase.puede_parsear(sustituta):
                logger.info(
                    "%s: extension resuelta por contenido como %s",
                    path.name, extension,
                )
                return clase()
    return None


def detectar_por_magic(path: Path) -> str | None:
    """Extension deducida de los primeros bytes, o None.

    Respaldo, nunca la via principal: la extension del archivo manda.
    """
    try:
        cabecera = path.open("rb").read(512)
    except OSError:
        return None
    for firma, extension in _FIRMAS:
        if cabecera.startswith(firma):
            return extension
    texto = cabecera.lstrip()[:64].lower()
    if texto.startswith((b"<!doctype html", b"<html")):
        return ".html"
    if texto[:1] in (b"{", b"["):
        return ".json"
    return None


def asignar_doc_ids(
    rutas: list[Path], fenomeno_por_ruta: dict[Path, int], raiz: Path
) -> dict[Path, str]:
    """Mapa ruta -> doc_id, DETERMINISTA entre ejecuciones.

    Formato "DOC-{fenomeno}-{contador:05d}". Se ordena por ruta relativa a la
    raiz y con separadores normalizados, para que el resultado no dependa del
    orden que devuelva el sistema de archivos ni del sistema operativo.
    """
    ordenadas = sorted(rutas, key=lambda p: _clave_orden(p, raiz))
    contadores: dict[int, int] = {}
    mapa: dict[Path, str] = {}
    for ruta in ordenadas:
        fenomeno = fenomeno_por_ruta.get(ruta, 0)
        contadores[fenomeno] = contadores.get(fenomeno, 0) + 1
        mapa[ruta] = f"DOC-{fenomeno}-{contadores[fenomeno]:05d}"
    return mapa


def _clave_orden(ruta: Path, raiz: Path) -> str:
    """Ruta relativa con separadores POSIX, en minusculas solo para ordenar."""
    try:
        relativa = ruta.relative_to(raiz)
    except ValueError:
        relativa = ruta
    return relativa.as_posix().casefold()


def procesar_archivos(
    rutas: list[Path],
    fenomeno_por_ruta: dict[Path, int],
    raiz: Path,
    *,
    doc_ids: dict[Path, str] | None = None,
) -> tuple[list[ParsedDocument], list[ErrorParseo]]:
    """Parsea todos los archivos. Un fallo nunca detiene la ingesta."""
    mapa = doc_ids or asignar_doc_ids(rutas, fenomeno_por_ruta, raiz)
    documentos: list[ParsedDocument] = []
    errores: list[ErrorParseo] = []

    for indice, ruta in enumerate(sorted(rutas, key=lambda p: _clave_orden(p, raiz)), 1):
        if indice % _INTERVALO_LOG == 0:
            logger.info("procesados %d/%d archivos", indice, len(rutas))

        parser = obtener_parser(ruta)
        if parser is None:
            errores.append(
                ErrorParseo(
                    ruta=str(ruta),
                    formato=ruta.suffix.lower().lstrip("."),
                    excepcion="FormatoNoSoportado: sin parser para la extension",
                    traceback="",
                )
            )
            documentos.append(_placeholder(ruta, mapa[ruta], fenomeno_por_ruta, "sin parser"))
            continue

        doc, error = parser.parse_seguro(ruta, mapa[ruta], fenomeno_por_ruta.get(ruta, 0))
        if doc is not None:
            documentos.append(doc)
        else:
            assert error is not None
            errores.append(error)
            documentos.append(
                _placeholder(ruta, mapa[ruta], fenomeno_por_ruta, error.excepcion)
            )

    logger.info(
        "parseo terminado: %d documentos, %d errores", len(documentos), len(errores)
    )
    return documentos, errores


def _placeholder(
    ruta: Path, doc_id: str, fenomeno_por_ruta: dict[Path, int], motivo: str
) -> ParsedDocument:
    """Documento vacio para un archivo que no se pudo parsear.

    OBLIGATORIO: la evaluacion empareja por `fuente`, asi que TODO archivo del
    corpus debe aparecer en la salida. HtmlParser lanza ParserError con paginas
    vacias y sin este placeholder esos archivos desaparecerian del entregable.
    El placeholder no aporta texto, pero conserva la cobertura de `fuente`.
    """
    import os

    return ParsedDocument(
        doc_id=doc_id,
        fuente=ruta.name,
        formato=ruta.suffix.lower().lstrip(".") or "desconocido",
        fenomeno=fenomeno_por_ruta.get(ruta, 0),
        ruta_original=os.path.abspath(ruta),
        meta_extra={"placeholder": True, "motivo": motivo},
        errores=[f"archivo no parseado: {motivo}"],
    )
```

**Tests de `selector.py`:**

| Test | Aserción |
|---|---|
| `test_obtener_parser_por_extension` | Parametrizado: `.md`→TextParser, `.html`→HtmlParser, `.json`→JsonParser, `.csv`→TabularParser |
| `test_extension_no_soportada_devuelve_none` | `.pdf` hoy → `None` |
| `test_magic_detecta_json_con_extension_equivocada` | Un JSON llamado `datos.dat` |
| `test_magic_no_pisa_la_extension` | Un `.csv` cuyo contenido empieza por `{` sigue yendo a TabularParser |
| `test_doc_id_es_determinista` | Dos llamadas con las rutas en distinto orden dan el mismo mapa |
| `test_doc_id_formato` | `"DOC-2-00041"` |
| `test_doc_id_numera_por_fenomeno` | Los contadores son independientes |
| `test_un_archivo_corrupto_no_detiene_el_lote` | 3 archivos, uno roto → 3 documentos y 1 error |
| `test_archivo_fallido_produce_placeholder` | `meta_extra["placeholder"]` y `fuente` correcto |
| `test_todo_archivo_aparece_en_la_salida` | `{d.fuente for d in docs} == {p.name for p in rutas}` — **el test que protege el emparejamiento** |

---

## Parte D — `parser/main.py`

```python
"""Orquestador de la ingesta: recorre el corpus, parsea, limpia y serializa."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from tqdm import tqdm

from parser import qa_report, selector
from parser.cleaning.pipeline import limpiar_corpus
from parser.models import ErrorParseo, ParsedDocument

logger = logging.getLogger("parser.main")

NOMBRE_DOCUMENTOS = "documentos_parseados.jsonl"
NOMBRE_ERRORES = "errores_parseo.jsonl"
NOMBRE_MAPEO = "mapeo_docids.json"
NOMBRE_LOG = "ingesta.log"

# Se infiere el fenomeno de la carpeta: .../fenomeno_2/... o .../2/...
# SUPUESTO documentado: si no se puede inferir y no se pasa --fenomeno, se
# asigna 0, que qa_report reporta como aviso.
_PISTAS_FENOMENO = ("fenomeno", "fenómeno", "phenomenon", "tema")


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada de la ingesta."""
    args = _argumentos(argv)
    salida = Path(args.output)
    salida.mkdir(parents=True, exist_ok=True)
    _configurar_logging(salida / NOMBRE_LOG)

    raiz = Path(args.input)
    rutas = _recolectar(raiz, args.formatos, args.limite)
    if not rutas:
        logger.error("no se encontro ningun archivo bajo %s", raiz)
        return 1

    fenomeno_por_ruta = {r: _inferir_fenomeno(r, raiz, args.fenomeno) for r in rutas}
    if args.fenomeno is not None:
        rutas = [r for r in rutas if fenomeno_por_ruta[r] == args.fenomeno]

    doc_ids = selector.asignar_doc_ids(rutas, fenomeno_por_ruta, raiz)
    _volcar_json(salida / NOMBRE_MAPEO, {v: str(k) for k, v in doc_ids.items()})

    ya_hechos: set[str] = set()
    if args.resume:
        ya_hechos = _fuentes_existentes(salida / NOMBRE_DOCUMENTOS)
        if ya_hechos:
            logger.info("--resume: %d archivos ya procesados se omiten", len(ya_hechos))
            rutas = [r for r in rutas if r.name not in ya_hechos]

    documentos: list[ParsedDocument] = []
    errores: list[ErrorParseo] = []
    for ruta in tqdm(rutas, desc="parseando", unit="arch"):
        docs, errs = selector.procesar_archivos(
            [ruta], fenomeno_por_ruta, raiz, doc_ids=doc_ids
        )
        documentos.extend(docs)
        errores.extend(errs)

    logger.info("limpiando %d documentos", len(documentos))
    documentos, duplicados = limpiar_corpus(documentos)

    _volcar_jsonl(salida / NOMBRE_DOCUMENTOS, (d.to_dict() for d in documentos))
    _volcar_jsonl(salida / NOMBRE_ERRORES, (e.to_dict() for e in errores))

    estadisticas = qa_report.generar(documentos, errores, duplicados, salida)
    _resumen(estadisticas, duplicados)
    return 0


def _argumentos(argv: list[str] | None) -> argparse.Namespace:
    """CLI de la ingesta."""
    p = argparse.ArgumentParser(description="Ingesta del corpus ADL")
    p.add_argument("--input", required=True, help="directorio raiz del corpus")
    p.add_argument("--output", required=True, help="directorio de resultados")
    p.add_argument("--fenomeno", type=int, choices=(1, 2, 3), help="procesar solo uno")
    p.add_argument("--formatos", nargs="*", help="extensiones a procesar, ej: .pdf .html")
    p.add_argument("--limite", type=int, help="maximo de archivos, para pruebas")
    p.add_argument("--resume", action="store_true", help="omitir los ya procesados")
    return p.parse_args(argv)


def _configurar_logging(archivo: Path) -> None:
    """Logging simultaneo a consola y a archivo."""
    formato = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    consola = logging.StreamHandler(sys.stderr)
    consola.setFormatter(formato)
    fichero = logging.FileHandler(archivo, encoding="utf-8")
    fichero.setFormatter(formato)
    raiz = logging.getLogger()
    raiz.setLevel(logging.INFO)
    raiz.handlers = [consola, fichero]


def _recolectar(raiz: Path, formatos: list[str] | None, limite: int | None) -> list[Path]:
    """Rutas de archivo bajo la raiz, ordenadas para que el orden sea estable.

    Se usa rglob y no una concatenacion de nombres: `fuente` sale de path.name y
    tiene que ser el nombre REAL en disco, con su casing y sus acentos.
    """
    permitidas = {f.lower() if f.startswith(".") else f".{f.lower()}" for f in formatos or []}
    rutas = [p for p in raiz.rglob("*") if p.is_file()]
    if permitidas:
        rutas = [p for p in rutas if p.suffix.lower() in permitidas]
    rutas.sort(key=lambda p: p.relative_to(raiz).as_posix().casefold())
    return rutas[:limite] if limite else rutas


def _inferir_fenomeno(ruta: Path, raiz: Path, por_defecto: int | None) -> int:
    """Fenomeno deducido de la carpeta, o el valor explicito, o 0."""
    for parte in ruta.relative_to(raiz).parts[:-1]:
        limpia = parte.strip().lower()
        if limpia.isdigit() and limpia in ("1", "2", "3"):
            return int(limpia)
        for pista in _PISTAS_FENOMENO:
            if limpia.startswith(pista):
                digitos = "".join(c for c in limpia if c.isdigit())
                if digitos:
                    return int(digitos[0])
    return por_defecto if por_defecto is not None else 0


def _fuentes_existentes(archivo: Path) -> set[str]:
    """Nombres de archivo ya presentes en un jsonl previo."""
    if not archivo.exists():
        return set()
    fuentes = set()
    with archivo.open(encoding="utf-8") as fh:
        for linea in fh:
            if linea.strip():
                fuentes.add(json.loads(linea)["fuente"])
    return fuentes


def _volcar_jsonl(archivo: Path, registros) -> None:
    """Un objeto JSON por linea, UTF-8 sin escapar los acentos."""
    with archivo.open("w", encoding="utf-8", newline="\n") as fh:
        for registro in registros:
            fh.write(json.dumps(registro, ensure_ascii=False) + "\n")


def _volcar_json(archivo: Path, datos) -> None:
    """JSON indentado, con claves ordenadas para que el diff sea legible."""
    archivo.write_text(
        json.dumps(datos, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _resumen(estadisticas: dict, duplicados: list[str]) -> None:
    """Resumen final en consola."""
    logger.info("=" * 60)
    logger.info("archivos totales      : %d", estadisticas["total"])
    logger.info("parseados con exito   : %d", estadisticas["exitosos"])
    logger.info("fallidos              : %d", estadisticas["fallidos"])
    logger.info("duplicados eliminados : %d", len(duplicados))
    logger.info("bloques descartados   : %d", estadisticas["bloques_descartados"])
    for formato, datos in sorted(estadisticas["por_formato"].items()):
        logger.info(
            "  %-10s %4d archivos, %6d bloques, %8d palabras",
            formato, datos["archivos"], datos["bloques"], datos["palabras"],
        )
    logger.info("=" * 60)


if __name__ == "__main__":
    raise SystemExit(main())
```

> **`main.py` termina aquí.** No llama a chunking, ni a encoders, ni a FAISS.

**Tests de `main.py`** (`tests/test_main.py`): un end-to-end con `tmp_path` que crea `corpus/1/a.md`, `corpus/2/b.json`, `corpus/2/c.csv`, ejecuta `main(["--input", ..., "--output", ...])` y comprueba que se crean los cuatro archivos, que `documentos_parseados.jsonl` tiene una línea por archivo, que el round-trip `from_dict(json.loads(linea))` funciona, que los `doc_id` reflejan el fenómeno de la carpeta, y que `--limite 1` procesa uno solo.

---

## Parte E — `parser/qa_report.py`

```python
"""Validacion post-ingesta.

Descubrir un parser roto DESPUES de haber indexado el corpus completo cuesta
horas que no va a haber. Este modulo existe para que eso no pase.
"""

from __future__ import annotations

import logging
import random
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from parser.models import ErrorParseo, ParsedDocument

logger = logging.getLogger(__name__)

IDIOMAS_ESPERADOS = frozenset({"es", "en", "pt"})
UMBRAL_DESCARTE = 0.40
UMBRAL_IDIOMA_INESPERADO = 0.05
DOCS_MAS_CORTOS = 20
MUESTRAS_POR_FORMATO = 10
CARACTERES_MUESTRA = 500

NOMBRE_INFORME = "qa_report.md"
NOMBRE_MUESTREO = "qa_muestreo.md"


def generar(
    documentos: list[ParsedDocument],
    errores: list[ErrorParseo],
    duplicados: list[str],
    salida: Path,
    *,
    semilla: int = 0,
) -> dict[str, Any]:
    """Escribe el informe y devuelve las estadisticas como dict."""
    estadisticas = _estadisticas(documentos, errores, duplicados)
    _escribir_informe(salida / NOMBRE_INFORME, estadisticas, documentos, errores, duplicados)
    _escribir_muestreo(salida / NOMBRE_MUESTREO, documentos, semilla)
    _asserts(documentos)
    return estadisticas


def _estadisticas(
    documentos: list[ParsedDocument],
    errores: list[ErrorParseo],
    duplicados: list[str],
) -> dict[str, Any]:
    """Metricas agregadas de cobertura, volumen, idiomas y descartes."""
    por_formato: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"archivos": 0, "bloques": 0, "palabras": 0,
                 "descartados": 0, "placeholders": 0, "palabras_doc": []}
    )
    idiomas: Counter[str] = Counter()
    motivos: Counter[str] = Counter()

    for doc in documentos:
        datos = por_formato[doc.formato]
        datos["archivos"] += 1
        datos["bloques"] += len(doc.blocks)
        datos["palabras"] += doc.num_palabras()
        datos["palabras_doc"].append(doc.num_palabras())
        if doc.meta_extra.get("placeholder"):
            datos["placeholders"] += 1
        for bloque in doc.blocks:
            if bloque.descartado:
                datos["descartados"] += 1
                motivos[bloque.motivo_descarte or "sin_motivo"] += 1
            elif bloque.idioma:
                idiomas[bloque.idioma] += 1

    for datos in por_formato.values():
        muestras = datos.pop("palabras_doc")
        datos["media_palabras"] = round(statistics.fmean(muestras), 1) if muestras else 0
        datos["mediana_palabras"] = statistics.median(muestras) if muestras else 0
        total = datos["bloques"]
        datos["ratio_descarte"] = datos["descartados"] / total if total else 0.0

    fallidos = sum(1 for d in documentos if d.meta_extra.get("placeholder"))
    return {
        "total": len(documentos),
        "exitosos": len(documentos) - fallidos,
        "fallidos": fallidos,
        "errores": len(errores),
        "duplicados": len(duplicados),
        "bloques_descartados": sum(motivos.values()),
        "por_formato": dict(por_formato),
        "idiomas": dict(idiomas),
        "motivos_descarte": dict(motivos),
        "alertas": _alertas(por_formato, idiomas),
    }


def _alertas(por_formato: dict[str, dict[str, Any]], idiomas: Counter[str]) -> list[str]:
    """Avisos que casi siempre significan un parser roto, no un corpus raro."""
    alertas = []
    for formato, datos in sorted(por_formato.items()):
        if datos["ratio_descarte"] > UMBRAL_DESCARTE:
            alertas.append(
                f"{formato}: {datos['ratio_descarte']:.0%} de bloques descartados. "
                f"Con ese porcentaje lo probable es que el parser este mal, no los documentos."
            )
        if datos["archivos"] and datos["placeholders"] / datos["archivos"] > 0.2:
            alertas.append(
                f"{formato}: {datos['placeholders']} de {datos['archivos']} archivos "
                f"no se pudieron parsear."
            )
    total = sum(idiomas.values())
    for idioma, veces in idiomas.items():
        if idioma not in IDIOMAS_ESPERADOS and total and veces / total > UMBRAL_IDIOMA_INESPERADO:
            alertas.append(
                f"idioma inesperado '{idioma}' en {veces} bloques ({veces / total:.0%}). "
                f"Suele indicar mojibake o basura de OCR, no un documento en ese idioma."
            )
    return alertas


def _escribir_informe(
    archivo: Path,
    estadisticas: dict[str, Any],
    documentos: list[ParsedDocument],
    errores: list[ErrorParseo],
    duplicados: list[str],
) -> None:
    """Informe en Markdown."""
    lineas = ["# Informe de ingesta", ""]

    if estadisticas["alertas"]:
        lineas += ["## Alertas", ""]
        lineas += [f"- {a}" for a in estadisticas["alertas"]] + [""]

    lineas += ["## Cobertura", "",
               "| formato | archivos | con texto | fallidos | exito |",
               "|---|---:|---:|---:|---:|"]
    for formato, datos in sorted(estadisticas["por_formato"].items()):
        con_texto = datos["archivos"] - datos["placeholders"]
        exito = con_texto / datos["archivos"] if datos["archivos"] else 0
        lineas.append(
            f"| {formato} | {datos['archivos']} | {con_texto} | "
            f"{datos['placeholders']} | {exito:.0%} |"
        )

    lineas += ["", "## Volumen", "",
               "| formato | bloques | palabras | media | mediana |",
               "|---|---:|---:|---:|---:|"]
    for formato, datos in sorted(estadisticas["por_formato"].items()):
        lineas.append(
            f"| {formato} | {datos['bloques']} | {datos['palabras']} | "
            f"{datos['media_palabras']} | {datos['mediana_palabras']} |"
        )

    lineas += ["", f"### Los {DOCS_MAS_CORTOS} documentos con menos texto", "",
               "Los outliers bajos son casi siempre extracciones rotas, no documentos cortos.",
               "", "| doc_id | fuente | formato | caracteres |", "|---|---|---|---:|"]
    cortos = sorted(documentos, key=lambda d: len(d.texto_completo()))[:DOCS_MAS_CORTOS]
    for doc in cortos:
        lineas.append(
            f"| {doc.doc_id} | {doc.fuente} | {doc.formato} | {len(doc.texto_completo())} |"
        )

    lineas += ["", "## Idiomas", "", "| idioma | bloques |", "|---|---:|"]
    for idioma, veces in sorted(estadisticas["idiomas"].items(), key=lambda x: -x[1]):
        lineas.append(f"| {idioma} | {veces} |")

    lineas += ["", "## Descartes", "", "| motivo | bloques |", "|---|---:|"]
    for motivo, veces in sorted(estadisticas["motivos_descarte"].items(), key=lambda x: -x[1]):
        lineas.append(f"| {motivo} | {veces} |")

    lineas += ["", "## Duplicados eliminados", ""]
    lineas += [f"- {d}" for d in duplicados] or ["Ninguno."]

    lineas += ["", "## Errores de parseo", ""]
    for error in errores[:50]:
        lineas.append(f"- `{Path(error.ruta).name}` ({error.formato}): {error.excepcion}")
    if len(errores) > 50:
        lineas.append(f"- ... y {len(errores) - 50} mas en errores_parseo.jsonl")

    archivo.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    logger.info("informe escrito en %s", archivo)


def _escribir_muestreo(archivo: Path, documentos: list[ParsedDocument], semilla: int) -> None:
    """Volcado para revision humana.

    Sin esto, las estadisticas agregadas pueden ocultar un parser que produce
    texto sintacticamente valido pero semanticamente inutil.
    """
    aleatorio = random.Random(semilla)  # semilla fija: el muestreo es reproducible
    por_formato: dict[str, list[ParsedDocument]] = defaultdict(list)
    for doc in documentos:
        por_formato[doc.formato].append(doc)

    lineas = ["# Muestreo para revision manual", ""]
    for formato in sorted(por_formato):
        candidatos = sorted(por_formato[formato], key=lambda d: d.doc_id)
        muestra = aleatorio.sample(candidatos, min(MUESTRAS_POR_FORMATO, len(candidatos)))
        lineas += [f"## {formato}", ""]
        for doc in sorted(muestra, key=lambda d: d.doc_id):
            lineas += [
                f"### {doc.doc_id} — `{doc.fuente}`",
                f"titulo: {doc.titulo!r} · idioma: {doc.idioma} · bloques: {len(doc.blocks)}",
                "", "```", doc.texto_completo()[:CARACTERES_MUESTRA], "```", "",
            ]
    archivo.write_text("\n".join(lineas) + "\n", encoding="utf-8")


def _asserts(documentos: list[ParsedDocument]) -> None:
    """Fallar ruidosamente ante lo que invalida el entregable."""
    vistos: set[str] = set()
    for doc in documentos:
        if doc.doc_id in vistos:
            raise AssertionError(f"doc_id duplicado: {doc.doc_id}")
        vistos.add(doc.doc_id)

        if not doc.fuente:
            raise AssertionError(f"{doc.doc_id}: fuente vacia")
        if Path(doc.ruta_original).name != doc.fuente:
            raise AssertionError(
                f"{doc.doc_id}: fuente {doc.fuente!r} no coincide con "
                f"{Path(doc.ruta_original).name!r}"
            )
        if not Path(doc.ruta_original).is_file():
            raise AssertionError(f"{doc.doc_id}: {doc.ruta_original} no existe")

        for bloque in doc.bloques_activos():
            if not bloque.texto.strip():
                raise AssertionError(f"{doc.doc_id}: bloque activo con texto vacio")

        if not doc.bloques_activos() and not doc.meta_extra.get("placeholder"):
            raise AssertionError(f"{doc.doc_id} ({doc.fuente}): cero bloques activos")
```

> **Un assert que el enunciado pedía y hay que matizar.** «Algún documento tiene cero bloques activos» no puede fallar para los *placeholders*: por diseño no tienen texto, y son justo lo que garantiza la cobertura de `fuente`. El assert los exceptúa explícitamente.

**Tests de `qa_report.py`:** cada assert duro con su caso que lo dispara (`doc_id` duplicado, `fuente` vacía, `fuente` que no coincide con `ruta_original`, bloque activo vacío, documento sin bloques activos que no es placeholder), más que un placeholder **no** dispara el último, que las alertas saltan con >40 % de descarte y con un idioma inesperado por encima del 5 %, y que el muestreo es reproducible con la misma semilla.

---

## Parte F — Parsers pendientes

Los tres siguen las mismas reglas: heredan de `BaseParser`, usan `self._bloque`, no limpian, y llenan `fuente` con `path.name` exacto vía `_nuevo_documento`.

### F.1 `parsers/pdf_parser.py` — implementado

```python
class PdfParser(BaseParser):
    EXTENSIONES = (".pdf",)
    FORMATO = "pdf"
```

El parser implementado usa `PyMuPDF` y sigue este flujo:

1. **Texto y geometría.** `page.get_text("dict")` conserva bloques, líneas, spans y coordenadas.
2. **Columnas.** Agrupa bloques por separación horizontal y emite la columna izquierda de arriba abajo y luego la derecha. Registra `meta_extra["paginas_dos_columnas"]`.
3. **Cabeceras y pies.** Elimina líneas de los márgenes superior/inferior cuyo texto normalizado se repite en al menos tres páginas.
4. **Índices.** Si más del 40 % de las líneas de una página coincide con `r"\.{4,}\s*\d+\s*$"`, descarta la página.
5. **Tablas.** Usa `page.find_tables()` de PyMuPDF; cada fila se linealiza con **`tablas.linealizar_fila`** y se emite como `table_row`.
6. **Captions.** Detecta prefijos `Figura|Figure|Gráfico|Tabla|Table|Cuadro` con número y captions sin prefijo cercanos a imágenes.
7. **Encabezados.** Usa tamaño modal y negrita; asigna `nivel` por rangos de tamaño y actualiza la pila con **`secciones.empujar_seccion`**.
8. **Anclas y metadata.** Emite `bbox` como lista JSON-nativa y registra páginas, autor, fecha, descartes, columnas y presencia de tablas.

`titulo`: `doc.metadata["title"]` si no está vacía ni es un nombre de archivo → primer heading de nivel 1 → primera línea de la página 1.

`meta_extra`: `num_paginas`, `autor`, `fecha`, `paginas_descartadas`, `paginas_dos_columnas`, `tiene_tablas`.

No hacer aquí: de-hyphenation (es de `cleaning/dehyphen.py`), normalización Unicode, colapso de espacios ni OCR. Los PDF compuestos exclusivamente por imágenes no producen texto.

Criterios verificados: PDF a dos columnas, filtros de índices y cabeceras/pies, captions, niveles de heading, filas `table_row` y anclas JSON-nativas.

### F.2 `parsers/image_parser.py`

```python
class ImageParser(BaseParser):
    EXTENSIONES = (".png", ".jpg", ".jpeg", ".tiff", ".webp")
    FORMATO = "imagen"
```

**Bloqueado hasta instalar el binario `tesseract-ocr` con los paquetes `spa`, `eng` y `por`.** `pytesseract` es solo el envoltorio.

1. Preprocesado, en este orden: escala de grises → deskew (Hough o `minAreaRect`) → binarización Otsu → si el ancho < 1000 px, escalar ×2 con interpolación cúbica.
2. `pytesseract.image_to_data(lang="spa+eng+por", output_type=Output.DICT)`, no `image_to_string`: hace falta la confianza por palabra. Probar `--psm 3` y `--psm 6` y quedarse con la de mayor confianza media.
3. Filtro agresivo: descartar palabras con `conf < 60`; si la confianza media < 50 → `ParserError`; si el texto útil < 30 caracteres → `ParserError`. Una portada con un logo debe producir error, no texto basura.
4. Reconstruir líneas agrupando por `(block_num, par_num, line_num)`; un `Block` de tipo `ocr_text` por párrafo.
5. `meta_extra`: `ocr=True`, `confianza_media`, `psm_usado`. Permite excluir estos bloques con un post-filtro si degradan las métricas.

Prohibido: modelos de visión generativos y captioning.

### F.3 `parsers/pbf_parser.py`

```python
class PbfParser(BaseParser):
    EXTENSIONES = (".pbf",)
    FORMATO = "pbf"
```

1. **Discriminar el formato.** La extensión la comparten OSM PBF y Mapbox Vector Tile. Los OSM PBF llevan `"OSMHeader"` cerca del inicio; los MVT no. Elegir `osmium` o `mapbox_vector_tile`; si no se puede determinar → `ParserError`.
2. Recorrer capas y features leyendo sus tags.
3. **Deduplicación por zoom.** El mismo elemento aparece repetido en varios niveles; el pliego lo advierte. Clave: `(capa, feature_id)`, o `(capa, nombre, codigo_administrativo)` si no hay id estable. Conservar solo la aparición del zoom más alto, que trae los atributos más completos. Registrar cuántos se eliminaron en `meta_extra`.
4. **Filtrar atributos de renderizado**: `z_order`, `layer`, `render_*`, `__*`, `source_layer`, `osm_id` numérico suelto y cualquier clave que empiece por `@`. Conservar `name`, `name:*`, `admin_level`, `place`, `population`, `boundary`, códigos DANE y cualquier clave con contenido textual.
5. Serializar con **`tablas.linealizar_fila`** y emitir como `tipo="feature"` con `ancla={"capa": ..., "feature_id": ...}`.
6. **Descartar geometría pura**: un feature sin ningún atributo textual no es recuperable por consulta en lenguaje natural.

No procesar geometrías, ni áreas, ni centroides, ni convertir a GeoJSON.

### F.4 Registrarlos en `selector.py`

```python
PARSERS: tuple[type[BaseParser], ...] = (
    TextParser, HtmlParser, JsonParser, TabularParser,
    PdfParser, ImageParser, PbfParser,
)
```

---

## Parte G — Dependencias

Añadir a `requirements.txt`:

```
# --- Limpieza ---
ftfy>=6.2,<7
langdetect>=1.0.9,<2      # Python puro, perfiles incluidos. NO fasttext: su
                          # modelo lid.176 son 126 MB que hay que descargar, y
                          # eso choca con "sin dependencias de red".

# --- Orquestacion ---
tqdm>=4.66,<5

# --- PDF ---
pymupdf>=1.24,<2

# --- OCR de imagenes ---
pytesseract>=0.3.10,<0.4
Pillow>=10.4,<12
opencv-python>=4.10,<5

# --- Mapas ---
osmium>=4.0,<5
mapbox-vector-tile>=2.1,<3
```

Verificado el 2026-08-03 contra el `.venv` de este repo (CPython 3.13.0, Windows): **todas tienen rueda `cp313`**, incluidas `osmium` y `mapbox-vector-tile`. `langdetect` solo publica sdist, pero es Python puro y se instala sin compilador.

Sistema, aparte de pip: `tesseract-ocr` con `tesseract-ocr-spa`, `tesseract-ocr-eng` y `tesseract-ocr-por`.

Comprobación de que no se compila nada desde fuente:

```powershell
.\.venv\Scripts\python.exe -m pip download --only-binary=:all: --dest $env:TEMP\ruedas -r requirements.txt
```

---

## Parte H — Orden de ejecución y compuertas

| # | Paso | Compuerta |
|---|---|---|
| 0 | Baseline | `pytest -q` → **222 passed** |
| 1 | Parte A (`to_dict`/`from_dict`) + tests | round-trip exacto |
| 2 | `cleaning/` + tests | normalización, dehyphenation, calidad, boilerplate, idioma, hash y deduplicación |
| 3 | `selector.py` + tests | `{d.fuente} == {p.name}`: **ningún archivo desaparece** |
| 4 | `qa_report.py` + tests | cada assert duro con su caso |
| 5 | `main.py` + test end-to-end | los 4 archivos de salida, round-trip desde disco |
| 6 | `pbf_parser.py` | siguiente parser de formato |
| 7 | `image_parser.py` | requiere el binario de tesseract |

Verificación end-to-end una vez esté el paso 6:

```powershell
.\.venv\Scripts\python.exe -m parser.main --input ruta\al\corpus --output salida --limite 50
.\.venv\Scripts\python.exe -m pytest -q
```

Y después **leer `salida/qa_muestreo.md` a ojo**. Es el paso que ninguna métrica agregada sustituye: un parser puede producir texto sintácticamente impecable y semánticamente inútil, y eso solo se ve leyéndolo.

---

## Parte I — Decisiones abiertas

1. **Campo `formato`.** La Tabla 1 del pliego lo restringe a `pdf|html|md`, pero el corpus trae json, csv, xlsx, pbf e imágenes. Provisional: `formato` guarda el real y `formato_pliego()` mapea, con `md` de cajón de sastre en `_MAPA_PLIEGO`. **Pendiente de confirmar.**
2. **Granularidad del `doc_id` en JSON multi-artículo.** Si el ground truth marca artículos individuales, un `doc_id` por archivo hunde el F1@3. El diseño ya guarda `ancla["registro_id"]`, así que se puede explotar a un doc_id por registro reagrupando en `selector.py`, sin tocar `json_parser`. **Pendiente de confirmar.**
3. **Arquitectura del encoder.** ¿Se admiten embeddings con backbone decoder (familia Qwen3-Embedding) o §4.2 restringe a arquitecturas tipo BERT? No afecta a esta etapa, pero sí a la siguiente.
4. **`slots=True` en las dataclasses.** Descartado por ahora; reevaluar en la etapa del PDF parser, que es donde explota el número de bloques.
