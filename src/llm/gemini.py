"""Google Gemini implementation of the structured LLM provider interface."""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any

from pydantic import ValidationError

from src.llm.base import LLMProvider, LLMProviderError
from src.llm.prompts import SYSTEM_PROMPT, build_generation_prompt, source_ids
from src.models import Decision, GenerationSelection, PolicyChunk


DEFAULT_GEMINI_MODEL = "gemini-3.6-flash"


class GeminiProvider(LLMProvider):
    """Generate citation selections through Gemini's JSON schema output."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = DEFAULT_GEMINI_MODEL,
        client: Any | None = None,
    ) -> None:
        self.model = model.strip()
        if not self.model:
            raise LLMProviderError("Gemini model name must not be empty")

        if client is not None:
            self._client = client
            return

        resolved_key = (api_key or os.getenv("GEMINI_API_KEY") or "").strip()
        if not resolved_key:
            raise LLMProviderError(
                "Gemini API key is missing; set GEMINI_API_KEY or provide api_key explicitly"
            )

        try:
            from google import genai
        except ImportError as exc:
            raise LLMProviderError(
                "Gemini provider requires the optional google-genai package"
            ) from exc

        try:
            self._client = genai.Client(api_key=resolved_key)
        except Exception as exc:
            raise LLMProviderError(
                f"Gemini client initialization failed ({type(exc).__name__})"
            ) from exc

    def generate_structured(
        self,
        question: str,
        contexts: Sequence[PolicyChunk],
    ) -> GenerationSelection:
        """Request, parse, and source-validate one structured selection."""
        try:
            prompt = build_generation_prompt(question, contexts)
            allowed_ids = set(source_ids(contexts))
        except (TypeError, ValueError) as exc:
            raise LLMProviderError(f"Invalid Gemini generation input: {exc}") from exc

        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=prompt,
                config={
                    "system_instruction": SYSTEM_PROMPT,
                    "temperature": 0.0,
                    "max_output_tokens": 1024,
                    "response_mime_type": "application/json",
                    "response_schema": GenerationSelection,
                },
            )
        except Exception as exc:
            raise LLMProviderError(
                f"Gemini generation request failed ({type(exc).__name__})"
            ) from exc

        selection = self._parse_response(response)
        self._validate_selection(selection, allowed_ids)
        return selection

    @staticmethod
    def _parse_response(response: Any) -> GenerationSelection:
        """Validate either Gemini's parsed object or its JSON text fallback."""
        try:
            parsed = getattr(response, "parsed", None)
            if isinstance(parsed, GenerationSelection):
                return parsed
            if parsed is not None:
                return GenerationSelection.model_validate(parsed)

            response_text = getattr(response, "text", None)
            if not isinstance(response_text, str) or not response_text.strip():
                raise LLMProviderError("Gemini returned no structured response")
            return GenerationSelection.model_validate_json(response_text)
        except LLMProviderError:
            raise
        except (ValidationError, TypeError, ValueError) as exc:
            raise LLMProviderError("Gemini returned invalid structured JSON") from exc
        except Exception as exc:
            raise LLMProviderError(
                f"Gemini response parsing failed ({type(exc).__name__})"
            ) from exc

    @staticmethod
    def _validate_selection(
        selection: GenerationSelection,
        allowed_ids: set[str],
    ) -> None:
        """Enforce source allowlisting and decision-specific source counts."""
        selected_ids = selection.supporting_source_ids
        if len(selected_ids) != len(set(selected_ids)):
            raise LLMProviderError("Gemini returned duplicate supporting source IDs")

        unknown_ids = sorted(set(selected_ids) - allowed_ids)
        if unknown_ids:
            raise LLMProviderError(
                "Gemini selected source IDs that were not supplied in context"
            )

        if not selection.answer.strip() or not selection.reason.strip():
            raise LLMProviderError("Gemini returned an empty answer or reason")
        if selection.decision == Decision.ANSWER and not selected_ids:
            raise LLMProviderError("Gemini ANSWER requires at least one source ID")
        if selection.decision == Decision.CONFLICT and len(selected_ids) < 2:
            raise LLMProviderError("Gemini CONFLICT requires at least two source IDs")
        if selection.decision == Decision.REFUSE and selected_ids:
            raise LLMProviderError("Gemini REFUSE must not select supporting source IDs")
