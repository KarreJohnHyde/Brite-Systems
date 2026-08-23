"""Capability and artifact routing for the Streamlit runtime selectors."""

from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path

from config.settings import Settings


EMBEDDING_BACKENDS = ("hashing", "sentence-transformers")
ANSWER_PROVIDERS = ("deterministic", "gemini")


def _module_available(module_name: str) -> bool:
    try:
        return find_spec(module_name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def available_embedding_backends() -> list[str]:
    """Return only embedding backends that this installation can execute."""

    available = ["hashing"]
    if _module_available("sentence_transformers"):
        available.append("sentence-transformers")
    return available


def available_answer_providers(settings: Settings) -> list[str]:
    """Return providers with both their package and credentials available."""

    available = ["deterministic"]
    api_key = (settings.gemini_api_key or "").strip()
    if api_key and _module_available("google.genai"):
        available.append("gemini")
    return available


def build_runtime_settings(
    embedding_backend: str,
    answer_provider: str,
    *,
    project_root: str | Path | None = None,
) -> Settings:
    """Build settings with a separate, persistent index per embedding backend."""

    if embedding_backend not in EMBEDDING_BACKENDS:
        raise ValueError(f"Unsupported embedding backend: {embedding_backend}")
    if answer_provider not in ANSWER_PROVIDERS:
        raise ValueError(f"Unsupported answer provider: {answer_provider}")

    settings = Settings.from_env(
        project_root=project_root,
        embedding_backend=embedding_backend,
        llm_provider=answer_provider,
    )
    index_root = settings.index_dir
    if index_root.name in EMBEDDING_BACKENDS:
        index_root = index_root.parent
    return settings.model_copy(
        update={"index_dir": (index_root / embedding_backend).resolve()}
    )
