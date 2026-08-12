"""Parser OCR para imagenes con texto visible."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image
import pytesseract
from pytesseract import Output

from parser.models import Block, ParsedDocument
from parser.parsers.base import BaseParser, ParserError


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
        imagen = Image.open(path)
        procesada = self._preprocesar(imagen)

        resultados = [self._ocr(procesada, psm) for psm in self.PSMS]
        resultado = max(resultados, key=lambda item: item[0])
        confianza, psm, palabras = resultado

        texto_util = " ".join(palabra["texto"] for palabra in palabras)
        if confianza < self.CONFIANZA_MEDIA_MINIMA or len(texto_util) < self.CARACTERES_MINIMOS:
            raise ParserError(
                f"OCR insuficiente en {path.name}: "
                f"confianza={confianza:.1f}, caracteres={len(texto_util)}"
            )

        doc.blocks = self._bloques(palabras)
        if not doc.blocks:
            raise ParserError(f"OCR sin bloques utilizables en {path.name}")

        doc.meta_extra.update(
            {
                "ocr": True,
                "confianza_media": confianza,
                "psm_usado": psm,
            }
        )
        return doc

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
