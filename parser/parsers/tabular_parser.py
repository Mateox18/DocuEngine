"""Parser de formatos tabulares (.csv, .tsv, .xlsx, .xls).

FILA ATOMICA: una fila NUNCA debe partirse entre fragmentos. Es la unidad
indivisible equivalente a la oracion en prosa: media fila ("pais: Colombia |
anio:") no es una proposicion evaluable y rompe el requisito de completitud
linguistica. El chunker puede agrupar filas contiguas, jamas dividir una.

Backend: `csv` de la stdlib y openpyxl en modo read_only, sin pandas. La
especificacion prohibe inferir tipos y las filas se recorren de una en una, asi
que pandas no aportaria nada y ademas obligaria a leer el archivo entero para
aplicar el limite de filas; los iteradores lo resuelven por streaming.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from collections.abc import Iterator, Sequence
from datetime import date, datetime
from itertools import chain, islice
from pathlib import Path
from typing import Any

from parser.models import Block, ParsedDocument
from parser.parsers.base import BaseParser, ParserError
from parser.parsers.lectura import leer_texto
from parser.parsers.tablas import linealizar_fila, nombrar_cabeceras

logger = logging.getLogger(__name__)

# Un dataset gigantesco domina el indice y degrada la recuperacion del resto.
LIMITE_FILAS = 50_000

FILAS_INSPECCION = 20
UMBRAL_TEXTUAL = 0.70
LARGO_MAX_CABECERA = 80
LIMITE_COLUMNAS_ANCHA = 30
MIN_COLUMNAS_TRAS_FILTRO = 5

_DELIMITADORES = ",;\t|"
_MUESTRA_SNIFFER = 65_536

_RE_NUMERO = re.compile(r"^[+-]?[\d.,]+(?:[eE][+-]?\d+)?$")
_RE_SOLO_SIMBOLOS = re.compile(r"^[\W\d_]+$", re.UNICODE)
_RE_COL_SINTETICA = re.compile(r"^col\d+$")
_PREFIJOS_NO_INFORMATIVOS = ("unnamed", "id_", "cod_", "_")
_VOCALES = set("AEIOU")

# Firmas de los primeros bytes, para los ".xls" que no lo son.
_MAGIC_ZIP = b"PK\x03\x04"
_MAGIC_OLE = b"\xd0\xcf\x11\xe0"


def _parece_numero(celda: str) -> bool:
    """True si la celda es un numero en cualquier notacion habitual.

    Con todo leido como str, "es un string" no discrimina nada; lo que
    discrimina una cabecera de una fila de datos es "no es un numero".
    """
    limpia = celda.strip().rstrip("%").replace("$", "").replace("€", "")
    limpia = limpia.replace(" ", "").replace(" ", "")
    if not limpia or not any(c.isdigit() for c in limpia):
        return False
    return bool(_RE_NUMERO.match(limpia))


def detectar_cabecera(muestra: Sequence[Sequence[str]]) -> int | None:
    """Indice de la fila de cabecera dentro de la muestra, o None.

    Los datasets del AI Index y similares traen titulo, notas y fuente antes de
    la tabla real, asi que la fila 0 rara vez es la cabecera.

    LIMITACION CONOCIDA: una tabla cuyas columnas son anios (1990, 1991, ...)
    no supera el umbral textual y se queda sin cabecera detectada. No se pierde
    ninguna fila —los anios se emiten como una fila de datos mas y las columnas
    pasan a colN— pero se degradan las etiquetas. Relajar el umbral haria que
    cualquier fila de datos numericos pudiera pasar por cabecera, que es peor.
    TODO(corpus): revisar con datasets reales si compensa una regla especifica.
    """
    for i in range(min(FILAS_INSPECCION, len(muestra))):
        celdas = [c.strip() for c in muestra[i]]
        no_vacias = [c for c in celdas if c]
        if len(no_vacias) < 2:
            continue
        # Con todo leido como str, lo que distingue una cabecera de una fila de
        # datos no es "ser string" sino "no ser un numero".
        textuales = [c for c in no_vacias if not _parece_numero(c)]
        if len(textuales) / len(celdas) < UMBRAL_TEXTUAL:
            continue
        if len({c.casefold() for c in no_vacias}) != len(no_vacias):
            continue
        if any(len(c) > LARGO_MAX_CABECERA for c in no_vacias):
            continue
        # Debe seguirle una fila con forma de tabla. Se compara el numero de
        # CELDAS, no el de celdas no vacias: un dato ausente en la primera fila
        # es de lo mas normal y no puede invalidar la cabecera.
        if i + 1 >= len(muestra):
            continue
        siguiente = muestra[i + 1]
        if len(siguiente) < 2 or not any(c.strip() for c in siguiente):
            continue
        return i
    return None


class TabularParser(BaseParser):
    """Parser de CSV, TSV y libros de Excel."""

    EXTENSIONES = (".csv", ".tsv", ".xlsx", ".xls")
    FORMATO = "csv"
    MAPA_FORMATOS = {".tsv": "tsv", ".xlsx": "xlsx", ".xls": "xls"}

    # ------------------------------------------------------------------ API

    def parse(self, path: Path, doc_id: str, fenomeno: int) -> ParsedDocument:
        """Parsea un archivo tabular emitiendo un bloque por fila de datos."""
        doc = self._nuevo_documento(path, doc_id, fenomeno)

        bloques: list[Block] = []
        preambulos: list[str] = []
        hojas_vacias: list[str] = []
        descartadas: list[str] = []
        procesadas = 0

        for hoja, filas in self._hojas(path, doc):
            muestra = list(islice(filas, FILAS_INSPECCION))
            restantes = chain(muestra, filas)
            if not any(any(c.strip() for c in fila) for fila in muestra):
                siguiente = list(islice(filas, 1))
                if not siguiente:
                    hojas_vacias.append(hoja)
                    continue
                restantes = chain(muestra, siguiente, filas)

            nuevos, preambulo, fuera, procesadas = self._procesar_hoja(
                hoja, muestra, restantes, procesadas, doc
            )
            bloques.extend(nuevos)
            if preambulo:
                preambulos.append(preambulo)
            descartadas.extend(fuera)
            if procesadas >= LIMITE_FILAS:
                break

        doc.blocks = bloques
        if preambulos:
            doc.meta_extra["preambulo"] = "\n".join(preambulos)
            doc.titulo = self._primera_linea(preambulos[0])
        if hojas_vacias:
            doc.meta_extra["hojas_vacias"] = hojas_vacias
        if descartadas:
            doc.meta_extra["columnas_descartadas"] = descartadas
        doc.meta_extra["filas_procesadas"] = procesadas

        if procesadas >= LIMITE_FILAS:
            doc.meta_extra["truncado"] = True
            doc.errores.append(
                f"archivo truncado: se procesaron las primeras {LIMITE_FILAS} filas"
            )
            self.logger.warning("%s: truncado en %d filas", doc.fuente, LIMITE_FILAS)

        if not doc.blocks:
            doc.meta_extra["vacio"] = True
            doc.errores.append("documento vacio: 0 bloques extraidos")
            self.logger.warning("documento vacio: %s", doc.fuente)
        return doc

    # --------------------------------------------------------------- Hojas

    def _hojas(
        self, path: Path, doc: ParsedDocument
    ) -> Iterator[tuple[str, Iterator[list[str]]]]:
        """Genera (nombre de hoja, iterador de filas ya en str).

        Unica frontera con la libreria de lectura: cambiar de backend no toca
        la emision de bloques. En CSV el nombre de hoja es la cadena vacia.
        """
        extension = path.suffix.lower()
        if extension in (".csv", ".tsv"):
            yield "", self._filas_csv(path, doc, extension)
        elif extension == ".xlsx":
            yield from self._filas_excel(path)
        else:
            yield from self._filas_xls(path, doc)

    def _filas_csv(
        self, path: Path, doc: ParsedDocument, extension: str
    ) -> Iterator[list[str]]:
        """Filas de un CSV/TSV, decodificado con la cascada de encoding."""
        leido = leer_texto(path, log=self.logger)
        doc.meta_extra["encoding"] = leido.encoding
        doc.meta_extra["bom"] = leido.bom
        delimitador = self._delimitador(leido.texto, extension)
        doc.meta_extra["delimitador"] = delimitador
        return (
            [celda.strip() for celda in fila]
            for fila in csv.reader(io.StringIO(leido.texto), delimiter=delimitador)
        )

    def _delimitador(self, texto: str, extension: str) -> str:
        """Delimitador del CSV. En TSV la extension es autoritativa."""
        if extension == ".tsv":
            # Sin sniffer: se equivoca con TSV cuyos campos llevan comas.
            return "\t"
        muestra = texto[:_MUESTRA_SNIFFER]
        try:
            return csv.Sniffer().sniff(muestra, delimiters=_DELIMITADORES).delimiter
        except csv.Error:
            # Le pasa a menudo con preambulos sin delimitadores.
            return self._delimitador_por_consistencia(muestra)

    def _delimitador_por_consistencia(self, muestra: str) -> str:
        """Elige el delimitador que produce el conteo de campos mas estable."""
        lineas = [linea for linea in muestra.split("\n") if linea.strip()][
            :FILAS_INSPECCION
        ]
        mejor = ","
        mejor_puntuacion = (0, 0)
        for candidato in _DELIMITADORES:
            conteos = [linea.count(candidato) + 1 for linea in lineas]
            if not conteos:
                continue
            modal = max(set(conteos), key=conteos.count)
            if modal < 2:
                continue
            puntuacion = (conteos.count(modal), modal)
            if puntuacion > mejor_puntuacion:
                mejor, mejor_puntuacion = candidato, puntuacion
        return mejor

    def _filas_excel(
        self, origen: Path | io.BytesIO
    ) -> Iterator[tuple[str, Iterator[list[str]]]]:
        """Hojas de un .xlsx, en orden y sin cargar el libro entero.

        Acepta un handle en memoria porque openpyxl rechaza por extension los
        archivos .xls, aunque su contenido sea un xlsx perfectamente valido.
        """
        import openpyxl

        # data_only=True da el valor cacheado de las formulas en vez de
        # "=SUM(A1:A9)"; sin eso un dataset con formulas indexa basura.
        libro = openpyxl.load_workbook(origen, read_only=True, data_only=True)
        for hoja in libro.worksheets:
            yield hoja.title, (
                [_celda_a_str(celda) for celda in fila]
                for fila in hoja.iter_rows(values_only=True)
            )

    def _filas_xls(
        self, path: Path, doc: ParsedDocument
    ) -> Iterator[tuple[str, Iterator[list[str]]]]:
        """Hojas de un .xls legado, comprobando antes que lo sea de verdad."""
        datos = path.read_bytes()
        cabecera = datos[:8]
        if cabecera.startswith(_MAGIC_ZIP):
            doc.errores.append("archivo .xls que en realidad es .xlsx")
            self.logger.warning("%s: extension .xls con contenido xlsx", doc.fuente)
            yield from self._filas_excel(io.BytesIO(datos))
            return
        if cabecera.lstrip()[:1] == b"<":
            raise ParserError(
                f"{path.name} tiene extension .xls pero es HTML; le corresponde HtmlParser"
            )
        if not cabecera.startswith(_MAGIC_OLE):
            raise ParserError(f"{path.name} no es un .xls reconocible")

        try:
            import xlrd
        except ImportError as exc:  # pragma: no cover - depende del entorno
            raise ParserError(
                "archivo .xls legado: instalar xlrd>=2.0 o convertir a .xlsx"
            ) from exc

        libro = xlrd.open_workbook(str(path))
        for hoja in libro.sheets():
            yield hoja.name, (
                [_celda_a_str(valor) for valor in hoja.row_values(n)]
                for n in range(hoja.nrows)
            )

    # ------------------------------------------------------------ Emision

    def _procesar_hoja(
        self,
        hoja: str,
        muestra: list[list[str]],
        filas: Iterator[list[str]],
        procesadas: int,
        doc: ParsedDocument,
    ) -> tuple[list[Block], str, list[str], int]:
        """Detecta cabecera y emite un table_row por fila de datos."""
        indice_cabecera = detectar_cabecera(muestra)
        if hoja:
            doc.meta_extra.setdefault("fila_cabecera", {})
            doc.meta_extra["fila_cabecera"][hoja] = indice_cabecera
        else:
            doc.meta_extra["fila_cabecera"] = indice_cabecera
            doc.meta_extra["cabecera_detectada"] = indice_cabecera is not None

        preambulo = ""
        if indice_cabecera is not None:
            preambulo = "\n".join(
                " ".join(c for c in fila if c.strip())
                for fila in muestra[:indice_cabecera]
                if any(c.strip() for c in fila)
            )
            cabeceras = nombrar_cabeceras(
                [c.strip() for c in muestra[indice_cabecera]], unicos=True
            )
            primera_datos = indice_cabecera + 1
        else:
            # Fallback que no pierde datos: si la fila 0 no parece cabecera,
            # tomarla como tal borraria una fila de datos.
            ancho = max((len(f) for f in muestra), default=0)
            cabeceras = nombrar_cabeceras([""] * ancho, unicos=True)
            primera_datos = 0

        indices, descartadas = self._columnas_informativas(cabeceras, doc)
        # Sin filtro de columnas se deja pasar la fila entera: si trae mas
        # celdas que cabeceras, linealizar_fila les pone col{n+1} en vez de
        # tirarlas en silencio.
        sin_filtro = indices == list(range(len(cabeceras)))
        activas = [cabeceras[i] for i in indices]
        titulo_tabla = self._primera_linea(preambulo)
        prefijo = self._prefijo(hoja, titulo_tabla)
        ruta = [hoja] if hoja else []

        bloques: list[Block] = []
        for numero, fila in enumerate(filas):
            if numero < primera_datos:
                continue
            if procesadas >= LIMITE_FILAS:
                break
            procesadas += 1
            if sin_filtro:
                celdas = list(fila)
            else:
                celdas = [fila[i] if i < len(fila) else "" for i in indices]
            texto = linealizar_fila(activas, celdas)
            if not texto:
                continue
            bloques.append(
                self._bloque(
                    "table_row",
                    prefijo + texto,
                    ancla={
                        "hoja": hoja,
                        "fila": numero,
                        "columnas": activas,
                    },
                    seccion_path=ruta,
                )
            )
        return bloques, preambulo, descartadas, procesadas

    def _columnas_informativas(
        self, cabeceras: Sequence[str], doc: ParsedDocument
    ) -> tuple[list[int], list[str]]:
        """Indices de las columnas a conservar y nombres de las descartadas."""
        if len(cabeceras) <= LIMITE_COLUMNAS_ANCHA:
            return list(range(len(cabeceras))), []

        conservar = [i for i, n in enumerate(cabeceras) if self._es_informativa(n)]
        descartadas = [n for i, n in enumerate(cabeceras) if i not in set(conservar)]

        # Valvula de seguridad: una tabla cuyas columnas son anios (todas
        # "puramente numericas") perderia el 100% de sus datos en silencio.
        if (
            len(descartadas) > len(cabeceras) / 2
            or len(conservar) < MIN_COLUMNAS_TRAS_FILTRO
        ):
            doc.meta_extra["filtro_columnas"] = "omitido"
            self.logger.info(
                "%s: filtro de columnas omitido (%d de %d se descartarian)",
                doc.fuente,
                len(descartadas),
                len(cabeceras),
            )
            return list(range(len(cabeceras))), []
        return conservar, descartadas

    def _es_informativa(self, nombre: str) -> bool:
        """False si el nombre de columna no aporta significado semantico."""
        limpio = nombre.strip()
        if not limpio or _RE_SOLO_SIMBOLOS.match(limpio):
            return False
        if _RE_COL_SINTETICA.match(limpio):
            return False
        if limpio.lower().startswith(_PREFIJOS_NO_INFORMATIVOS):
            return False
        if len(limpio) <= 6 and limpio.isupper() and not set(limpio) & _VOCALES:
            return False
        return True

    def _prefijo(self, hoja: str, titulo_tabla: str) -> str:
        """Contexto que se antepone a cada fila. Solo lo que exista."""
        partes = []
        if hoja:
            partes.append(f"[Hoja: {hoja}]")
        if titulo_tabla:
            partes.append(f"[Tabla: {titulo_tabla}]")
        return " ".join(partes) + " " if partes else ""

    def _primera_linea(self, texto: str) -> str:
        """Primera linea no vacia de un texto, o cadena vacia."""
        for linea in texto.split("\n"):
            if linea.strip():
                return linea.strip()
        return ""


def _celda_a_str(valor: Any) -> str:
    """Serializacion canonica de una celda de Excel.

    No es inferencia de tipos sino serializacion: una celda de Excel no tiene
    forma textual propia y hay que elegir una estable.
    """
    if valor is None:
        return ""
    if isinstance(valor, bool):
        return "true" if valor else "false"
    if isinstance(valor, float):
        # Excel guarda los enteros como float: sin esto un anio saldria "2019.0".
        return str(int(valor)) if valor.is_integer() else repr(valor)
    if isinstance(valor, datetime):
        if (valor.hour, valor.minute, valor.second) == (0, 0, 0):
            return valor.date().isoformat()
        return valor.isoformat(sep=" ")
    if isinstance(valor, date):
        return valor.isoformat()
    return str(valor).strip()
