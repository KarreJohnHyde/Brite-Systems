"""Runtime capability and backend artifact routing tests."""

from __future__ import annotations

from pathlib import Path

import src.web_runtime as web_runtime
from src.web_runtime import (
    answer_provider_key,
    available_answer_providers,
    available_embedding_backends,
    build_runtime_settings,
)


def test_each_embedding_backend_gets_a_separate_index(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("INDEX_DIR", str(tmp_path / "indexes"))

    hashing = build_runtime_settings("hashing", "deterministic")
    semantic = build_runtime_settings("sentence-transformers", "deterministic")

    assert hashing.index_dir == (tmp_path / "indexes" / "hashing").resolve()
    assert semantic.index_dir == (
        tmp_path / "indexes" / "sentence-transformers"
    ).resolve()


def test_backend_specific_index_env_resolves_to_sibling(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(
        "INDEX_DIR",
        str(tmp_path / "indexes" / "sentence-transformers"),
    )

    hashing = build_runtime_settings("hashing", "deterministic")

    assert hashing.index_dir == (tmp_path / "indexes" / "hashing").resolve()


def test_runtime_options_are_package_gated_not_key_gated(monkeypatch) -> None:
    installed = {
        "sentence-transformers",
        "google-genai",
        "openai",
        "anthropic",
        "groq",
    }
    monkeypatch.setattr(
        web_runtime,
        "_distribution_available",
        lambda distribution: distribution in installed,
    )

    assert available_embedding_backends() == [
        "hashing",
        "sentence-transformers",
        "openai",
        "gemini",
    ]
    assert available_answer_providers() == [
        "deterministic",
        "gemini",
        "openai",
        "anthropic",
        "llama",
    ]


def test_session_keys_models_and_remote_indexes_are_isolated(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("INDEX_DIR", str(tmp_path / "indexes"))
    settings = build_runtime_settings(
        "openai",
        "anthropic",
        api_keys={"openai": "openai-secret", "anthropic": "anthropic-secret"},
        embedding_model="text-embedding-3-small",
        embedding_dimension=1024,
        answer_model="claude-sonnet-4-6",
        langsmith_tracing=True,
        langsmith_api_key="trace-secret",
        langsmith_project="county-review",
    )

    assert settings.index_dir == (
        tmp_path
        / "indexes"
        / "openai"
        / "text-embedding-3-small-1024d"
    ).resolve()
    assert settings.embedding_api_key == "openai-secret"
    assert answer_provider_key(settings, "anthropic") == "anthropic-secret"
    assert settings.answer_model == "claude-sonnet-4-6"
    assert settings.langsmith_tracing is True
    assert settings.langsmith_project == "county-review"
    assert "openai-secret" not in repr(settings)
    assert "anthropic-secret" not in repr(settings)
    assert "trace-secret" not in repr(settings)
