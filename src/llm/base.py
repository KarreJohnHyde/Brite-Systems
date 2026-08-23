"""Provider-neutral interface for structured policy generation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from src.models import CoverageGateResult, GenerationSelection, PolicyChunk


class LLMProviderError(RuntimeError):
    """Raised when an LLM provider cannot return a trustworthy selection."""


class LLMProvider(ABC):
    """Interface implemented by optional structured-generation providers."""

    @abstractmethod
    def evaluate_coverage(
        self,
        question: str,
        contexts: Sequence[PolicyChunk],
    ) -> CoverageGateResult:
        """Evaluate if the retrieved contexts can answer the question."""
        raise LLMProviderError("An abstract LLM provider cannot generate a response")

    @abstractmethod
    def generate_answer(
        self,
        question: str,
        contexts: Sequence[PolicyChunk],
    ) -> GenerationSelection:
        """Return citation-selectable phrasing without changing the decision."""
        raise LLMProviderError("An abstract LLM provider cannot generate a response")
