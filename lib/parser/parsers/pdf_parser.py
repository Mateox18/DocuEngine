"""Parser de PDF basado en PyMuPDF.

Extrae texto con coordenadas y lo convierte en bloques semanticos
(`paragraph`, `heading`, `caption` y `table_row`). Conserva la trazabilidad de
pagina y `bbox`, ordena documentos de una o dos columnas y registra metadata
estructural del PDF.

La limpieza linguistica pertenece a `lib.parser.cleaning` y no se realiza aqui.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import re
import unicodedata

import fitz
from PIL import Image

from lib.parser.models import Block, ParsedDocument, BBox, TipoBloque, TIPOS_BLOQUE
from lib.parser.parsers.base import BaseParser
from lib.parser.parsers.image_parser import ImageParser
from lib.parser.parsers.secciones import empujar_seccion
from lib.parser.parsers.tablas import linealizar_fila, nombrar_cabeceras

_RE_CAPTION = re.compile(
    r"^(figura|figure|gráfico|grafico|tabla|table|cuadro)\s+\d+",
    re.IGNORECASE,
)
_RE_INDEX = re.compile(r"\.{4,}\s*\d+\s*$")

class PdfParser(BaseParser):
    """Extrae y estructura documentos PDF usando PyMuPDF.

    El parser clasifica lineas por texto y tipografia, detecta captions
    cercanos a imagenes, identifica tablas con `Page.find_tables()` y elimina
    cabeceras, pies e indices repetitivos segun su geometria.
    """

    EXTENSIONES = (".pdf",)
    FORMATO = "pdf"
    def parse(self, path: Path, doc_id: str, fenomeno: int) -> ParsedDocument:
        """Parsea un PDF y devuelve su representacion intermedia.

        El flujo por pagina es: extraer bloques y tablas, descartar paginas de
        indice, filtrar cabeceras y pies repetidos, ordenar columnas, clasificar
        lineas y emitir bloques con anclas JSON-nativas.

        Args:
            path: Ruta al archivo .pdf
            doc_id: Identificador único del documento.
            fenomeno: Fenómeno asociado al documento.

        Returns:
            ParsedDocument: Documento con bloques, titulo y metadata de PDF.

        Las paginas con menos de 30 caracteres de texto intentan OCR como
        fallback; las paginas normales siguen usando la extraccion nativa.
        """
        with fitz.open(path) as pdf:
            doc = self._nuevo_documento(path, doc_id, fenomeno)
            pdf_blocks: list[PdfBlock] = []
            ocr_por_pagina: dict[int, list[Block]] = {}
            confianza_ocr: dict[str, float] = {}
            psm_ocr: dict[str, int] = {}
            paginas: list[dict] = []
            tablas_por_pagina: dict[int, list[PdfTable]] = {}
            pesos_tamanio: Counter[float] = Counter()
            for numero_pagina, page in enumerate(pdf, start=1):
                contenido = page.get_text("dict")
                tablas_por_pagina[numero_pagina] = self._extraer_tablas(page)
                paginas.append({
                    "numero": numero_pagina,
                    "alto": float(page.rect.height),
                    "contenido": contenido,
                })
                imagenes = [
                    BBox(*bloque["bbox"])
                    for bloque in contenido["blocks"]
                    if bloque.get("type") == 1 and "bbox" in bloque
                ]
                for bloque in contenido["blocks"]:
                    pdf_block = self._extraer_bloque(
                        bloque,
                        numero_pagina,
                        pesos_tamanio,
                        imagenes,
                    )
                    if pdf_block is not None:
                        pdf_blocks.append(pdf_block)
                if len(self._texto_de_dict(contenido).strip()) < 30:
                    try:
                        bloques_ocr, confianza, psm = self._ocr_pagina(
                            page,
                            numero_pagina,
                        )
                    except Exception as exc:  # OCR es un fallback no fatal
                        self.logger.warning(
                            "OCR omitido en %s página %d: %s",
                            path,
                            numero_pagina,
                            exc,
                        )
                    else:
                        ocr_por_pagina[numero_pagina] = bloques_ocr
                        confianza_ocr[str(numero_pagina)] = confianza
                        psm_ocr[str(numero_pagina)] = psm

            paginas_descartadas = self._paginas_de_indice(paginas)
            repetidos = self._cabeceras_pies_repetidos(pdf_blocks, paginas)
            pdf_blocks = [
                bloque_filtrado
                for bloque in pdf_blocks
                if bloque.pagina not in paginas_descartadas
                for bloque_filtrado in [
                    self._filtrar_bloque(bloque, repetidos, paginas)
                ]
                if bloque_filtrado is not None
            ]

            # Indexar una vez los bloques por pagina evita recorrer todos los
            # bloques del PDF para cada pagina durante la emision final.
            bloques_por_pagina: dict[int, list[PdfBlock]] = {}
            for bloque in pdf_blocks:
                bloques_por_pagina.setdefault(bloque.pagina, []).append(bloque)

            tamanio_normal = (
                pesos_tamanio.most_common(1)[0][0]
                if pesos_tamanio
                else None
            )

            niveles = self._niveles_heading(pdf_blocks, tamanio_normal)
            pila: list[tuple[int, str]] = []
            paginas_dos_columnas: list[int] = []
            for pagina in paginas:
                bloques = bloques_por_pagina.get(pagina["numero"], [])
                bloques, dos_columnas = self._ordenar_bloques(bloques)
                if dos_columnas:
                    paginas_dos_columnas.append(pagina["numero"])
                for pdf_block in bloques:
                    self._emitir_bloques(
                        doc, pdf_block, tamanio_normal, niveles, pila
                    )
                doc.blocks.extend(ocr_por_pagina.get(pagina["numero"], []))
                for tabla in tablas_por_pagina.get(pagina["numero"], []):
                    self._emitir_tabla(doc, tabla, pila)

            doc.meta_extra.update({
                "num_paginas": len(pdf),
                "autor": pdf.metadata.get("author") or None,
                "fecha": pdf.metadata.get("creationDate") or None,
                "paginas_descartadas": sorted(paginas_descartadas),
                "paginas_dos_columnas": paginas_dos_columnas,
                "tiene_tablas": any(tablas_por_pagina.values()),
            })
            if ocr_por_pagina:
                doc.meta_extra["paginas_ocr"] = sorted(ocr_por_pagina)
                doc.meta_extra["confianza_ocr"] = confianza_ocr
                doc.meta_extra["psm_ocr"] = psm_ocr
            titulo = pdf.metadata.get("title") or ""
            if not titulo or titulo.casefold() == path.name.casefold():
                headings = [b.texto for b in doc.blocks if b.tipo == "heading"]
                titulo = headings[0] if headings else (
                    doc.blocks[0].texto if doc.blocks else ""
                )
            doc.titulo = titulo or None

            return doc

    @staticmethod
    def _texto_de_dict(contenido: dict) -> str:
        """Reconstruye el texto visible sin repetir otra extracción de la página."""
        lineas: list[str] = []
        for bloque in contenido.get("blocks", []):
            if bloque.get("type") != 0:
                continue
            for linea in bloque.get("lines", []):
                texto = "".join(
                    str(span.get("text", ""))
                    for span in linea.get("spans", [])
                )
                if texto:
                    lineas.append(texto)
        return "\n".join(lineas)

    def _ocr_pagina(
        self,
        page: fitz.Page,
        numero_pagina: int,
    ) -> tuple[list[Block], float, int]:
        """Renderiza una página y delega su OCR a ImageParser."""
        # 1.5 equivale aproximadamente a 108 DPI para una pagina PDF normal:
        # conserva legibilidad para OCR y reduce memoria/tiempo frente a 2.0.
        escala = 1.5
        pixmap = page.get_pixmap(
            matrix=fitz.Matrix(escala, escala),
            alpha=False,
        )
        imagen = Image.frombytes(
            "RGB",
            (pixmap.width, pixmap.height),
            pixmap.samples,
        )
        return ImageParser().extraer_ocr(
            imagen,
            pagina=numero_pagina,
            escala=escala,
            # En PDF las paginas OCR suelen ser bloques de texto completos;
            # PSM 6 evita ejecutar una segunda pasada con PSM 3.
            psms=(6,),
        )

    def _extraer_tablas(self, page: fitz.Page) -> list[PdfTable]:
        """Extrae tablas mediante la API nativa de PyMuPDF 1.23+."""
        try:
            finder = page.find_tables()
        except (AttributeError, RuntimeError, ValueError):
            return []
        tablas: list[PdfTable] = []
        for tabla in getattr(finder, "tables", []):
            filas = tabla.extract()
            if not filas:
                continue
            cabeceras = nombrar_cabeceras(
                [str(celda or "").strip() for celda in filas[0]],
                unicos=True,
            )
            filas_linealizadas = [
                linealizar_fila(
                    cabeceras,
                    [str(celda or "").strip() for celda in fila],
                )
                for fila in filas[1:]
            ]
            filas_linealizadas = [fila for fila in filas_linealizadas if fila]
            if filas_linealizadas:
                tablas.append(
                    PdfTable(
                        pagina=page.number + 1,
                        bbox=BBox(*tabla.bbox),
                        filas=filas_linealizadas,
                    )
                )
        return tablas

    def _emitir_tabla(
        self,
        doc: ParsedDocument,
        tabla: PdfTable,
        pila: list[tuple[int, str]],
    ) -> None:
        for fila in tabla.filas:
            doc.blocks.append(
                self._bloque(
                    "table_row",
                    fila,
                    seccion_path=[texto for _, texto in pila],
                    ancla={
                        "pagina": tabla.pagina,
                        "bbox": [
                            tabla.bbox.x0,
                            tabla.bbox.y0,
                            tabla.bbox.x1,
                            tabla.bbox.y1,
                        ],
                    },
                )
            )

    def _emitir_bloques(
        self,
        doc: ParsedDocument,
        pdf_block: PdfBlock,
        tamanio_normal: float | None,
        niveles: dict[float, int],
        pila: list[tuple[int, str]],
    ) -> None:
        grupos = self._agrupar_lineas(
            pdf_block.lineas,
            tamanio_normal,
            cerca_de_imagen=pdf_block.cerca_de_imagen,
        )
        for tipo, lineas in grupos:
            if tipo not in TIPOS_BLOQUE:
                raise ValueError(f"Tipo de bloque invalido: {tipo!r}")
            texto = "\n".join(linea.texto for linea in lineas)
            bbox = [
                min(linea.bbox.x0 for linea in lineas),
                min(linea.bbox.y0 for linea in lineas),
                max(linea.bbox.x1 for linea in lineas),
                max(linea.bbox.y1 for linea in lineas),
            ]
            nivel = niveles.get(round(lineas[0].size, 1)) if tipo == "heading" else None
            if tipo == "heading":
                seccion_path = empujar_seccion(pila, nivel or 1, texto)
            else:
                seccion_path = [texto_seccion for _, texto_seccion in pila]
            doc.blocks.append(
                self._bloque(
                    tipo,
                    texto,
                    nivel=nivel,
                    seccion_path=seccion_path,
                    ancla={"pagina": pdf_block.pagina, "bbox": bbox},
                )
            )

    @staticmethod
    def _normalizar_repeticion(texto: str) -> str:
        texto = unicodedata.normalize("NFKC", texto).casefold()
        return " ".join(texto.split())

    def _cabeceras_pies_repetidos(
        self,
        pdf_blocks: list[PdfBlock],
        paginas: list[dict],
    ) -> set[str]:
        altos = {p["numero"]: p["alto"] for p in paginas}
        apariciones: dict[str, set[int]] = {}
        for bloque in pdf_blocks:
            alto = altos[bloque.pagina]
            for linea in bloque.lineas:
                if linea.bbox.y0 < alto * 0.07 or linea.bbox.y1 > alto * 0.93:
                    clave = self._normalizar_repeticion(linea.texto)
                    if clave:
                        apariciones.setdefault(clave, set()).add(bloque.pagina)
        return {texto for texto, paginas_texto in apariciones.items() if len(paginas_texto) >= 3}

    def _filtrar_bloque(
        self,
        bloque: PdfBlock,
        repetidos: set[str],
        paginas: list[dict],
    ) -> PdfBlock | None:
        alto = next(p["alto"] for p in paginas if p["numero"] == bloque.pagina)
        bloque.lineas = [
            linea for linea in bloque.lineas
            if not (
                self._normalizar_repeticion(linea.texto) in repetidos
                and (linea.bbox.y0 < alto * 0.07 or linea.bbox.y1 > alto * 0.93)
            )
        ]
        return bloque if bloque.lineas else None

    def _paginas_de_indice(self, paginas: list[dict]) -> set[int]:
        descartadas: set[int] = set()
        for pagina in paginas:
            lineas = [
                "".join(span.get("text", "") for span in linea.get("spans", []))
                for bloque in pagina["contenido"]["blocks"]
                for linea in bloque.get("lines", [])
            ]
            relevantes = [linea.strip() for linea in lineas if linea.strip()]
            if relevantes and sum(bool(_RE_INDEX.search(linea)) for linea in relevantes) / len(relevantes) > 0.4:
                descartadas.add(pagina["numero"])
        return descartadas

    def _ordenar_bloques(
        self,
        bloques: list[PdfBlock],
    ) -> tuple[list[PdfBlock], bool]:
        orden_natural = sorted(bloques, key=lambda b: (b.bbox.y0, b.bbox.x0))
        if len(bloques) < 4:
            return orden_natural, False
        xs = sorted(b.bbox.x0 for b in bloques)
        separacion, indice = max(
            ((xs[i + 1] - xs[i], i) for i in range(len(xs) - 1)),
            default=(0, 0),
        )
        if separacion <= 72:
            return orden_natural, False
        corte = xs[indice] + separacion / 2
        izquierda = sorted((b for b in bloques if b.bbox.x0 <= corte), key=lambda b: b.bbox.y0)
        derecha = sorted((b for b in bloques if b.bbox.x0 > corte), key=lambda b: b.bbox.y0)
        return izquierda + derecha, True

    def _niveles_heading(
        self,
        bloques: list[PdfBlock],
        tamanio_normal: float | None,
    ) -> dict[float, int]:
        tamanios = sorted({
            round(linea.size, 1)
            for bloque in bloques
            for linea in bloque.lineas
            if self._tipo_linea(
                linea,
                tamanio_normal,
                cerca_de_imagen=bloque.cerca_de_imagen,
            ) == "heading"
        }, reverse=True)
        return {tamanio: min(indice + 1, 6) for indice, tamanio in enumerate(tamanios)}

    def _extraer_bloque(
        self,
        pdf_block: dict,
        pagina: int,
        pesos_tamanio: Counter[float],
        imagenes: list[BBox],
    ) -> PdfBlock | None:
        """Extrae un bloque de texto de la estructura 'dict' de PyMuPDF.

        Args:
            pdf_block: Diccionario con los datos del bloque (contiene 'lines').
            pagina: Número de página donde se encuentra el bloque.

        Returns:
            PdfBlock: Objeto con la información del bloque, o None si está vacío.
        """
        lineas = []
        lineas_pdf = pdf_block.get("lines")
        if not lineas_pdf:
            return None

        for pdf_line in lineas_pdf:
            linea = self._extraer_linea(pdf_line)

            if linea is not None:
                lineas.append(linea)
                tamanio = round(linea.size, 1)
                pesos_tamanio[tamanio] += len(linea.texto.strip())
        if not lineas:
            return None
        return PdfBlock(
            pagina=pagina,
            bbox=BBox(*pdf_block["bbox"]),
            lineas=lineas,
            cerca_de_imagen=any(
                self._linea_cerca_de_imagen(linea, imagen)
                for linea in lineas
                for imagen in imagenes
            ),
        )

    @staticmethod
    def _linea_cerca_de_imagen(linea: PdfLine, imagen: BBox) -> bool:
        """Indica si una línea está justo encima o debajo de una imagen."""
        margen_vertical = 36.0
        margen_horizontal = 12.0
        solapamiento_horizontal = min(linea.bbox.x1, imagen.x1) - max(
            linea.bbox.x0, imagen.x0
        )
        distancia_vertical = min(
            abs(linea.bbox.y1 - imagen.y0),
            abs(imagen.y1 - linea.bbox.y0),
        )
        esta_fuera = linea.bbox.y1 <= imagen.y0 or linea.bbox.y0 >= imagen.y1
        return (
            solapamiento_horizontal >= -margen_horizontal
            and esta_fuera
            and distancia_vertical <= margen_vertical
        )

    def _extraer_linea(self, pdf_line: dict) -> PdfLine | None:
        """Extrae una línea de texto y calcula sus propiedades de formato.

        Determina la fuente predominante, el tamaño máximo, y si es negrita o cursiva
        basándose en los 'spans' que componen la línea.

        Args:
            pdf_line: Diccionario con los datos de la línea (contiene 'spans').

        Returns:
            PdfLine: Objeto con el texto y metadatos, o None si es solo espacio en blanco.
        """
        if not pdf_line["spans"]:
            raise ValueError("Linea sin spans")
        texto = ""
        fuentes = {}
        size = 0
        bold = False
        italic = False
        for span in pdf_line["spans"]:
            texto += span["text"]
            fuentes[span["font"]] = (
                fuentes.get(span["font"], 0)
                + len(span["text"])
            )
            if span["size"] > size:
                size = span["size"]
        font_predominante = max(fuentes, key=fuentes.get)
        bold = "Bold" in font_predominante
        italic = (
            "Italic" in font_predominante
            or "Oblique" in font_predominante
        )
        if not texto.strip():
            return None
        return PdfLine(texto, BBox(*pdf_line["bbox"]), font_predominante, size, bold, italic)

    def _tipo_linea(
        self,
        linea: PdfLine,
        tamanio_normal: float | None,
        *,
        cerca_de_imagen: bool = False,
    ) -> TipoBloque:
        texto = linea.texto.strip()

        if _RE_CAPTION.match(texto):
            return "caption"

        es_caption_contextual = (
            cerca_de_imagen
            and len(texto) <= 200
            and (
                tamanio_normal is None
                or linea.size <= tamanio_normal * 1.10
                or linea.italic
            )
        )
        if es_caption_contextual:
            return "caption"

        if tamanio_normal is None:
            return "paragraph"

        es_texto_corto = len(texto) <= 150
        es_mas_grande = linea.size >= tamanio_normal * 1.15
        es_negrita_destacada = (
            linea.bold
            and linea.size >= tamanio_normal
        )

        if es_texto_corto and (es_mas_grande or es_negrita_destacada):
            return "heading"

        return "paragraph"

    def _agrupar_lineas(
        self,
        lineas: list[PdfLine],
        tamanio_normal: float | None,
        *,
        cerca_de_imagen: bool = False,
    ) -> list[GrupoLineas]:
        grupos: list[GrupoLineas] = []
        for linea in lineas:
            tipo = self._tipo_linea(
                linea,
                tamanio_normal,
                cerca_de_imagen=cerca_de_imagen,
            )

            # Headings y captions no se fusionan entre sí
            if tipo != "paragraph":
                grupos.append((tipo, [linea]))
                continue

            # Solo se juntan párrafos contiguos
            if grupos and grupos[-1][0] == "paragraph":
                grupos[-1][1].append(linea)
            else:
                grupos.append(("paragraph", [linea]))

        return grupos

@dataclass
class PdfLine:
    """Representación de una línea física en un PDF.

    Atributos:
        texto: Contenido textual de la línea.
        bbox: Coordenadas del área que ocupa la línea.
        font: Nombre de la fuente predominante.
        size: Tamaño de fuente máximo detectado en la línea.
        bold: True si la fuente predominante indica negrita.
        italic: True si la fuente predominante indica cursiva u oblicua.
    """
    texto: str
    bbox: BBox

    font: str
    size: float

    bold: bool
    italic: bool


GrupoLineas = tuple[TipoBloque, list[PdfLine]]


@dataclass
class PdfTable:
    pagina: int
    bbox: BBox
    filas: list[str]


@dataclass
class PdfBlock:
    """Agrupación de líneas que forman un bloque estructural en el PDF.

    Atributos:
        pagina: Número de página (1-based).
        bbox: Coordenadas del área que ocupa el bloque completo.
        lineas: Lista de objetos PdfLine que componen el bloque.
    """
    pagina: int
    bbox: BBox
    lineas: list[PdfLine]
    cerca_de_imagen: bool = False
