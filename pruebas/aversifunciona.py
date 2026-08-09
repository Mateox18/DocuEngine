from sentence_transformers import SentenceTransformer
from encoder.octen import armar_indice
from chunker.models import Chunk
import torch
print(torch.cuda.is_available())
def chunk_de_prueba(id_, texto):
    return Chunk(id_=id_, doc_id="DOC-1-00001", indice=0, texto=texto, fuente="prueba.md", fenomeno=1)

model = SentenceTransformer("Octen/Octen-Embedding-8B-INT8", device="cuda")

chunks = [
    chunk_de_prueba(1, "texto de ejemplo uno"),
    chunk_de_prueba(2, "texto de ejemplo dos"),
]

malos = armar_indice(chunks, model, dim=4096, salto=8,
                      ruta_indice="index.faiss", ruta_metadata="metadata.jsonl")
print("fallidos:", malos)