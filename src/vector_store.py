"""Persisted FAISS index with validated, trusted chunk metadata."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from src.models import PolicyChunk


class IndexIntegrityError(RuntimeError):
    """Raised when an index and its metadata cannot be trusted together."""


class VectorStore:
    """Cosine-similarity vector store backed by FAISS IndexFlatIP."""

    INDEX_NAME = "policy.faiss"
    METADATA_NAME = "metadata.json"
    MANIFEST_NAME = "manifest.json"

    def __init__(self, dimension: int) -> None:
        self.dimension = dimension
        self.index: Any | None = None
        self.chunks: list[PolicyChunk] = []
        self.manifest: dict[str, Any] = {}

    # Compatibility alias for the original prototype.
    @property
    def clauses(self) -> list[PolicyChunk]:
        return self.chunks

    def build(
        self,
        embeddings: np.ndarray,
        chunks: list[PolicyChunk],
        *,
        embedding_backend: str = "unknown",
        embedding_model: str = "unknown",
        embedding_artifact_sha256: str | None = None,
        corpus_sha256: str | None = None,
    ) -> None:
        if embeddings.ndim != 2:
            raise ValueError("Embeddings must be a two-dimensional matrix")
        if len(embeddings) != len(chunks):
            raise ValueError(f"Embedding/chunk mismatch: {len(embeddings)} != {len(chunks)}")
        if embeddings.shape[1] != self.dimension:
            raise ValueError(f"Embedding dimension {embeddings.shape[1]} != configured {self.dimension}")
        if not np.isfinite(embeddings).all():
            raise ValueError("Embeddings contain NaN or infinite values")
        if embedding_artifact_sha256 is not None and (
            len(embedding_artifact_sha256) != 64
            or any(character not in "0123456789abcdef" for character in embedding_artifact_sha256)
        ):
            raise ValueError("Embedding artifact digest must be a lowercase SHA-256 hex string")

        try:
            import faiss
        except ImportError as exc:
            raise RuntimeError("faiss-cpu is required to build the persisted policy index") from exc

        self.index = faiss.IndexFlatIP(self.dimension)
        self.index.add(np.ascontiguousarray(embeddings, dtype="float32"))
        self.chunks = list(chunks)
        self.manifest = {
            "schema_version": 3,
            "index_type": "IndexFlatIP",
            "metric": "cosine_via_normalized_inner_product",
            "dimension": self.dimension,
            "chunks": len(chunks),
            "embedding_backend": embedding_backend,
            "embedding_model": embedding_model,
            "corpus_sha256": corpus_sha256,
        }
        if embedding_artifact_sha256 is not None:
            self.manifest["embedding_artifact_sha256"] = embedding_artifact_sha256

    def search(self, query_embedding: np.ndarray, k: int = 10) -> list[tuple[PolicyChunk, float]]:
        if self.index is None or not self.chunks:
            raise RuntimeError("Index is not loaded. Run `python main.py ingest` first.")
        if query_embedding.shape != (1, self.dimension):
            raise ValueError(
                f"Query embedding shape {query_embedding.shape} does not match (1, {self.dimension})"
            )
        k = min(max(1, k), len(self.chunks))
        scores, indices = self.index.search(np.ascontiguousarray(query_embedding, dtype="float32"), k)
        return [
            (self.chunks[int(index)], float(score))
            for score, index in zip(scores[0], indices[0])
            if index >= 0
        ]

    def save(self, directory: str | Path) -> None:
        if self.index is None or not self.chunks or not self.manifest:
            raise RuntimeError("Cannot save an unbuilt vector store")
        try:
            import faiss
        except ImportError as exc:
            raise RuntimeError("faiss-cpu is required to save the index") from exc

        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        index_path = target / self.INDEX_NAME
        metadata_path = target / self.METADATA_NAME
        faiss.write_index(self.index, str(index_path))
        metadata_bytes = (
            json.dumps(
                [chunk.model_dump(mode="json") for chunk in self.chunks],
                indent=2,
                ensure_ascii=False,
            )
            + "\n"
        ).encode("utf-8")
        metadata_path.write_bytes(metadata_bytes)
        self.manifest.update(
            {
                "index_sha256": hashlib.sha256(index_path.read_bytes()).hexdigest(),
                "metadata_sha256": hashlib.sha256(metadata_bytes).hexdigest(),
            }
        )
        (target / self.MANIFEST_NAME).write_text(
            json.dumps(self.manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def load(self, directory: str | Path) -> None:
        try:
            import faiss
        except ImportError as exc:
            raise RuntimeError("faiss-cpu is required to load the index") from exc

        target = Path(directory)
        required = [target / self.INDEX_NAME, target / self.METADATA_NAME, target / self.MANIFEST_NAME]
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            raise FileNotFoundError(
                "Policy index is incomplete. Missing: " + ", ".join(missing) + ". Run `python main.py ingest`."
            )
        try:
            manifest = json.loads((target / self.MANIFEST_NAME).read_text(encoding="utf-8"))
            metadata_bytes = (target / self.METADATA_NAME).read_bytes()
            metadata = json.loads(metadata_bytes.decode("utf-8"))
            chunks = [PolicyChunk.model_validate(item) for item in metadata]
            index = faiss.read_index(str(target / self.INDEX_NAME))
        except Exception as exc:
            raise IndexIntegrityError(f"Could not validate policy index in {target}: {exc}") from exc

        dimension = int(manifest.get("dimension", -1))
        expected_count = int(manifest.get("chunks", -1))
        if manifest.get("schema_version") != 3:
            raise IndexIntegrityError("Unsupported index schema; rebuild with `python main.py ingest`")
        if dimension != index.d or dimension != self.dimension:
            raise IndexIntegrityError(
                f"Index dimension mismatch (manifest={dimension}, index={index.d}, engine={self.dimension})"
            )
        if expected_count != index.ntotal or expected_count != len(chunks):
            raise IndexIntegrityError(
                f"Index count mismatch (manifest={expected_count}, index={index.ntotal}, metadata={len(chunks)})"
            )
        if len({chunk.chunk_id for chunk in chunks}) != len(chunks):
            raise IndexIntegrityError("Duplicate trusted chunk IDs in index metadata")
        actual_metadata_hash = hashlib.sha256(metadata_bytes).hexdigest()
        actual_index_hash = hashlib.sha256((target / self.INDEX_NAME).read_bytes()).hexdigest()
        if manifest.get("metadata_sha256") != actual_metadata_hash:
            raise IndexIntegrityError("Policy metadata checksum mismatch; rebuild with `python main.py ingest`")
        if manifest.get("index_sha256") != actual_index_hash:
            raise IndexIntegrityError("FAISS index checksum mismatch; rebuild with `python main.py ingest`")

        self.index = index
        self.chunks = chunks
        self.manifest = manifest

    @property
    def is_ready(self) -> bool:
        return self.index is not None and bool(self.chunks)
