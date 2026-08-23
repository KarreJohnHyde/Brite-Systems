from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import numpy as np
import pytest

from evaluation.evaluate import run_evaluation
from src.pipeline import ingest_corpus


def _single_question_file(project_root: Path, target: Path) -> Path:
    questions = json.loads(
        (project_root / "evaluation" / "questions.json").read_text(encoding="utf-8")
    )
    target.write_text(json.dumps([questions[0]]), encoding="utf-8")
    return target


def test_evaluation_only_uses_configured_reranker_when_opted_in(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    project_root: Path,
    pipeline_settings,
) -> None:
    ingest_corpus(pipeline_settings)
    questions = _single_question_file(project_root, tmp_path / "questions.json")
    fake_module = types.ModuleType("sentence_transformers")

    class PredictableCrossEncoder:
        def __init__(self, model_name: str) -> None:
            self.model_name = model_name

        @staticmethod
        def predict(pairs):
            return np.zeros(len(pairs), dtype="float32")

    fake_module.CrossEncoder = PredictableCrossEncoder
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    configured = pipeline_settings.model_copy(
        update={"enable_reranking": True, "require_reranker": True}
    )

    default_report = run_evaluation(
        settings=configured,
        questions_path=questions,
        output_dir=tmp_path / "default",
        quiet=True,
    )
    reranked_report = run_evaluation(
        settings=configured,
        questions_path=questions,
        output_dir=tmp_path / "reranked",
        quiet=True,
        respect_reranking=True,
    )

    assert default_report["configuration"]["reranking"] is False
    assert default_report["configuration"]["reranker_loaded"] is False
    assert reranked_report["configuration"]["reranking"] is True
    assert reranked_report["configuration"]["reranker_required"] is True
    assert reranked_report["configuration"]["reranker_loaded"] is True
