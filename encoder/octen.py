import torch
import numpy as np
from sentence_transformers import SentenceTransformer

if torch.backends.mps.is_available():
    DEVICE = 'mps'
else:
    DEVICE = 'cpu'

print(f"Usando Device: {DEVICE}")

MODEL_NAME = "Octen/Octen-Embedding-8B-INT8"

model = SentenceTransformer(MODEL_NAME, device=DEVICE)

print("Modelo cargado correctamente.")