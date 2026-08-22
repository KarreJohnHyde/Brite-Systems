"""Embedding backends with a deterministic offline implementation."""

from __future__ import annotations

import hashlib
import re
from typing import Literal

import numpy as np

from src.models import PolicyChunk
from src.parser import get_embedding_text

WORD_RE = re.compile(r"[a-z0-9]+(?:\.[0-9]+)*", re.IGNORECASE)
DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class EmbeddingUnavailableError(RuntimeError):
    """Raised when an explicitly selected embedding backend cannot load."""


class EmbeddingEngine:
    """Encode clauses and queries using a recorded, reproducible backend.

    `hashing` is the credential-free default. It produces real normalized dense
    vectors from word and word-bigram features and requires no network/model
    download. `sentence-transformers` enables MiniLM when desired.
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        *,
        backend: Literal["hashing", "sentence-transformers"] = "hashing",
        dimension: int = 768,
    ) -> None:
        self.backend = backend
        self.model_name = model_name if backend == "sentence-transformers" else f"stable-hashing-{dimension}"
        self._model = None
        if backend == "sentence-transformers":
            try:
                from sentence_transformers import SentenceTransformer

                self._model = SentenceTransformer(model_name)
                self.dimension = int(self._model.get_sentence_embedding_dimension())
            except Exception as exc:
                raise EmbeddingUnavailableError(
                    f"Could not load sentence-transformers model {model_name!r}. "
                    "Use EMBEDDING_BACKEND=hashing for the offline backend."
                ) from exc
        else:
            self.dimension = dimension

    @property
    def descriptor(self) -> str:
        return f"{self.backend}:{self.model_name}"

    def encode_clauses(self, clauses: list[PolicyChunk]) -> np.ndarray:
        if not clauses:
            return np.empty((0, self.dimension), dtype="float32")
        return self._encode([get_embedding_text(chunk) for chunk in clauses])

    def encode_query(self, query: str) -> np.ndarray:
        if not query.strip():
            raise ValueError("Question must not be empty")
        return self._encode([query])

    def _encode(self, texts: list[str]) -> np.ndarray:
        if self._model is not None:
            vectors = self._model.encode(
                texts,
                show_progress_bar=len(texts) > 16,
                convert_to_numpy=True,
                normalize_embeddings=True,
            )
            return np.asarray(vectors, dtype="float32")
        return np.vstack([self._hash_vector(text) for text in texts]).astype("float32")

    def _hash_vector(self, text: str) -> np.ndarray:
        tokens = WORD_RE.findall(text.lower())
        features = tokens + [f"{a}::{b}" for a, b in zip(tokens, tokens[1:])]
        vector = np.zeros(self.dimension, dtype="float32")
        for feature in features:
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=16).digest()
            index = int.from_bytes(digest[:8], "little") % self.dimension
            sign = 1.0 if digest[8] & 1 else -1.0
            vector[index] += sign
        norm = float(np.linalg.norm(vector))
        if norm:
            vector /= norm
        return vector
