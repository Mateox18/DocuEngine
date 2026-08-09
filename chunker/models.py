from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

@dataclass(kw_only=True)
class Chunk:
    """Unidad mínima de información para recuperación semántica.
    
    Contiene el texto y metadatos denormalizados del documento original para
    permitir respuestas rápidas y trazabilidad. El embedding se gestiona
    en memoria pero se omite en persistencia para evitar duplicidad con FAISS.
    """
    # 1. Identificadores y Trazabilidad
    id_: str                # ID único (puede ser hash del contenido o UUID)
    doc_id: str             # Referencia al ParsedDocument original
    indice: int             # Posición del chunk dentro del documento para mantener el orden
    
    # 2. Contenido y Representación
    texto: str              # El fragmento de texto procesado
    embedding: list[float] | None = None  # Vector generado por Octen-8B (SentenceTransformer)
    
    # 3. Metadatos de Evaluación (Críticos para el reto)
    fuente: str             # Nombre exacto del archivo original
    fenomeno: int           # Categoría del documento
    
    # 4. Contexto Estructural
    seccion_path: list[str] = field(default_factory=list) # Ancestros (H1 > H2...)
    pagina: int | None = None  # Página original (especialmente para PDFs)
    tipo_bloque_origen: str | None = None # p.ej. "table_row", "paragraph"
    
    # 5. Flexibilidad
    meta_extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serializa el chunk a un formato compatible con bases vectoriales.
        
        NOTA: No incluye el embedding para evitar duplicidad; se asume que
        este se guarda en el índice vectorial (FAISS).
        """
        return {
            "id_": self.id_,
            "doc_id": self.doc_id,
            "texto": self.texto,
            "metadata": {
                "fuente": self.fuente,
                "fenomeno": self.fenomeno,
                "indice": self.indice,
                "seccion_path": list(self.seccion_path),
                "pagina": self.pagina,
                "tipo": self.tipo_bloque_origen,
                **self.meta_extra
            }
        }

    @classmethod
    def from_dict(cls, datos: dict[str, Any]) -> Chunk:
        """Reconstruye un Chunk desde un diccionario."""
        meta = datos.get("metadata", {})
        # Identificar qué campos de meta son extra
        fijos = {"fuente", "fenomeno", "indice", "seccion_path", "pagina", "tipo"}
        extra = {k: v for k, v in meta.items() if k not in fijos}
        
        return cls(
            id_=datos["id_"],
            doc_id=datos["doc_id"],
            texto=datos["texto"],
            fuente=meta.get("fuente", ""),
            fenomeno=meta.get("fenomeno", 0),
            indice=meta.get("indice", 0),
            seccion_path=meta.get("seccion_path", []),
            pagina=meta.get("pagina"),
            tipo_bloque_origen=meta.get("tipo"),
            meta_extra=extra
        )