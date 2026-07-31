from dataclasses import dataclass, field

@dataclass
class Block:
    """Unidad estructural del documento."""
    # Tipo del bloque (heading, paragraph, table, caption...)
    tipo: str
    texto: str
    # Para markdown y html
    nivel: int | None = None

@dataclass
class ParsedDocument:
    """Representación intermedia de un documento parseado."""
    # Metadata del documento
    doc_id: str
    fuente: str
    formato: str
    fenomeno: int
    titulo: str | None = None

    # Contenido estructurado
    blocks: list[Block] = field(default_factory=list)
