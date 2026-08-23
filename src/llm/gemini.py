"""Google Gemini implementation of the structured LLM provider interface."""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any, Literal

from pydantic import ValidationError

from src.llm.base import LLMProvider, LLMProviderError
from src.llm.prompts import (
    build_coverage_gate_prompt,
    build_generation_selection_prompt,
)
from src.models import CoverageGateResult, GenerationSelection, PolicyChunk

DEFAULT_GEMINI_MODEL = "gemini-3.6-flash"


class GeminiProvider(LLMProvider):
    """Generate citation selections through Gemini's JSON schema output."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = DEFAULT_GEMINI_MODEL,
        thinking_level: Literal["minimal", "low", "medium", "high"] = "minimal",
        client: Any | None = None,
    ) -> None:
        self.model = model.strip()
        if not self.model:
            raise LLMProviderError("Gemini model name must not be empty")
        self.thinking_level = thinking_level

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

    def evaluate_coverage(
        self,
        question: str,
        contexts: Sequence[PolicyChunk],
    ) -> CoverageGateResult:
        """Call the Coverage Gate LLM prompt and return a structured assessment."""
        if not contexts:
            return CoverageGateResult(
                covered=False,
                confidence=1.0,
                matched_clause_ids=[],
                uncovered_aspect="No clauses were retrieved.",
            )

        prompt = build_coverage_gate_prompt(question, contexts)
        
        try:
            generation_config = {
                "temperature": 0.0,
                "max_output_tokens": 1024,
                "response_mime_type": "application/json",
                "response_schema": CoverageGateResult,
            }
            if self.model.startswith("gemini-3"):
                generation_config["thinking_config"] = {
                    "thinking_level": self.thinking_level
                }
            response = self._client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=generation_config,
            )
        except Exception as exc:
            raise LLMProviderError(
                f"Gemini generation request failed ({type(exc).__name__})"
            ) from exc

        return self._parse_coverage_response(response)

    def generate_answer(
        self,
        question: str,
        contexts: Sequence[PolicyChunk],
    ) -> GenerationSelection:
        """Generate structured phrasing whose opaque source IDs can be validated."""
        prompt = build_generation_selection_prompt(question, contexts)
        
        try:
            generation_config = {
                "temperature": 0.0,
                "max_output_tokens": 2048,
                "response_mime_type": "application/json",
                "response_schema": GenerationSelection,
            }
            if self.model.startswith("gemini-3"):
                generation_config["thinking_config"] = {
                    "thinking_level": self.thinking_level
                }
            response = self._client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=generation_config,
            )
            return self._parse_generation_response(response)
        except Exception as exc:
            raise LLMProviderError(
                f"Gemini generation request failed ({type(exc).__name__})"
            ) from exc

    @staticmethod
    def _parse_generation_response(response: Any) -> GenerationSelection:
        try:
            parsed = getattr(response, "parsed", None)
            if isinstance(parsed, GenerationSelection):
                return parsed
            if parsed is not None:
                return GenerationSelection.model_validate(parsed)

            response_text = getattr(response, "text", None)
            if not isinstance(response_text, str) or not response_text.strip():
                raise LLMProviderError("Gemini returned no structured answer")
            return GenerationSelection.model_validate_json(response_text)
        except LLMProviderError:
            raise
        except (ValidationError, TypeError, ValueError) as exc:
            raise LLMProviderError("Gemini returned invalid answer JSON") from exc
        except Exception as exc:
            raise LLMProviderError(
                f"Gemini answer parsing failed ({type(exc).__name__})"
            ) from exc

    @staticmethod
    def _parse_coverage_response(response: Any) -> CoverageGateResult:
        """Validate either Gemini's parsed object or its JSON text fallback."""
        try:
            parsed = getattr(response, "parsed", None)
            if isinstance(parsed, CoverageGateResult):
                return parsed
            if parsed is not None:
                return CoverageGateResult.model_validate(parsed)

            response_text = getattr(response, "text", None)
            if not isinstance(response_text, str) or not response_text.strip():
                raise LLMProviderError("Gemini returned no structured response")
            return CoverageGateResult.model_validate_json(response_text)
        except LLMProviderError:
            raise
        except (ValidationError, TypeError, ValueError) as exc:
            raise LLMProviderError("Gemini returned invalid structured JSON") from exc
        except Exception as exc:
            raise LLMProviderError(
                f"Gemini response parsing failed ({type(exc).__name__})"
            ) from exc
