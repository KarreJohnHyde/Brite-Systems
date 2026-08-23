from __future__ import annotations

from contextlib import contextmanager

import pytest

from config.settings import Settings
from src.models import Decision
from src.observability import PipelineTracer, TraceSpan, safe_trace_payload
from src.pipeline import GroundedAnswerPipeline


def test_trace_payload_strictly_excludes_content() -> None:
    payload = safe_trace_payload(
        {
            "question": "private question",
            "answer": "private answer",
            "excerpt": "policy text",
            "reason": "private rationale",
            "question_characters": 16,
            "decision": "ANSWER",
            "citation_clause_ids": ["2.4.1"],
        }
    )

    assert payload == {
        "question_characters": 16,
        "decision": "ANSWER",
        "citation_clause_ids": ["2.4.1"],
    }


def test_disabled_tracer_is_a_noop(pipeline_settings) -> None:
    tracer = PipelineTracer(pipeline_settings)

    with tracer.query(
        "private question",
        include_debug_trace=False,
        embedding_backend="hashing",
        answer_provider="deterministic",
        model="deterministic",
    ) as span:
        assert isinstance(span, TraceSpan)
        span.end({"answer": "private answer", "decision": "ANSWER"})

    tracer.flush()


def test_settings_accept_legacy_langchain_key_alias(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.setenv("LANGCHAIN_API_KEY", "legacy-test-key")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")

    settings = Settings.from_env(project_root=tmp_path)

    assert settings.langsmith_tracing is True
    assert settings.langsmith_api_key == "legacy-test-key"


def test_enabled_tracing_requires_a_key() -> None:
    settings = Settings(langsmith_tracing=True, langsmith_api_key=None)

    with pytest.raises(RuntimeError, match="no API key"):
        PipelineTracer(settings)


class RecordingSpan:
    def __init__(self, event: dict) -> None:
        self.event = event

    def end(self, outputs: dict) -> None:
        self.event["outputs"] = outputs


class RecordingTracer:
    def __init__(self) -> None:
        self.events: list[dict] = []

    @contextmanager
    def query(self, question: str, **metadata):
        event = {"name": "query", "question_length": len(question), "metadata": metadata}
        self.events.append(event)
        yield RecordingSpan(event)

    @contextmanager
    def span(self, name: str, run_type: str, inputs=None):
        event = {"name": name, "run_type": run_type, "inputs": inputs or {}}
        self.events.append(event)
        yield RecordingSpan(event)

    def flush(self, timeout: float = 10.0) -> None:
        return None


def test_pipeline_emits_safe_diagnostic_spans(
    pipeline_settings,
    hashing_engine,
    vector_store,
) -> None:
    tracer = RecordingTracer()
    pipeline = GroundedAnswerPipeline(
        pipeline_settings,
        hashing_engine,
        vector_store,
        tracer=tracer,
    )

    answer = pipeline.ask("What is the household resource limit?")

    assert answer.decision == Decision.ANSWER
    assert [event["name"] for event in tracer.events] == [
        "query",
        "temporal-applicability",
        "retrieve-policy-evidence",
        "decide-answer-state",
        "build-validated-answer",
    ]
    serialized = repr(tracer.events)
    assert "What is the household resource limit?" not in serialized
    assert answer.answer not in serialized
    assert "decision" in serialized
    assert "citation_clause_ids" in serialized
