from __future__ import annotations

from pathlib import Path

import pytest

from config.settings import Settings
from src.artifact_integrity import resolve_local_directory, sha256_directory
from src.pipeline import GroundedAnswerPipeline
from src.vector_store import IndexIntegrityError


def test_directory_sha256_is_stable_and_covers_names_and_contents(tmp_path: Path) -> None:
    artifact = tmp_path / "model"
    (artifact / "nested").mkdir(parents=True)
    (artifact / "config.json").write_text('{"model": "candidate"}', encoding="utf-8")
    weights = artifact / "nested" / "weights.bin"
    weights.write_bytes(b"weights-v1")

    first = sha256_directory(artifact)
    second = sha256_directory(artifact)

    assert first == second
    assert len(first) == 64

    weights.write_bytes(b"weights-v2")
    assert sha256_directory(artifact) != first

    weights.write_bytes(b"weights-v1")
    weights.rename(artifact / "nested" / "renamed.bin")
    assert sha256_directory(artifact) != first


def test_resolve_local_directory_distinguishes_paths_from_hub_ids(tmp_path: Path) -> None:
    artifact = tmp_path / "models" / "candidate"
    artifact.mkdir(parents=True)

    assert resolve_local_directory("models/candidate", base_dir=tmp_path) == artifact.resolve()
    assert (
        resolve_local_directory(
            "sentence-transformers/all-MiniLM-L6-v2",
            base_dir=tmp_path,
        )
        is None
    )


def test_pipeline_rejects_changed_local_embedding_artifact(
    tmp_path: Path,
    pipeline_settings,
) -> None:
    artifact = tmp_path / "candidate"
    artifact.mkdir()
    weights = artifact / "model.safetensors"
    weights.write_bytes(b"trusted")
    settings = pipeline_settings.model_copy(
        update={
            "embedding_backend": "sentence-transformers",
            "embedding_model": str(artifact),
        }
    )
    manifest = {"embedding_artifact_sha256": sha256_directory(artifact)}

    GroundedAnswerPipeline._validate_embedding_artifact(settings, manifest)

    weights.write_bytes(b"changed")
    with pytest.raises(IndexIntegrityError, match="differs from the model"):
        GroundedAnswerPipeline._validate_embedding_artifact(settings, manifest)


def test_pipeline_accepts_legacy_manifest_without_artifact_digest(
    pipeline_settings,
) -> None:
    GroundedAnswerPipeline._validate_embedding_artifact(pipeline_settings, {})


def test_require_reranker_setting_is_loaded_from_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("REQUIRE_RERANKER", "true")

    settings = Settings.from_env(project_root=tmp_path)

    assert settings.require_reranker is True
