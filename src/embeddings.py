"""Embedding backends with a deterministic offline implementation."""

from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Callable
from typing import Any, Literal

import numpy as np

from src.models import PolicyChunk
from src.parser import get_embedding_text

WORD_RE = re.compile(r"[a-z0-9]+(?:\.[0-9]+)*", re.IGNORECASE)
DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
REMOTE_BATCH_SIZE = 64
REMOTE_MAX_ATTEMPTS = 5
RETRY_DELAY_RE = re.compile(
    r"(?:retry(?:delay|\s+in)?[^0-9]{0,24})([0-9]+(?:\.[0-9]+)?)\s*s",
    re.IGNORECASE,
)


class EmbeddingUnavailableError(RuntimeError):
    """Raised when an explicitly selected embedding backend cannot load."""


class EmbeddingEngine:
    """Encode clauses and queries using a recorded, reproducible backend.

    `hashing` is the credential-free default. It produces normalized dense
    vectors from word and word-bigram features and requires no network/model
    download. MiniLM, OpenAI, and Gemini are explicit semantic alternatives.
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        *,
        backend: Literal[
            "hashing",
            "sentence-transformers",
            "openai",
            "gemini",
        ] = "hashing",
        dimension: int = 768,
        api_key: str | None = None,
        client: Any | None = None,
        gemini_types: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.backend = backend
        self.model_name = (
            f"stable-hashing-{dimension}" if backend == "hashing" else model_name
        )
        self._model = None
        self._client = None
        self._gemini_types = gemini_types
        self._sleep = sleep
        if backend == "sentence-transformers":
            try:
                from sentence_transformers import SentenceTransformer

                self._model = SentenceTransformer(model_name)
                dimension_getter = getattr(self._model, "get_embedding_dimension", None)
                if dimension_getter is None:
                    dimension_getter = self._model.get_sentence_embedding_dimension
                self.dimension = int(dimension_getter())
            except Exception as exc:
                raise EmbeddingUnavailableError(
                    f"Could not load sentence-transformers model {model_name!r}. "
                    "Use EMBEDDING_BACKEND=hashing for the offline backend."
                ) from exc
        elif backend == "openai":
            self.dimension = dimension
            if client is not None:
                self._client = client
            else:
                if not api_key or not api_key.strip():
                    raise EmbeddingUnavailableError(
                        "OpenAI embeddings require an OpenAI API key"
                    )
                try:
                    from openai import OpenAI
                except ImportError as exc:
                    raise EmbeddingUnavailableError(
                        "OpenAI embeddings require the openai package"
                    ) from exc
                self._client = OpenAI(api_key=api_key.strip())
        elif backend == "gemini":
            self.dimension = dimension
            if client is not None:
                self._client = client
            else:
                if not api_key or not api_key.strip():
                    raise EmbeddingUnavailableError(
                        "Gemini embeddings require a Gemini API key"
                    )
                try:
                    from google import genai
                    from google.genai import types
                except ImportError as exc:
                    raise EmbeddingUnavailableError(
                        "Gemini embeddings require the google-genai package"
                    ) from exc
                self._client = genai.Client(api_key=api_key.strip())
                self._gemini_types = types
        else:
            self.dimension = dimension

    @property
    def descriptor(self) -> str:
        return f"{self.backend}:{self.model_name}"

    def encode_clauses(self, clauses: list[PolicyChunk]) -> np.ndarray:
        if not clauses:
            return np.empty((0, self.dimension), dtype="float32")
        return self._encode(
            [get_embedding_text(chunk) for chunk in clauses],
            is_query=False,
        )

    def encode_query(self, query: str) -> np.ndarray:
        if not query.strip():
            raise ValueError("Question must not be empty")
        return self._encode([query], is_query=True)

    def _encode(self, texts: list[str], *, is_query: bool) -> np.ndarray:
        if self._model is not None:
            vectors = self._model.encode(
                texts,
                show_progress_bar=len(texts) > 16,
                convert_to_numpy=True,
                normalize_embeddings=True,
            )
            return np.asarray(vectors, dtype="float32")
        if self.backend == "openai":
            return self._encode_openai(texts)
        if self.backend == "gemini":
            return self._encode_gemini(texts, is_query=is_query)
        return np.vstack([self._hash_vector(text) for text in texts]).astype("float32")

    def _encode_openai(self, texts: list[str]) -> np.ndarray:
        assert self._client is not None
        vectors: list[list[float]] = []
        try:
            for batch in self._batches(texts):
                response = self._request_with_retry(
                    lambda: self._client.embeddings.create(
                        model=self.model_name,
                        input=batch,
                        dimensions=self.dimension,
                        encoding_format="float",
                    )
                )
                data = list(getattr(response, "data", []))
                data.sort(key=lambda item: int(getattr(item, "index", 0)))
                vectors.extend(list(item.embedding) for item in data)
        except Exception as exc:
            raise EmbeddingUnavailableError(
                f"OpenAI embedding request failed ({type(exc).__name__})"
            ) from exc
        return self._validated_vectors(vectors, len(texts))

    def _encode_gemini(self, texts: list[str], *, is_query: bool) -> np.ndarray:
        assert self._client is not None
        vectors: list[list[float]] = []
        try:
            for batch in self._batches(texts):
                prepared = [self._gemini_retrieval_text(text, is_query) for text in batch]
                if self._gemini_types is None:
                    contents: Any = prepared
                    config: Any = {"output_dimensionality": self.dimension}
                else:
                    contents = [
                        self._gemini_types.Content(
                            parts=[self._gemini_types.Part.from_text(text=text)]
                        )
                        for text in prepared
                    ]
                    config = self._gemini_types.EmbedContentConfig(
                        output_dimensionality=self.dimension
                    )
                response = self._request_with_retry(
                    lambda: self._client.models.embed_content(
                        model=self.model_name,
                        contents=contents,
                        config=config,
                    )
                )
                vectors.extend(
                    list(item.values) for item in getattr(response, "embeddings", [])
                )
        except Exception as exc:
            raise EmbeddingUnavailableError(
                f"Gemini embedding request failed ({type(exc).__name__})"
            ) from exc
        return self._validated_vectors(vectors, len(texts))

    def _validated_vectors(
        self,
        vectors: list[list[float]],
        expected_count: int,
    ) -> np.ndarray:
        if len(vectors) != expected_count:
            raise EmbeddingUnavailableError(
                "Embedding provider returned an unexpected number of vectors"
            )
        array = np.asarray(vectors, dtype="float32")
        if array.ndim != 2 or array.shape[1] != self.dimension:
            raise EmbeddingUnavailableError(
                "Embedding provider returned vectors with an unexpected dimension"
            )
        norms = np.linalg.norm(array, axis=1, keepdims=True)
        return np.divide(array, norms, out=np.zeros_like(array), where=norms != 0)

    def _request_with_retry(self, request: Callable[[], Any]) -> Any:
        """Retry only transient hosted-provider failures with a bounded delay."""

        for attempt in range(REMOTE_MAX_ATTEMPTS):
            try:
                return request()
            except Exception as exc:
                if attempt + 1 >= REMOTE_MAX_ATTEMPTS or not self._retryable(exc):
                    raise
                delay = self._retry_delay(exc, attempt)
                self._sleep(delay)
        raise AssertionError("unreachable")

    @staticmethod
    def _retryable(exc: Exception) -> bool:
        status = getattr(exc, "status_code", None)
        if status is None:
            response = getattr(exc, "response", None)
            status = getattr(response, "status_code", None)
        if status == 429 or (isinstance(status, int) and status >= 500):
            return True
        return isinstance(exc, (TimeoutError, ConnectionError)) or any(
            marker in type(exc).__name__.lower()
            for marker in ("timeout", "ratelimit", "connection")
        )

    @staticmethod
    def _retry_delay(exc: Exception, attempt: int) -> float:
        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", None)
        if headers:
            raw = headers.get("retry-after") or headers.get("Retry-After")
            try:
                return min(max(float(raw), 0.0) + 0.5, 60.0)
            except (TypeError, ValueError):
                pass
        match = RETRY_DELAY_RE.search(str(exc))
        if match:
            return min(float(match.group(1)) + 0.5, 60.0)
        return min(float(2 ** attempt), 20.0)

    @staticmethod
    def _batches(texts: list[str]) -> list[list[str]]:
        return [
            texts[start : start + REMOTE_BATCH_SIZE]
            for start in range(0, len(texts), REMOTE_BATCH_SIZE)
        ]

    def _gemini_retrieval_text(self, text: str, is_query: bool) -> str:
        if self.model_name != "gemini-embedding-2":
            return text
        instruction = (
            "Find Calder County policy clauses that answer this benefits question:"
            if is_query
            else "Represent this Calder County benefits policy clause for retrieval:"
        )
        return f"{instruction}\n{text}"

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
