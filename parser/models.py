"""Modelos de la representacion intermedia del pipeline de parseo.

Los parsers EXTRAEN y ESTRUCTURAN; la limpieza (NFKC, colapso de espacios,
deteccion de idioma, de-hyphenation) es responsabilidad de la capa cleaning/
posterior. Un parser nunca debe llenar `idioma`, `hash_contenido` ni
`descartado`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, get_args

TipoBloque = Literal[
    "heading",
    "paragraph",
    "table_row",
    "caption",
    "list_item",
    "cell",
    "ocr_text",
    "feature",
]
TIPOS_BLOQUE: frozenset[str] = frozenset(get_args(TipoBloque))
# Esta version debe actualizarse cada vez que se actualice el esquema de parseo.
SCHEMA_VERSION = 1
# El pliego (Tabla 1) restringe el formato a pdf|html|md, pero el corpus real
# incluye json, csv, xlsx, pbf e imagenes. Decision provisional: `formato`
# guarda el formato REAL y formato_pliego() mapea al conjunto permitido cuando
# haya que emitir la metadata final.
# TODO(pliego): confirmar el mapeo con la organizacion del reto.
FORMATOS_PLIEGO: frozenset[str] = frozenset({"pdf", "html", "md"})
_MAPA_PLIEGO: dict[str, str] = {
    "pdf": "pdf",
    "html": "html",
    "htm": "html",
    "xml": "html",
    "md": "md",
    "markdown": "md",
    "txt": "md",
    "json": "md",
    "jsonl": "md",
    "csv": "md",
    "tsv": "md",
    "xlsx": "md",
    "xls": "md",
    "imagen": "md",
    "pbf": "md",
}
_FORMATO_PLIEGO_POR_DEFECTO = "md"
_JSON_ESCALARES = (str, int, float, bool, type(None))


def _validar_json_nativo(valor: Any, ruta: str) -> None:
    """Valida que un valor use solo tipos JSON nativos del esquema."""
    if isinstance(valor, _JSON_ESCALARES):
        return
    if isinstance(valor, list):
        for indice, item in enumerate(valor):
            _validar_json_nativo(item, f"{ruta}[{indice}]")
        return
    if isinstance(valor, dict):
        for clave, item in valor.items():
            if not isinstance(clave, str):
                raise TypeError(f"{ruta} contiene una clave no str: {clave!r}")
            _validar_json_nativo(item, f"{ruta}.{clave}")
        return
    raise TypeError(f"{ruta} no es JSON-nativo: {type(valor).__name__}")


@dataclass
class Block:
    """Unidad estructural del documento."""

    tipo: TipoBloque
    texto: str
    # Nivel de encabezado (1-6). Solo para tipo="heading"; None en el resto.
    nivel: int | None = None
    # Trazabilidad al origen; claves libres segun formato.
    #   PDF   -> {"pagina": 12, "bbox": [x0, y0, x1, y1]}
    #   HTML  -> {"xpath": "/html/body/div[2]/p[5]"}
    #   XLSX  -> {"hoja": "Data", "fila": 340}
    #   texto -> {"linea": 41, "linea_fin": 43}
    ancla: dict[str, Any] = field(default_factory=dict)
    # ISO 639-1. Lo llena cleaning; el parser lo deja en None.
    idioma: str | None = None
    # Ruta de encabezados ANCESTROS. Nunca incluye el texto del propio bloque,
    # tampoco cuando el bloque es un heading.
    seccion_path: list[str] = field(default_factory=list)
    descartado: bool = False
    motivo_descarte: str | None = None

    def __post_init__(self) -> None:
        """Válida el tipo en runtime (un Literal no se comprueba solo)."""
        if self.tipo not in TIPOS_BLOQUE:
            raise ValueError(f"tipo de bloque no permitido: {self.tipo!r}")
    def to_dict(self) -> dict[str, Any]:
        """Serializa el bloque a un dict JSON-nativo."""
        _validar_json_nativo(self.ancla, "Block.ancla")
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


@dataclass(kw_only=True)
class ParsedDocument:
    """Representacion intermedia de un documento parseado.

    kw_only=True: se construye en un unico sitio (BaseParser._nuevo_documento),
    asi que la ergonomia posicional no aporta nada, y evita intercambiar por
    error doc_id/fuente/formato/ruta_original, que son los cuatro str.
    """

    doc_id: str
    # CRITICO: nombre EXACTO del archivo original (path.name), sin lower(),
    # sin strip, sin normalizacion Unicode. Clave de emparejamiento del reto.
    fuente: str
    # Formato real: pdf|html|md|txt|json|csv|xlsx|imagen|pbf
    formato: str
    fenomeno: int
    ruta_original: str

    titulo: str | None = None
    idioma: str | None = None  # dominante; lo llena cleaning
    hash_contenido: str | None = None  # SHA-256; lo llena cleaning
    meta_extra: dict[str, Any] = field(default_factory=dict)
    errores: list[str] = field(default_factory=list)

    blocks: list[Block] = field(default_factory=list)

    def bloques_activos(self) -> list[Block]:
        """Bloques no descartados, en orden de lectura."""
        return [b for b in self.blocks if not b.descartado]

    def texto_completo(self) -> str:
        """Texto de los bloques activos unido por linea en blanco."""
        return "\n\n".join(b.texto for b in self.bloques_activos())

    def num_palabras(self) -> int:
        """Palabras aproximadas del texto activo (split por espacios)."""
        return len(self.texto_completo().split())

    def formato_pliego(self) -> str:
        """Mapea el formato real al conjunto pdf|html|md que exige el pliego."""
        return _MAPA_PLIEGO.get(self.formato, _FORMATO_PLIEGO_POR_DEFECTO)

    def to_dict(self) -> dict[str, Any]:
        """Serializa el documento a un dict JSON-nativo."""
        _validar_json_nativo(self.meta_extra, "ParsedDocument.meta_extra")
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
            "blocks": [bloque.to_dict() for bloque in self.blocks],
        }

    @classmethod
    def from_dict(cls, datos: dict[str, Any]) -> ParsedDocument:
        """Reconstruye un documento producido por to_dict()."""
        datos = dict(datos)
        version = datos.pop("schema_version", None)
        if version != SCHEMA_VERSION:
            raise ValueError(
                f"schema_version no soportado: {version!r}; "
                f"esperado: {SCHEMA_VERSION}"
            )
        datos["blocks"] = [Block.from_dict(bloque) for bloque in datos.get("blocks", [])]
        return cls(**datos)


@dataclass
class ErrorParseo:
    """Registro de un fallo aislado al parsear un archivo. El pipeline sigue.

    Es un REGISTRO de datos, no una excepcion: la excepcion es
    parsers.base.ParserError. (En el documento del reto figura como
    `ParseError`; renombrado para no colisionar con `ParserError`.)
    """

    ruta: str
    formato: str
    excepcion: str
    traceback: str

    def to_dict(self) -> dict[str, str]:
        """Serializa el fallo de parseo para logs o reportes JSON."""
        return {
            "ruta": self.ruta,
            "formato": self.formato,
            "excepcion": self.excepcion,
            "traceback": self.traceback,
        }

    @classmethod
    def from_dict(cls, datos: dict[str, str]) -> ErrorParseo:
        """Reconstruye un fallo de parseo producido por to_dict()."""
        return cls(**datos)
