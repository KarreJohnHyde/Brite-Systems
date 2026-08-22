"""
FAISS-based vector store for policy clause retrieval.

Stores clause embeddings and metadata, supports save/load to disk,
and provides semantic search over the policy manual.
"""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Optional

import faiss
import numpy as np

from src.parser import PolicyClause


class VectorStore:
    """FAISS vector index with clause metadata storage."""

    def __init__(self, dimension: int):
        self.dimension = dimension
        self.index: Optional[faiss.Index] = None
        self.clauses: list[PolicyClause] = []

    def build(self, embeddings: np.ndarray, clauses: list[PolicyClause]):
        """
        Build the FAISS index from embeddings and store clause metadata.
        
        Uses IndexFlatIP (inner product) because embeddings are L2-normalized,
        so inner product = cosine similarity.
        """
        assert len(embeddings) == len(clauses), \
            f"Mismatch: {len(embeddings)} embeddings vs {len(clauses)} clauses"
        assert embeddings.shape[1] == self.dimension, \
            f"Dimension mismatch: got {embeddings.shape[1]}, expected {self.dimension}"

        self.index = faiss.IndexFlatIP(self.dimension)
        self.index.add(embeddings)
        self.clauses = clauses

    def search(self, query_embedding: np.ndarray, k: int = 10) -> list[tuple[PolicyClause, float]]:
        """
        Search for the k most similar clauses to the query.
        
        Returns: list of (clause, score) tuples, sorted by descending score.
        Score is cosine similarity (0 to 1 for normalized vectors).
        """
        if self.index is None:
            raise RuntimeError("Index not built. Call build() or load() first.")

        scores, indices = self.index.search(query_embedding, k)
        
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx >= 0:  # FAISS returns -1 for missing results
                results.append((self.clauses[idx], float(score)))
        
        return results

    def save(self, directory: str | Path):
        """Save the FAISS index and clause metadata to disk."""
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)

        # Save FAISS index
        faiss.write_index(self.index, str(directory / "index.faiss"))

        # Save clause metadata as JSON
        metadata = {
            "dimension": self.dimension,
            "num_clauses": len(self.clauses),
            "clauses": [asdict(c) for c in self.clauses],
        }
        with open(directory / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

    def load(self, directory: str | Path):
        """Load a previously saved FAISS index and clause metadata."""
        directory = Path(directory)

        # Load FAISS index
        index_path = directory / "index.faiss"
        if not index_path.exists():
            raise FileNotFoundError(f"No FAISS index found at {index_path}")
        self.index = faiss.read_index(str(index_path))

        # Load clause metadata
        metadata_path = directory / "metadata.json"
        with open(metadata_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        self.dimension = metadata["dimension"]
        self.clauses = [
            PolicyClause(**c) for c in metadata["clauses"]
        ]

    @property
    def is_ready(self) -> bool:
        """Check if the index is built/loaded and ready for search."""
        return self.index is not None and len(self.clauses) > 0
