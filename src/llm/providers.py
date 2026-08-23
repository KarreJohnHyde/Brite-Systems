"""Structured answer providers for OpenAI, Anthropic, and Llama via Groq."""

from __future__ import annotations

import os
from abc import abstractmethod
from collections.abc import Sequence
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from src.llm.base import LLMProvider, LLMProviderError
from src.llm.prompts import (
    build_coverage_gate_prompt,
    build_generation_selection_prompt,
)
from src.models import CoverageGateResult, GenerationSelection, PolicyChunk


StructuredResult = TypeVar("StructuredResult", bound=BaseModel)


def _validated_result(
    response_model: type[StructuredResult],
    value: Any,
    provider_name: str,
) -> StructuredResult:
    """Coerce an SDK parsed object or JSON string into the required model."""

    try:
        if isinstance(value, response_model):
            return value
        if isinstance(value, str):
            if not value.strip():
                raise ValueError("empty response")
            return response_model.model_validate_json(value)
        if value is None:
            raise ValueError("missing parsed response")
        return response_model.model_validate(value)
    except (ValidationError, TypeError, ValueError) as exc:
        raise LLMProviderError(
            f"{provider_name} returned invalid structured JSON"
        ) from exc


class StructuredPromptProvider(LLMProvider):
    """Shared policy prompt flow for SDKs with structured output support."""

    provider_name = "Model provider"

    def evaluate_coverage(
        self,
        question: str,
        contexts: Sequence[PolicyChunk],
    ) -> CoverageGateResult:
        if not contexts:
            return CoverageGateResult(
                covered=False,
                confidence=1.0,
                matched_clause_ids=[],
                uncovered_aspect="No clauses were retrieved.",
            )
        prompt = build_coverage_gate_prompt(question, contexts)
        return self._safe_request(prompt, CoverageGateResult)

    def generate_answer(
        self,
        question: str,
        contexts: Sequence[PolicyChunk],
    ) -> GenerationSelection:
        prompt = build_generation_selection_prompt(question, contexts)
        return self._safe_request(prompt, GenerationSelection)

    def _safe_request(
        self,
        prompt: str,
        response_model: type[StructuredResult],
    ) -> StructuredResult:
        try:
            return self._request_structured(prompt, response_model)
        except LLMProviderError:
            raise
        except Exception as exc:
            raise LLMProviderError(
                f"{self.provider_name} generation request failed ({type(exc).__name__})"
            ) from exc

    @abstractmethod
    def _request_structured(
        self,
        prompt: str,
        response_model: type[StructuredResult],
    ) -> StructuredResult:
        raise NotImplementedError


class OpenAIProvider(StructuredPromptProvider):
    """OpenAI Responses API provider using Pydantic structured outputs."""

    provider_name = "OpenAI"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "gpt-5-mini",
        client: Any | None = None,
    ) -> None:
        self.model = model.strip()
        if not self.model:
            raise LLMProviderError("OpenAI model name must not be empty")
        if client is not None:
            self._client = client
            return

        resolved_key = (api_key or os.getenv("OPENAI_API_KEY") or "").strip()
        if not resolved_key:
            raise LLMProviderError("OpenAI API key is missing")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise LLMProviderError("OpenAI provider requires the openai package") from exc
        self._client = OpenAI(api_key=resolved_key)

    def _request_structured(
        self,
        prompt: str,
        response_model: type[StructuredResult],
    ) -> StructuredResult:
        response = self._client.responses.parse(
            model=self.model,
            input=prompt,
            text_format=response_model,
        )
        value = getattr(response, "output_parsed", None)
        if value is None:
            value = getattr(response, "output_text", None)
        return _validated_result(response_model, value, self.provider_name)


class AnthropicProvider(StructuredPromptProvider):
    """Claude Messages API provider using Pydantic structured outputs."""

    provider_name = "Anthropic"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-6",
        client: Any | None = None,
    ) -> None:
        self.model = model.strip()
        if not self.model:
            raise LLMProviderError("Anthropic model name must not be empty")
        if client is not None:
            self._client = client
            return

        resolved_key = (api_key or os.getenv("ANTHROPIC_API_KEY") or "").strip()
        if not resolved_key:
            raise LLMProviderError("Anthropic API key is missing")
        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise LLMProviderError(
                "Anthropic provider requires the anthropic package"
            ) from exc
        self._client = Anthropic(api_key=resolved_key)

    def _request_structured(
        self,
        prompt: str,
        response_model: type[StructuredResult],
    ) -> StructuredResult:
        response = self._client.messages.parse(
            model=self.model,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
            output_format=response_model,
        )
        value = getattr(response, "parsed_output", None)
        if value is None:
            text_parts = [
                block.text
                for block in getattr(response, "content", [])
                if isinstance(getattr(block, "text", None), str)
            ]
            value = "".join(text_parts)
        return _validated_result(response_model, value, self.provider_name)


class GroqLlamaProvider(StructuredPromptProvider):
    """Llama provider hosted by Groq with validated JSON-schema output."""

    provider_name = "Llama via Groq"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "meta-llama/llama-4-scout-17b-16e-instruct",
        client: Any | None = None,
    ) -> None:
        self.model = model.strip()
        if not self.model:
            raise LLMProviderError("Llama model name must not be empty")
        if client is not None:
            self._client = client
            return

        resolved_key = (
            api_key
            or os.getenv("LLAMA_API_KEY")
            or os.getenv("GROQ_API_KEY")
            or ""
        ).strip()
        if not resolved_key:
            raise LLMProviderError("Groq API key for Llama is missing")
        try:
            from groq import Groq
        except ImportError as exc:
            raise LLMProviderError("Llama provider requires the groq package") from exc
        self._client = Groq(api_key=resolved_key)

    def _request_structured(
        self,
        prompt: str,
        response_model: type[StructuredResult],
    ) -> StructuredResult:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": response_model.__name__.lower(),
                    "strict": False,
                    "schema": response_model.model_json_schema(),
                },
            },
        )
        choices = getattr(response, "choices", None) or []
        value = (
            getattr(getattr(choices[0], "message", None), "content", None)
            if choices
            else None
        )
        return _validated_result(response_model, value, self.provider_name)
