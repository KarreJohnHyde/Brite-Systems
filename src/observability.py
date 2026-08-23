"""Privacy-preserving LangSmith tracing for the custom RAG pipeline."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator

from config.settings import Settings


LOGGER = logging.getLogger("grounded_answer.observability")

# Only these diagnostic fields may leave the process through LangSmith. Raw
# questions, answers, reasons, next steps, excerpts, and policy text are
# intentionally absent.
SAFE_TRACE_FIELDS = frozenset(
    {
        "answer_provider",
        "citation_clause_ids",
        "citation_count",
        "citation_validation",
        "clause_ids",
        "conflict_count",
        "decision",
        "embedding_backend",
        "error_type",
        "evidence_level",
        "include_debug_trace",
        "model",
        "privacy_mode",
        "question_characters",
        "question_words",
        "result_count",
        "status",
        "support_counts",
    }
)


def safe_trace_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a strict allowlist projection suitable for remote tracing."""

    safe: dict[str, Any] = {}
    for key, value in payload.items():
        if key not in SAFE_TRACE_FIELDS:
            continue
        if value is None or isinstance(value, (bool, int, float, str)):
            safe[key] = value
        elif isinstance(value, list) and all(
            item is None or isinstance(item, (bool, int, float, str)) for item in value
        ):
            safe[key] = value
        elif isinstance(value, dict) and all(
            isinstance(item_key, str)
            and (item_value is None or isinstance(item_value, (bool, int, float, str)))
            for item_key, item_value in value.items()
        ):
            safe[key] = value
    return safe


class TraceSpan:
    """Small wrapper that enforces output filtering before a run is ended."""

    def __init__(self, run: Any | None = None) -> None:
        self._run = run

    def end(self, outputs: dict[str, Any]) -> None:
        if self._run is not None:
            self._run.end(outputs=safe_trace_payload(outputs))


class PipelineTracer:
    """Optional standalone LangSmith client with content-free trace payloads."""

    def __init__(self, settings: Settings) -> None:
        self.enabled = settings.langsmith_tracing
        self.project = settings.langsmith_project
        self._client: Any | None = None
        self._langsmith: Any | None = None

        if not self.enabled:
            return
        if not settings.langsmith_api_key:
            raise RuntimeError(
                "LangSmith tracing is enabled but no API key is configured; "
                "set LANGSMITH_API_KEY (or legacy LANGCHAIN_API_KEY)"
            )

        try:
            import langsmith as ls
        except ImportError as exc:
            raise RuntimeError(
                "LangSmith tracing requires `python -m pip install -r requirements-tracing.txt`"
            ) from exc

        self._langsmith = ls
        self._client = ls.Client(
            api_key=settings.langsmith_api_key,
            api_url=settings.langsmith_endpoint,
            workspace_id=settings.langsmith_workspace_id,
            hide_inputs=safe_trace_payload,
            hide_outputs=safe_trace_payload,
            hide_metadata=safe_trace_payload,
            omit_traced_runtime_info=True,
        )

    @contextmanager
    def query(
        self,
        question: str,
        *,
        include_debug_trace: bool,
        embedding_backend: str,
        answer_provider: str,
        model: str,
    ) -> Iterator[TraceSpan]:
        """Create one root query trace without recording the question text."""

        if not self.enabled:
            yield TraceSpan()
            return

        assert self._langsmith is not None
        assert self._client is not None
        inputs = safe_trace_payload(
            {
                "question_characters": len(question),
                "question_words": len(question.split()),
                "include_debug_trace": include_debug_trace,
                "embedding_backend": embedding_backend,
                "answer_provider": answer_provider,
                "model": model,
                "privacy_mode": "content-redacted",
            }
        )
        metadata = safe_trace_payload(
            {
                "embedding_backend": embedding_backend,
                "answer_provider": answer_provider,
                "model": model,
                "privacy_mode": "content-redacted",
            }
        )
        with self._langsmith.tracing_context(
            enabled=True,
            client=self._client,
            project_name=self.project,
        ):
            with self._langsmith.trace(
                "grounded-answer-query",
                "chain",
                inputs=inputs,
                metadata=metadata,
                tags=["rag", "policy", "content-redacted"],
                client=self._client,
                project_name=self.project,
            ) as run:
                yield TraceSpan(run)

    @contextmanager
    def span(
        self,
        name: str,
        run_type: str,
        inputs: dict[str, Any] | None = None,
    ) -> Iterator[TraceSpan]:
        """Create a nested content-free diagnostic span."""

        if not self.enabled:
            yield TraceSpan()
            return

        assert self._langsmith is not None
        assert self._client is not None
        with self._langsmith.trace(
            name,
            run_type,
            inputs=safe_trace_payload(inputs or {}),
            client=self._client,
            project_name=self.project,
        ) as run:
            yield TraceSpan(run)

    def flush(self, timeout: float = 10.0) -> None:
        """Flush background trace writes, primarily for short-lived CLI runs."""

        if self._client is None:
            return
        try:
            self._client.flush(timeout=timeout)
        except Exception as exc:  # Observability must never break a safe answer.
            LOGGER.warning("LangSmith trace flush failed (%s)", type(exc).__name__)
