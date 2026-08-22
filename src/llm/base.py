"""Provider-neutral interface for structured policy generation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from src.models import GenerationSelection, PolicyChunk


class LLMProviderError(RuntimeError):
    """Raised when an LLM provider cannot return a trustworthy selection."""


class LLMProvider(ABC):
    """Interface implemented by optional structured-generation providers."""

    @abstractmethod
    def generate_structured(
        self,
        question: str,
        contexts: Sequence[PolicyChunk],
    ) -> GenerationSelection:
        """Return a validated selection grounded only in ``contexts``."""
        raise LLMProviderError("An abstract LLM provider cannot generate a response")
