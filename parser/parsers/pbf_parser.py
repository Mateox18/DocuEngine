"""Parser de atributos textuales en OSM PBF y Mapbox Vector Tiles."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from parser.models import ParsedDocument
from parser.parsers.base import BaseParser, ParserError
from parser.parsers.tablas import linealizar_fila, nombrar_cabeceras


class PbfParser(BaseParser):
    """Extrae atributos recuperables de entidades geograficas."""

    EXTENSIONES = (".pbf",)
    FORMATO = "pbf"

    def parse(self, path: Path, doc_id: str, fenomeno: int) -> ParsedDocument:
        doc = self._nuevo_documento(path, doc_id, fenomeno)
        with path.open("rb") as archivo:
            cabecera = archivo.read(65536)
        es_osm = b"OSMHeader" in cabecera
        if es_osm:
            bloques, eliminados = self._parsear_osm(path)
        else:
            bloques, eliminados = self._parsear_mvt(path.read_bytes())

        doc.blocks = bloques
        doc.meta_extra.update(
            {
                "tipo_pbf": "osm" if es_osm else "mvt",
                "features_deduplicados": eliminados,
            }
        )
        return doc

    def _parsear_osm(self, path: Path):
        try:
            import osmium
        except ImportError as exc:
            raise ParserError("Falta la dependencia osmium para OSM PBF") from exc

        parser = self
        bloques = []
        vistos: set[tuple[str, int]] = set()
        eliminados = 0

        class Handler(osmium.SimpleHandler):
            def _objeto(self, tipo: str, objeto: Any) -> None:
                nonlocal eliminados
                clave = (tipo, int(objeto.id))
                if clave in vistos:
                    eliminados += 1
                    return
                atributos = parser._atributos_textuales(dict(objeto.tags))
                if not atributos:
                    return
                vistos.add(clave)
                cabeceras = nombrar_cabeceras(list(atributos), unicos=True)
                texto = linealizar_fila(cabeceras, list(atributos.values()))
                if texto:
                    bloques.append(
                        parser._bloque(
                            "feature",
                            texto,
                            ancla={"capa": tipo, "feature_id": int(objeto.id)},
                        )
                    )

            def node(self, objeto):
                self._objeto("node", objeto)

            def way(self, objeto):
                self._objeto("way", objeto)

            def relation(self, objeto):
                self._objeto("relation", objeto)

        Handler().apply_file(str(path), locations=False)
        return bloques, eliminados

    def _parsear_mvt(self, datos: bytes):
        try:
            import mapbox_vector_tile
        except ImportError as exc:
            raise ParserError("Falta mapbox-vector-tile para MVT") from exc
        try:
            capas = mapbox_vector_tile.decode(datos)
        except Exception as exc:
            raise ParserError("PBF no reconocido como OSM PBF ni MVT") from exc

        bloques = []
        vistos: set[tuple[str, str]] = set()
        eliminados = 0
        for capa, contenido in capas.items():
            for indice, feature in enumerate(contenido.get("features", [])):
                feature_id = feature.get("id", indice)
                clave = (str(capa), str(feature_id))
                if clave in vistos:
                    eliminados += 1
                    continue
                atributos = self._atributos_textuales(feature.get("properties", {}))
                if not atributos:
                    continue
                vistos.add(clave)
                texto = linealizar_fila(
                    nombrar_cabeceras(list(atributos), unicos=True),
                    list(atributos.values()),
                )
                if texto:
                    bloques.append(
                        self._bloque(
                            "feature",
                            texto,
                            ancla={"capa": str(capa), "feature_id": feature_id},
                        )
                    )
        return bloques, eliminados

    @staticmethod
    def _atributos_textuales(atributos: dict[Any, Any]) -> dict[str, str]:
        salida: dict[str, str] = {}
        for clave, valor in atributos.items():
            nombre = str(clave)
            if (
                nombre.startswith("@")
                or nombre.startswith("__")
                or nombre.startswith("render_")
                or nombre in {"z_order", "layer", "source_layer"}
            ):
                continue
            if nombre == "osm_id" and isinstance(valor, (int, float)):
                continue
            if valor is not None and str(valor).strip():
                salida[nombre] = str(valor)
        return salida
