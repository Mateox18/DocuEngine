"""Parser OCR para imagenes con texto visible."""

from __future__ import annotations

from collections import defaultdict
import os
from pathlib import Path
import shutil
from typing import Any

import cv2
import numpy as np
from PIL import Image
import pytesseract
from pytesseract import Output

from lib.parser.models import Block, ParsedDocument
from lib.parser.parsers.base import BaseParser, ParserError


def _configurar_tesseract() -> None:
    """Encuentra Tesseract en PATH, variable de entorno o rutas Windows comunes."""
    candidatos = [
        os.getenv("TESSERACT_CMD"),
        shutil.which("tesseract"),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for candidato in candidatos:
        if candidato and Path(candidato).is_file():
            pytesseract.pytesseract.tesseract_cmd = str(candidato)
            return


_configurar_tesseract()


class ImageParser(BaseParser):
    """Extrae texto de imagenes mediante Tesseract OCR."""

    EXTENSIONES = (".png", ".jpg", ".jpeg", ".tiff", ".webp", ".avif")
    FORMATO = "imagen"
    IDIOMAS = "spa+eng+por"
    PSMS = (3, 6)
    CONFIANZA_MINIMA = 60.0
    CONFIANZA_MEDIA_MINIMA = 50.0
    CARACTERES_MINIMOS = 30

    def parse(self, path: Path, doc_id: str, fenomeno: int) -> ParsedDocument:
        doc = self._nuevo_documento(path, doc_id, fenomeno)
        with Image.open(path) as imagen:
            doc.blocks, confianza, psm = self.extraer_ocr(imagen)

        doc.meta_extra.update(
            {
                "ocr": True,
                "confianza_media": confianza,
                "psm_usado": psm,
            }
        )
        return doc

    def extraer_ocr(
        self,
        imagen: Image.Image,
        *,
        pagina: int | None = None,
        escala: float = 1.0,
        psms: tuple[int, ...] | None = None,
    ) -> tuple[list[Block], float, int]:
        """Extrae OCR reutilizable por imagenes independientes y PDF."""
        procesada = self._preprocesar(imagen)
        modos = self.PSMS if psms is None else psms
        resultados = [self._ocr(procesada, psm) for psm in modos]
        confianza, psm, palabras = max(resultados, key=lambda item: item[0])
        texto_util = " ".join(palabra["texto"] for palabra in palabras)
        if (
            confianza < self.CONFIANZA_MEDIA_MINIMA
            or len(texto_util) < self.CARACTERES_MINIMOS
        ):
            contexto = f" en página {pagina}" if pagina is not None else ""
            raise ParserError(
                f"OCR insuficiente{contexto}: "
                f"confianza={confianza:.1f}, caracteres={len(texto_util)}"
            )

        bloques = self._bloques(palabras)
        if not bloques:
            raise ParserError("OCR sin bloques utilizables")

        for bloque in bloques:
            bloque.ancla["ocr"] = True
            if pagina is not None:
                bloque.ancla["pagina"] = pagina
            if escala != 1.0:
                x0, y0, x1, y1 = bloque.ancla["bbox"]
                bloque.ancla["bbox"] = [
                    x0 / escala,
                    y0 / escala,
                    x1 / escala,
                    y1 / escala,
                ]
        return bloques, confianza, psm

    @staticmethod
    def _preprocesar(imagen: Image.Image) -> np.ndarray:
        """Gris, deskew, Otsu y escalado de imagenes pequenas."""
        gris = np.array(imagen.convert("L"))
        _, referencia = cv2.threshold(
            gris, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )

        puntos = cv2.findNonZero(255 - referencia)
        if puntos is not None and len(puntos) > 20:
            angulo = cv2.minAreaRect(puntos)[-1]
            if angulo < -45:
                angulo += 90
            if abs(angulo) > 0.2:
                alto, ancho = gris.shape[:2]
                centro = (ancho / 2, alto / 2)
                matriz = cv2.getRotationMatrix2D(centro, angulo, 1.0)
                gris = cv2.warpAffine(
                    gris,
                    matriz,
                    (ancho, alto),
                    flags=cv2.INTER_CUBIC,
                    borderMode=cv2.BORDER_CONSTANT,
                    borderValue=255,
                )

        _, binaria = cv2.threshold(
            gris, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )
        if binaria.shape[1] < 1000:
            binaria = cv2.resize(
                binaria,
                None,
                fx=2,
                fy=2,
                interpolation=cv2.INTER_CUBIC,
            )
        return binaria

    def _ocr(
        self, imagen: np.ndarray, psm: int
    ) -> tuple[float, int, list[dict[str, Any]]]:
        datos = pytesseract.image_to_data(
            imagen,
            lang=self.IDIOMAS,
            config=f"--psm {psm}",
            output_type=Output.DICT,
        )
        palabras: list[dict[str, Any]] = []
        confianzas: list[float] = []
        for indice, crudo in enumerate(datos.get("conf", [])):
            try:
                confianza = float(crudo)
            except (TypeError, ValueError):
                continue
            texto = str(datos.get("text", [""])[indice]).strip()
            if not texto or confianza < self.CONFIANZA_MINIMA:
                continue
            confianzas.append(confianza)
            palabras.append(
                {
                    "texto": texto,
                    "confianza": confianza,
                    "block_num": int(datos["block_num"][indice]),
                    "par_num": int(datos["par_num"][indice]),
                    "line_num": int(datos["line_num"][indice]),
                    "word_num": int(datos["word_num"][indice]),
                    "left": int(datos["left"][indice]),
                    "top": int(datos["top"][indice]),
                    "width": int(datos["width"][indice]),
                    "height": int(datos["height"][indice]),
                }
            )
        media = sum(confianzas) / len(confianzas) if confianzas else 0.0
        return media, psm, palabras

    def _bloques(self, palabras: list[dict[str, Any]]) -> list[Block]:
        grupos: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
        for palabra in palabras:
            grupos[(palabra["block_num"], palabra["par_num"])].append(palabra)

        bloques: list[Block] = []
        for grupo in grupos.values():
            grupo.sort(key=lambda palabra: (palabra["line_num"], palabra["word_num"]))
            por_linea: dict[int, list[dict[str, Any]]] = defaultdict(list)
            for palabra in grupo:
                por_linea[palabra["line_num"]].append(palabra)
            lineas = [
                " ".join(palabra["texto"] for palabra in palabras_linea)
                for _, palabras_linea in sorted(por_linea.items())
            ]
            x0 = min(palabra["left"] for palabra in grupo)
            y0 = min(palabra["top"] for palabra in grupo)
            x1 = max(palabra["left"] + palabra["width"] for palabra in grupo)
            y1 = max(palabra["top"] + palabra["height"] for palabra in grupo)
            confianza = sum(p["confianza"] for p in grupo) / len(grupo)
            bloques.append(
                self._bloque(
                    "ocr_text",
                    "\n".join(lineas),
                    ancla={"bbox": [x0, y0, x1, y1], "confianza": confianza},
                )
            )
        return bloques
