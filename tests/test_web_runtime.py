"""Runtime capability and backend artifact routing tests."""

from __future__ import annotations

from pathlib import Path

from src.web_runtime import (
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


def test_runtime_options_are_capability_gated(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", " ")
    settings = build_runtime_settings("hashing", "deterministic")

    assert "hashing" in available_embedding_backends()
    assert available_answer_providers(settings) == ["deterministic"]
