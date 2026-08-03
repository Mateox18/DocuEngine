"""Contrato base que deben cumplir todos los parsers de formato.

REGLA CLAVE: los parsers extraen y estructuran; NO limpian. Nada de
normalizacion Unicode, colapso de espacios, deteccion de idioma ni eliminacion
de cabeceras por repeticion: eso es de cleaning/. La unica "limpieza" permitida
es la inherente al formato (quitar etiquetas HTML, ignorar elementos
decorativos de PDF, descartar claves de renderizado en PBF).
"""

from __future__ import annotations

import logging
import os
import traceback
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar

from parser.models import Block, ErrorParseo, ParsedDocument, TipoBloque

logger = logging.getLogger(__name__)


class ParserError(Exception):
    """Error irrecuperable al parsear un archivo concreto."""


class BaseParser(ABC):
    """Interfaz comun de los parsers por formato."""

    # Extensiones soportadas, en minusculas y con punto. Ej: (".pdf",)
    EXTENSIONES: ClassVar[tuple[str, ...]] = ()
    # Formato canonico que produce este parser. Ej: "pdf"
    FORMATO: ClassVar[str] = ""
    # Override por extension cuando un parser cubre varios formatos reales.
    # Ej: TextParser -> {".txt": "txt"}, con ".md"/".markdown" via FORMATO.
    MAPA_FORMATOS: ClassVar[dict[str, str]] = {}

    def __init__(self) -> None:
        self.logger = logging.getLogger(
            f"{type(self).__module__}.{type(self).__name__}"
        )

    @classmethod
    def puede_parsear(cls, path: Path) -> bool:
        """True si la extension (en minusculas) esta declarada en EXTENSIONES."""
        return path.suffix.lower() in cls.EXTENSIONES

    @classmethod
    def formato_para(cls, path: Path) -> str:
        """Formato real de este archivo segun su extension."""
        return cls.MAPA_FORMATOS.get(path.suffix.lower(), cls.FORMATO)

    @abstractmethod
    def parse(self, path: Path, doc_id: str, fenomeno: int) -> ParsedDocument:
        """Parsea un archivo y devuelve su representacion intermedia.

        Debe llenar: doc_id, fuente, formato, fenomeno, ruta_original, blocks.
        Puede llenar: titulo, meta_extra, errores.
        NO debe llenar: idioma, hash_contenido, descartado (son de cleaning).
        Lanza ParserError si el archivo es irrecuperable.
        """

    def parse_seguro(
        self, path: Path, doc_id: str, fenomeno: int
    ) -> tuple[ParsedDocument | None, ErrorParseo | None]:
        """Igual que parse() pero aisla el fallo en un ErrorParseo.

        Es el punto donde se materializa la regla "un archivo que revienta no
        detiene la ingesta". El selector lo llama en bucle.
        """
        try:
            return self.parse(path, doc_id, fenomeno), None
        except Exception as exc:  # noqa: BLE001 - aislamiento deliberado
            self.logger.exception("fallo al parsear %s", path)
            return None, ErrorParseo(
                ruta=str(path),
                formato=self.formato_para(path),
                excepcion=f"{type(exc).__name__}: {exc}",
                traceback=traceback.format_exc(),
            )

    def _nuevo_documento(
        self, path: Path, doc_id: str, fenomeno: int
    ) -> ParsedDocument:
        """Construye el ParsedDocument con la metadata base ya llena."""
        if not path.is_file():
            raise ParserError(f"no existe o no es un archivo: {path}")
        if not self.puede_parsear(path):
            raise ParserError(
                f"{type(self).__name__} no soporta la extension {path.suffix!r}"
            )
        return ParsedDocument(
            doc_id=doc_id,
            # CRITICO: nombre exacto del archivo. Sin lower(), sin strip(),
            # sin normalizacion Unicode. Es la clave de emparejamiento.
            fuente=path.name,
            formato=self.formato_para(path),
            fenomeno=fenomeno,
            # abspath() NO toca el filesystem: no resuelve symlinks ni reescribe
            # el casing real de Windows. resolve() si, y podria alterar el
            # nombre; por eso abspath.
            ruta_original=os.path.abspath(path),
        )

    def _bloque(
        self,
        tipo: TipoBloque,
        texto: str,
        *,
        nivel: int | None = None,
        ancla: dict[str, Any] | None = None,
        seccion_path: list[str] | None = None,
    ) -> Block:
        """Crea un Block copiando ancla y seccion_path.

        La copia no es cosmetica: los parsers pasan aqui la pila viva de
        secciones, y sin copiar todos los bloques compartirian la misma lista
        y cada pop() los corromperia retroactivamente.
        """
        return Block(
            tipo=tipo,
            texto=texto,
            nivel=nivel,
            ancla=dict(ancla) if ancla else {},
            seccion_path=list(seccion_path) if seccion_path else [],
        )
