"""Streamlit interface for The Grounded Answer.

The UI uses the same source-first pipeline and validated PolicyAnswer contract as
the CLI. Optional runtimes are exposed only when their local package and required
server-side credentials are available.
"""

from __future__ import annotations

import hashlib
import logging
import time
from datetime import date
from typing import Any

import streamlit as st

from config.settings import Settings
from src.pipeline import GroundedAnswerPipeline, ingest_corpus
from src.web_runtime import (
    available_answer_providers,
    available_embedding_backends,
    build_runtime_settings,
)


LOGGER = logging.getLogger("grounded_answer.streamlit")
DEFAULT_EMBEDDING_BACKEND = "hashing"
DEFAULT_ANSWER_PROVIDER = "deterministic"
EMBEDDING_LABELS = {
    "hashing": "Hashing · fast and offline",
    "sentence-transformers": "MiniLM · semantic search",
}
PROVIDER_LABELS = {
    "deterministic": "Deterministic · verified",
    "gemini": "Gemini · model phrasing",
}

st.set_page_config(
    page_title="The Grounded Answer",
    page_icon="⚖️",
    layout="centered",
)


def _citation_label(citation: dict[str, Any]) -> str:
    if label := citation.get("source_locator_label"):
        return str(label)
    clause_id = citation.get("clause_id")
    if clause_id:
        return f"Policy Manual §{clause_id}"
    return str(citation.get("source_locator") or "Unlabelled policy source")


def _render_answer(
    payload: dict[str, Any],
    runtime: dict[str, Any] | None = None,
) -> None:
    """Render one validated PolicyAnswer serialized in JSON mode."""

    decision = str(payload.get("decision", "REFUSE")).upper()
    if decision == "ANSWER":
        st.success("⚖️ ANSWER — directly supported by the policy sources")
    elif decision == "CONFLICT":
        st.warning("⚖️ CONFLICT — the manual contains incompatible guidance")
    else:
        st.error("⚖️ REFUSE — the manual does not safely settle the question")

    # Streamlit treats pairs of dollar signs as inline math delimiters. Policy
    # amounts must remain ordinary visible currency in the rendered answer.
    rendered_answer = str(payload.get("answer", "No answer was produced.")).replace(
        "$", r"\$"
    )
    st.markdown(rendered_answer)

    next_step = payload.get("next_step")
    if next_step:
        st.info(f"Next step: {next_step}")

    citations = payload.get("citations") or []
    reason = payload.get("reason")
    with st.expander("Answer review", icon=":material/fact_check:"):
        if reason:
            st.write(reason)
        review_lines = [
            f"**Decision:** {decision}",
            f"**Evidence level:** {payload.get('evidence_level', 'UNKNOWN')}",
            f"**Validated citations:** {len(citations)}",
        ]
        if runtime:
            backend = str(runtime.get("embedding_backend", "not recorded"))
            provider = str(runtime.get("answer_provider", "not recorded"))
            review_lines.extend(
                [
                    f"**Embedding backend:** {EMBEDDING_LABELS.get(backend, backend)}",
                    f"**Answer phrasing:** {PROVIDER_LABELS.get(provider, provider)}",
                ]
            )
        st.markdown("  \n".join(review_lines))
        if runtime and runtime.get("fallback_note"):
            st.caption(str(runtime["fallback_note"]))

    if citations:
        with st.expander(
            "Verify cited source text",
            expanded=decision == "CONFLICT",
            icon=":material/policy:",
        ):
            for citation in citations:
                start = citation.get("line_start", "?")
                end = citation.get("line_end", "?")
                page = citation.get("page")
                location = f"lines {start}–{end}"
                if page is not None:
                    location = f"page {page}; {location}"
                st.markdown(
                    f"**{_citation_label(citation)}**  \n"
                    f"{location}"
                )
                st.code(str(citation.get("excerpt", "")), language=None, wrap_lines=True)

    evidence = payload.get("evidence_level")
    if evidence:
        st.caption(f"Evidence level: {evidence}")


def _artifact_revision(settings: Settings) -> str:
    """Fingerprint every file that can change the answer contract."""

    digest = hashlib.sha256()
    paths = (
        settings.corpus_path,
        settings.amendment_path,
        settings.timeline_path,
        settings.index_dir / "manifest.json",
        settings.findings_path,
        settings.contacts_path,
    )
    for path in paths:
        if path is None:
            continue
        digest.update(str(path.resolve()).encode("utf-8"))
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"<missing>")
    return digest.hexdigest()


