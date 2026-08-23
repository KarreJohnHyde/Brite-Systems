"""Capability, credential, and artifact routing for the Streamlit runtime."""

from __future__ import annotations

import re
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Mapping

from config.settings import DEFAULT_EMBEDDING_MODELS, Settings


EMBEDDING_BACKENDS = ("hashing", "sentence-transformers", "openai", "gemini")
ANSWER_PROVIDERS = ("deterministic", "gemini", "openai", "anthropic", "llama")
LOCAL_EMBEDDING_BACKENDS = frozenset({"hashing", "sentence-transformers"})

EMBEDDING_DISTRIBUTIONS = {
    "sentence-transformers": "sentence-transformers",
    "openai": "openai",
    "gemini": "google-genai",
}
ANSWER_DISTRIBUTIONS = {
    "gemini": "google-genai",
    "openai": "openai",
    "anthropic": "anthropic",
    "llama": "groq",
}
ANSWER_KEY_FIELDS = {
    "gemini": "gemini_api_key",
    "openai": "openai_api_key",
    "anthropic": "anthropic_api_key",
    "llama": "llama_api_key",
}
ANSWER_MODEL_FIELDS = {
    "gemini": "gemini_model",
    "openai": "openai_model",
    "anthropic": "anthropic_model",
    "llama": "llama_model",
}


def _distribution_available(distribution_name: str) -> bool:
    try:
        version(distribution_name)
        return True
    except PackageNotFoundError:
        return False


def available_embedding_backends() -> list[str]:
    """Return embedding backends whose SDK is installed in this runtime."""

    available = ["hashing"]
    for backend in EMBEDDING_BACKENDS[1:]:
        distribution = EMBEDDING_DISTRIBUTIONS[backend]
        if _distribution_available(distribution):
            available.append(backend)
    return available


def available_answer_providers() -> list[str]:
    """Return phrasing providers whose SDK is installed in this runtime."""

    available = ["deterministic"]
    for provider in ANSWER_PROVIDERS[1:]:
        distribution = ANSWER_DISTRIBUTIONS[provider]
        if _distribution_available(distribution):
            available.append(provider)
    return available


def langsmith_available() -> bool:
    """Return whether optional content-redacted tracing can be enabled."""

    return _distribution_available("langsmith")


def answer_provider_key(settings: Settings, provider: str) -> str | None:
    """Return the configured key for an answer provider, if it needs one."""

    field = ANSWER_KEY_FIELDS.get(provider)
    if field is None:
        return None
    value = getattr(settings, field, None)
    return str(value).strip() if value else None


def _artifact_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-._")
    return slug[:96] or "default"


def build_runtime_settings(
    embedding_backend: str,
    answer_provider: str,
    *,
    project_root: str | Path | None = None,
    api_keys: Mapping[str, str | None] | None = None,
    embedding_model: str | None = None,
    answer_model: str | None = None,
    embedding_dimension: int | None = None,
    langsmith_tracing: bool | None = None,
    langsmith_api_key: str | None = None,
    langsmith_project: str | None = None,
) -> Settings:
    """Build validated settings and isolate indexes by backend/model/dimension."""

    if embedding_backend not in EMBEDDING_BACKENDS:
        raise ValueError(f"Unsupported embedding backend: {embedding_backend}")
    if answer_provider not in ANSWER_PROVIDERS:
        raise ValueError(f"Unsupported answer provider: {answer_provider}")

    settings = Settings.from_env(
        project_root=project_root,
        embedding_backend=embedding_backend,
        llm_provider=answer_provider,
    )
    updates: dict[str, object] = {
        "embedding_model": (
            embedding_model
            or DEFAULT_EMBEDDING_MODELS[embedding_backend]
        ).strip(),
    }
    if not updates["embedding_model"]:
        raise ValueError("Embedding model name must not be empty")
    if embedding_dimension is not None:
        updates["embedding_dimension"] = embedding_dimension

    if answer_model is not None and answer_provider != "deterministic":
        normalized_model = answer_model.strip()
        if not normalized_model:
            raise ValueError("Answer model name must not be empty")
        updates[ANSWER_MODEL_FIELDS[answer_provider]] = normalized_model

    for provider, value in (api_keys or {}).items():
        field = ANSWER_KEY_FIELDS.get(provider)
        if field is not None:
            updates[field] = value.strip() if value and value.strip() else None

    if langsmith_tracing is not None:
        updates["langsmith_tracing"] = langsmith_tracing
    if langsmith_api_key is not None:
        updates["langsmith_api_key"] = (
            langsmith_api_key.strip() if langsmith_api_key.strip() else None
        )
    if langsmith_project is not None:
        normalized_project = langsmith_project.strip()
        if not normalized_project:
            raise ValueError("LangSmith project name must not be empty")
        updates["langsmith_project"] = normalized_project

    settings = Settings.model_validate({**settings.model_dump(), **updates})
    index_root = settings.index_dir
    if index_root.name in EMBEDDING_BACKENDS:
        index_root = index_root.parent
    elif index_root.parent.name in EMBEDDING_BACKENDS:
        index_root = index_root.parent.parent

    if embedding_backend in LOCAL_EMBEDDING_BACKENDS:
        selected_index = index_root / embedding_backend
    else:
        model_slug = _artifact_slug(settings.embedding_model)
        selected_index = (
            index_root
            / embedding_backend
            / f"{model_slug}-{settings.embedding_dimension}d"
        )
    return Settings.model_validate(
        {**settings.model_dump(), "index_dir": selected_index.resolve()}
    )
