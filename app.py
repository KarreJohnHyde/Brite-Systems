"""Optional Streamlit interface for The Grounded Answer.

The UI uses the same source-first pipeline and validated PolicyAnswer contract as
the CLI.  Deterministic generation and stable hashing embeddings are the safe
defaults; external model use must be selected explicitly.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import streamlit as st

from config.settings import Settings
from src.pipeline import GroundedAnswerPipeline


LOGGER = logging.getLogger("grounded_answer.streamlit")

st.set_page_config(
    page_title="The Grounded Answer",
    page_icon="⚖️",
    layout="centered",
)


def _citation_label(citation: dict[str, Any]) -> str:
    clause_id = citation.get("clause_id")
    source_id = citation.get("chunk_id", "source")
    section = citation.get("section_title") or "Untitled section"
    return f"§{clause_id} — {section}" if clause_id else f"{source_id} — {section}"


def _render_answer(payload: dict[str, Any]) -> None:
    """Render one validated PolicyAnswer serialized in JSON mode."""

    decision = str(payload.get("decision", "REFUSE")).upper()
    if decision == "ANSWER":
        st.success("ANSWER — directly supported by the manual")
    elif decision == "CONFLICT":
        st.warning("CONFLICT — the manual contains incompatible guidance")
    else:
        st.error("REFUSE — the manual does not safely settle the question")

    st.markdown(str(payload.get("answer", "No answer was produced.")))

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
                    f"{location} · Source ID `{citation.get('chunk_id', 'unknown')}`"
                )
                st.code(str(citation.get("excerpt", "")), language=None, wrap_lines=True)

    evidence = payload.get("evidence_level")
    if evidence:
        st.caption(f"Evidence level: {evidence}")


@st.cache_resource(show_spinner="Loading the policy index…")
def _load_pipeline(embedding_backend: str, provider: str) -> GroundedAnswerPipeline:
    settings = Settings.from_env(
        embedding_backend=embedding_backend,
        llm_provider=provider,
    )
    return GroundedAnswerPipeline.load(settings)


st.title("⚖️ The Grounded Answer")
st.subheader("Calder County HSP policy evidence assistant")
st.markdown(
    "This assistant uses only the supplied policy manual. It chooses **ANSWER**, "
    "**CONFLICT**, or **REFUSE**, and exposes the exact source text behind every "
    "supported answer. It is decision support, not an eligibility decision-maker."
)

try:
    defaults = Settings.from_env()
except (TypeError, ValueError) as exc:
    st.error(f"Configuration is invalid: {exc}")
    st.stop()

backend_options = ["hashing", "sentence-transformers"]
provider_options = ["deterministic", "gemini"]

with st.sidebar:
    st.header("Runtime mode")
    embedding_backend = st.selectbox(
        "Embedding backend",
        backend_options,
        index=backend_options.index(defaults.embedding_backend),
        help="Hashing is local and reproducible. Sentence Transformers downloads and runs MiniLM locally.",
    )
    provider = st.selectbox(
        "Answer phrasing",
        provider_options,
        index=provider_options.index(defaults.llm_provider),
        help="Deterministic keeps all query processing local. Gemini sends selected excerpts to the configured API.",
    )
    st.caption(
        "Reranking is configured with ENABLE_RERANKING in .env and is disabled by default. "
        "Restart Streamlit after editing .env. The selected embedding backend must match "
        "the backend used for ingestion."
    )
    if st.button("Clear conversation"):
        st.session_state.messages = []
        st.rerun()

try:
    pipeline = _load_pipeline(embedding_backend, provider)
except (FileNotFoundError, ImportError, RuntimeError, ValueError) as exc:
    st.error(str(exc))
    st.code(
        f"python main.py ingest --embedding-backend {embedding_backend}",
        language="powershell",
    )
    if provider == "gemini":
        st.caption("Gemini additionally requires GEMINI_API_KEY in .env or the process environment.")
    st.stop()

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        if message["role"] == "user":
            st.markdown(message["content"])
        else:
            _render_answer(message["payload"])

if prompt := st.chat_input("Ask a policy question…"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        try:
            started = time.perf_counter()
            with st.spinner("Retrieving and checking policy evidence…"):
                answer = pipeline.ask(prompt)
            elapsed = time.perf_counter() - started
            payload = answer.model_dump(mode="json")
            _render_answer(payload)
            st.caption(f"Completed in {elapsed:.2f}s")
            st.session_state.messages.append({"role": "assistant", "payload": payload})
        except Exception:
            LOGGER.exception("The Streamlit request failed safely")
            st.error(
                "The request could not be completed safely, so no policy answer was shown. "
                "Check the server log and confirm that the index matches the selected backend."
            )

st.caption(
    "Privacy: deterministic mode does not send the question or corpus to an external model. "
    "Do not enter secrets or unnecessary personal information."
)