@st.cache_resource(show_spinner="Loading the policy index…", max_entries=8)
def _load_pipeline(
    embedding_backend: str,
    provider: str,
    artifact_revision: str,
) -> GroundedAnswerPipeline:
    del artifact_revision  # The value is intentionally part of the cache key.
    settings = build_runtime_settings(embedding_backend, provider)
    manifest_path = settings.index_dir / "manifest.json"
    if not manifest_path.exists():
        LOGGER.info("Policy index is missing; creating it from the trusted source bundle")
        ingest_corpus(settings)
    return GroundedAnswerPipeline.load(settings)


def _runtime_selection_changed() -> None:
    """Release the prior model/index when a user changes runtime mode."""

    _load_pipeline.clear()


st.title("⚖️ The Grounded Answer")
st.subheader("Calder County HSP policy evidence assistant")
st.markdown(
    "This assistant uses only the supplied policy manual and applicable amendments. It chooses **ANSWER**, "
    "**CONFLICT**, or **REFUSE**, and exposes the exact source text behind every "
    "supported answer. It is decision support, not an eligibility decision-maker."
)

try:
    capability_settings = build_runtime_settings(
        DEFAULT_EMBEDDING_BACKEND,
        DEFAULT_ANSWER_PROVIDER,
    )
    embedding_options = available_embedding_backends()
    provider_options = available_answer_providers(capability_settings)
except (TypeError, ValueError) as exc:
    LOGGER.exception("The Streamlit configuration is invalid")
    st.error(f"Configuration is invalid: {exc}")
    st.stop()

if st.session_state.get("embedding_backend") not in embedding_options:
    st.session_state.embedding_backend = DEFAULT_EMBEDDING_BACKEND
if st.session_state.get("answer_provider") not in provider_options:
    st.session_state.answer_provider = DEFAULT_ANSWER_PROVIDER

with st.sidebar:
    st.header("Runtime mode")
    embedding_backend = st.selectbox(
        "Embedding backend",
        embedding_options,
        key="embedding_backend",
        format_func=lambda value: EMBEDDING_LABELS[value],
        on_change=_runtime_selection_changed,
        help="Hashing starts immediately. MiniLM builds and caches a separate semantic index on first use.",
    )
    answer_provider = st.selectbox(
        "Answer phrasing",
        provider_options,
        key="answer_provider",
        format_func=lambda value: PROVIDER_LABELS[value],
        on_change=_runtime_selection_changed,
        help="Gemini appears only when its server-side package and API key are configured.",
    )
    runtime_status_slot = st.empty()
    if "gemini" not in provider_options:
        st.caption("Gemini is not configured for this deployment.")

    st.header("Case context")
    use_case_date = st.toggle("Use a case date", value=False)
    date_basis = "Change occurred"
    case_date: date | None = None
    if use_case_date:
        date_basis = st.selectbox(
            "Date applies to",
            ("Change occurred", "Determination made"),
        )
        case_date = st.date_input(
            "Date",
            value=date.today(),
            min_value=date(2000, 1, 1),
            max_value=date(2100, 12, 31),
            format="DD/MM/YYYY",
        )
    if st.button("Clear conversation", icon=":material/delete_sweep:"):
        st.session_state.messages = []
        st.rerun()

active_embedding_backend = embedding_backend
active_answer_provider = answer_provider
try:
    runtime_settings = build_runtime_settings(embedding_backend, answer_provider)
    pipeline = _load_pipeline(
        embedding_backend,
        answer_provider,
        _artifact_revision(runtime_settings),
    )
except (FileNotFoundError, ImportError, RuntimeError, ValueError) as exc:
    LOGGER.exception("The selected policy runtime could not be loaded: %s", exc)
    if (
        embedding_backend != DEFAULT_EMBEDDING_BACKEND
        or answer_provider != DEFAULT_ANSWER_PROVIDER
    ):
        st.warning(
            "The selected optional runtime was unavailable, so the assistant returned "
            "to the verified hashing and deterministic mode.",
            icon=":material/warning:",
        )
        active_embedding_backend = DEFAULT_EMBEDDING_BACKEND
        active_answer_provider = DEFAULT_ANSWER_PROVIDER
        runtime_settings = build_runtime_settings(
            active_embedding_backend,
            active_answer_provider,
        )
        pipeline = _load_pipeline(
            active_embedding_backend,
            active_answer_provider,
            _artifact_revision(runtime_settings),
        )
    else:
        st.error("The policy sources could not be loaded safely. Please try again later.")
        st.stop()

