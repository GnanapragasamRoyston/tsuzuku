"""Encodeur sentence-transformers, chargé seulement par `make embeddings` (extra `embeddings`).

Import paresseux : l'image Airflow, l'API et la CI n'installent pas PyTorch ; les tests passent
un encodeur factice qui respecte la même interface (`name`, `encode`).
"""

from typing import Protocol

import numpy as np


class Encoder(Protocol):
    name: str

    def encode(self, texts: list[str]) -> np.ndarray: ...


class SentenceEncoder:
    def __init__(self, model: str, prefix: str = "", batch_size: int = 64) -> None:
        from sentence_transformers import SentenceTransformer  # extra « embeddings »

        # Le préfixe fait partie de l'identité : « query: » change les vecteurs d'e5.
        self.name = f"{model}|{prefix}" if prefix else model
        self.prefix = prefix
        self.batch_size = batch_size
        self.model = SentenceTransformer(model, device="cpu")

    def encode(self, texts: list[str]) -> np.ndarray:
        vectors = self.model.encode(
            [self.prefix + t for t in texts],
            batch_size=self.batch_size,
            normalize_embeddings=True,  # cosinus = produit scalaire, et norme 1 en base
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return np.asarray(vectors, dtype=np.float32)
