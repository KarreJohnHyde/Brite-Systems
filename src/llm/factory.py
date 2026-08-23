"""Construct the optional structured answer provider selected in settings."""

from __future__ import annotations

from config.settings import Settings
from src.llm.base import LLMProvider


def build_llm_provider(settings: Settings) -> LLMProvider | None:
    """Create one provider without importing unused optional SDKs."""

    if settings.llm_provider == "deterministic":
        return None
    if settings.llm_provider == "gemini":
        from src.llm.gemini import GeminiProvider

        return GeminiProvider(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            thinking_level=settings.gemini_thinking_level,
        )
    if settings.llm_provider == "openai":
        from src.llm.providers import OpenAIProvider

        return OpenAIProvider(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
        )
    if settings.llm_provider == "anthropic":
        from src.llm.providers import AnthropicProvider

        return AnthropicProvider(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
        )
    if settings.llm_provider == "llama":
        from src.llm.providers import GroqLlamaProvider

        return GroqLlamaProvider(
            api_key=settings.llama_api_key,
            model=settings.llama_model,
        )
    raise ValueError(f"Unsupported answer provider: {settings.llm_provider}")