runtime_status_slot.badge(
    f"{active_embedding_backend} · {active_answer_provider}",
    icon=":material/verified:",
    color="green",
)

manual_chunks = [chunk for chunk in pipeline.store.chunks if chunk.source_kind == "manual"]
amendment_chunks = [chunk for chunk in pipeline.store.chunks if chunk.source_kind == "amendment"]
active_manual = manual_chunks[0] if manual_chunks else pipeline.store.chunks[0]
version = active_manual.document_version or "version not stated"
amendment_caption = (
    f" · Amendment No. {amendment_chunks[0].amendment_number} effective "
    f"{amendment_chunks[0].effective_date}"
    if amendment_chunks
    else ""
)
st.caption(
    f"Active manual: {active_manual.document_name} · consolidated {version} · "
    f"{len(manual_chunks)} manual clauses and {len(amendment_chunks)} amendment paragraphs"
    f"{amendment_caption}"
)

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    avatar = "⚖️" if message["role"] == "assistant" else None
    with st.chat_message(message["role"], avatar=avatar):
        if message["role"] == "user":
            st.markdown(message["content"])
        else:
            _render_answer(message["payload"], message.get("runtime"))

if prompt := st.chat_input(
    "Ask a complete, standalone policy question…",
    key="policy_question",
    submit_mode="disable",
):
    display_prompt = prompt
    change_date = None
    determination_date = None
    if use_case_date and case_date is not None:
        context_label = date_basis
        display_prompt += (
            f"\n\n**{context_label}:** {case_date.day} {case_date.strftime('%B %Y')}"
        )
        if date_basis == "Change occurred":
            change_date = case_date
        else:
            determination_date = case_date

    st.session_state.messages.append({"role": "user", "content": display_prompt})
    with st.chat_message("user"):
        st.markdown(display_prompt)

    with st.chat_message("assistant", avatar="⚖️"):
        try:
            started = time.perf_counter()
            active_provider = active_answer_provider
            fallback_note = None
            with st.spinner("Retrieving and checking policy evidence…"):
                answer = pipeline.ask(
                    prompt,
                    change_date=change_date,
                    determination_date=determination_date,
                )
                if (
                    active_answer_provider == "gemini"
                    and answer.decision.value == "REFUSE"
                    and any(
                        marker in answer.reason.lower()
                        for marker in (
                            "provider safety check",
                            "coverage evaluation failed",
                        )
                    )
                ):
                    fallback_settings = build_runtime_settings(
                        active_embedding_backend,
                        DEFAULT_ANSWER_PROVIDER,
                    )
                    fallback_pipeline = _load_pipeline(
                        active_embedding_backend,
                        DEFAULT_ANSWER_PROVIDER,
                        _artifact_revision(fallback_settings),
                    )
                    answer = fallback_pipeline.ask(
                        prompt,
                        change_date=change_date,
                        determination_date=determination_date,
                    )
                    active_provider = DEFAULT_ANSWER_PROVIDER
                    fallback_note = (
                        "Gemini could not complete the validated policy workflow, so this "
                        "answer used the deterministic fallback."
                    )
                elif active_answer_provider == "gemini":
                    if answer.phrasing_mode == "model":
                        active_provider = "gemini"
                    else:
                        active_provider = DEFAULT_ANSWER_PROVIDER
                        fallback_note = (
                            "Model phrasing was not used for this answer; the validated "
                            "deterministic policy wording was shown."
                        )
            elapsed = time.perf_counter() - started
            payload = answer.model_dump(mode="json")
            answer_runtime = {
                "embedding_backend": active_embedding_backend,
                "answer_provider": active_provider,
                "fallback_note": fallback_note,
            }
            _render_answer(payload, answer_runtime)
            st.caption(f"Completed in {elapsed:.2f}s")
            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "payload": payload,
                    "runtime": answer_runtime,
                }
            )
        except Exception:
            LOGGER.exception("The Streamlit request failed safely")
            st.error(
                "The request could not be completed safely, so no policy answer was shown. "
                "Please try again later."
            )

if active_answer_provider == "gemini":
    st.caption(
        "Privacy: Gemini mode sends the question and selected policy excerpts to the "
        "configured Google Gemini API. Do not enter secrets or unnecessary personal information."
    )
else:
    st.caption(
        "Privacy: deterministic mode does not send the question or corpus to an external model. "
        "Do not enter secrets or unnecessary personal information."
    )
