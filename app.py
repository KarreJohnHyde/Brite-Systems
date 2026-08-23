"""Streamlit interface for The Grounded Answer.

The UI uses the same source-first pipeline and validated PolicyAnswer contract as
the CLI. The public interface is intentionally fixed to deterministic generation
and stable hashing embeddings so a user cannot select an unavailable runtime.
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


LOGGER = logging.getLogger("grounded_answer.streamlit")
PRODUCTION_EMBEDDING_BACKEND = "hashing"
PRODUCTION_LLM_PROVIDER = "deterministic"

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


def _render_answer(payload: dict[str, Any]) -> None:
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

    reason = payload.get("reason")
    if reason:
        with st.expander("Why this decision was made"):
            st.write(reason)

    next_step = payload.get("next_step")
    if next_step:
        st.info(f"Next step: {next_step}")

    citations = payload.get("citations") or []
    if citations:
        with st.expander("Verify cited source text", expanded=decision == "CONFLICT"):
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
    settings = Settings.from_env(
        embedding_backend=embedding_backend,
        llm_provider=provider,
    )
    manifest_path = settings.index_dir / "manifest.json"
    if not manifest_path.exists():
        LOGGER.info("Policy index is missing; creating it from the trusted source bundle")
        ingest_corpus(settings)
    return GroundedAnswerPipeline.load(settings)


st.title("⚖️ The Grounded Answer")
st.subheader("Calder County HSP policy evidence assistant")
st.markdown(
    "This assistant uses only the supplied policy manual and applicable amendments. It chooses **ANSWER**, "
    "**CONFLICT**, or **REFUSE**, and exposes the exact source text behind every "
    "supported answer. It is decision support, not an eligibility decision-maker."
)

try:
    runtime_settings = Settings.from_env(
        embedding_backend=PRODUCTION_EMBEDDING_BACKEND,
        llm_provider=PRODUCTION_LLM_PROVIDER,
    )
except (TypeError, ValueError) as exc:
    LOGGER.exception("The Streamlit configuration is invalid")
    st.error(f"Configuration is invalid: {exc}")
    st.stop()

with st.sidebar:
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
    st.badge("Verified policy mode", icon=":material/verified:", color="green")

try:
    pipeline = _load_pipeline(
        PRODUCTION_EMBEDDING_BACKEND,
        PRODUCTION_LLM_PROVIDER,
        _artifact_revision(runtime_settings),
    )
except (FileNotFoundError, ImportError, RuntimeError, ValueError) as exc:
    LOGGER.exception("The verified policy runtime could not be loaded: %s", exc)
    st.error(
        "The verified policy sources could not be loaded safely. Please try again later."
    )
    st.stop()

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
            _render_answer(message["payload"])

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
            with st.spinner("Retrieving and checking policy evidence…"):
                answer = pipeline.ask(
                    prompt,
                    change_date=change_date,
                    determination_date=determination_date,
                )
            elapsed = time.perf_counter() - started
            payload = answer.model_dump(mode="json")
            _render_answer(payload)
            st.caption(f"Completed in {elapsed:.2f}s")
            st.session_state.messages.append({"role": "assistant", "payload": payload})
        except Exception:
            LOGGER.exception("The Streamlit request failed safely")
            st.error(
                "The request could not be completed safely, so no policy answer was shown. "
                "Please try again later."
            )

st.caption(
    "Privacy: deterministic mode does not send the question or corpus to an external model. "
    "Do not enter secrets or unnecessary personal information."
)
