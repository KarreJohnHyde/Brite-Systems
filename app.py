"""Streamlit interface for The Grounded Answer.

The UI uses the same source-first pipeline and validated PolicyAnswer contract as
the CLI. Optional runtimes use deployment credentials or keys supplied only for
the current Streamlit session.
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
    ANSWER_KEY_FIELDS,
    ANSWER_MODEL_FIELDS,
    LOCAL_EMBEDDING_BACKENDS,
    answer_provider_key,
    available_answer_providers,
    available_embedding_backends,
    build_runtime_settings,
    langsmith_available,
)


LOGGER = logging.getLogger("grounded_answer.streamlit")
DEFAULT_EMBEDDING_BACKEND = "hashing"
DEFAULT_ANSWER_PROVIDER = "deterministic"
EMBEDDING_LABELS = {
    "hashing": "Hashing · fast and offline",
    "sentence-transformers": "MiniLM · semantic search",
    "openai": "OpenAI · hosted embeddings",
    "gemini": "Gemini · hosted embeddings",
}
PROVIDER_LABELS = {
    "deterministic": "Deterministic · verified",
    "gemini": "Gemini · model phrasing",
    "openai": "OpenAI · model phrasing",
    "anthropic": "Claude · model phrasing",
    "llama": "Llama via Groq · model phrasing",
}
CREDENTIAL_WIDGET_KEYS = {
    "gemini": "session_gemini_api_key",
    "openai": "session_openai_api_key",
    "anthropic": "session_anthropic_api_key",
    "llama": "session_llama_api_key",
    "langsmith": "session_langsmith_api_key",
}
CREDENTIAL_LABELS = {
    "gemini": "Gemini API key",
    "openai": "OpenAI API key",
    "anthropic": "Anthropic API key",
    "llama": "Groq API key for Llama",
    "langsmith": "LangSmith / LangChain API key",
}
REMOTE_EMBEDDING_KEY_PROVIDER = {
    "openai": "openai",
    "gemini": "gemini",
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
                    f"**Embedding model:** {runtime.get('embedding_model', 'not recorded')}",
                    f"**Answer phrasing:** {PROVIDER_LABELS.get(provider, provider)}",
                    f"**Answer model:** {runtime.get('answer_model', 'not recorded')}",
                    f"**LangSmith tracing:** {'On · content redacted' if runtime.get('langsmith_tracing') else 'Off'}",
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


@st.cache_resource(show_spinner="Loading the policy index…", max_entries=4)
def _load_local_pipeline(
    embedding_backend: str,
    embedding_model: str,
    embedding_dimension: int,
    artifact_revision: str,
) -> GroundedAnswerPipeline:
    del artifact_revision  # The value is intentionally part of the cache key.
    settings = build_runtime_settings(
        embedding_backend,
        DEFAULT_ANSWER_PROVIDER,
        embedding_model=embedding_model,
        embedding_dimension=embedding_dimension,
        langsmith_tracing=False,
    )
    manifest_path = settings.index_dir / "manifest.json"
    if not manifest_path.exists():
        LOGGER.info("Policy index is missing; creating it from the trusted source bundle")
        ingest_corpus(settings)
    return GroundedAnswerPipeline.load(settings)


def _runtime_selection_changed() -> None:
    """Release session-specific clients when runtime controls change."""

    st.session_state.pop("_session_runtime_pipeline", None)


def _secret_fingerprint(value: str | None) -> str:
    if not value:
        return "missing"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _session_credential(
    provider: str,
    deployment_settings: Settings,
) -> tuple[str | None, str | None]:
    """Resolve a pasted key first, without exposing a deployment secret in the UI."""

    widget_key = CREDENTIAL_WIDGET_KEYS[provider]
    pasted = str(st.session_state.get(widget_key, "")).strip()
    if pasted:
        return pasted, "session"
    if provider == "langsmith":
        deployed = deployment_settings.langsmith_api_key
    else:
        deployed = answer_provider_key(deployment_settings, provider)
    if deployed:
        return deployed, "deployment"
    return None, None


def _runtime_signature(settings: Settings) -> str:
    values = [
        settings.embedding_backend,
        settings.embedding_model,
        str(settings.embedding_dimension),
        settings.llm_provider,
        settings.answer_model,
        str(settings.langsmith_tracing),
        settings.langsmith_project,
        _artifact_revision(settings),
        _secret_fingerprint(settings.gemini_api_key),
        _secret_fingerprint(settings.openai_api_key),
        _secret_fingerprint(settings.anthropic_api_key),
        _secret_fingerprint(settings.llama_api_key),
        _secret_fingerprint(settings.langsmith_api_key),
    ]
    return hashlib.sha256("\n".join(values).encode("utf-8")).hexdigest()


def _load_runtime_pipeline(settings: Settings) -> GroundedAnswerPipeline:
    """Keep credentials and remote clients scoped to one Streamlit session."""

    signature = _runtime_signature(settings)
    cached = st.session_state.get("_session_runtime_pipeline")
    if isinstance(cached, dict) and cached.get("signature") == signature:
        return cached["pipeline"]

    if settings.embedding_backend in LOCAL_EMBEDDING_BACKENDS:
        base_settings = build_runtime_settings(
            settings.embedding_backend,
            DEFAULT_ANSWER_PROVIDER,
            embedding_model=settings.embedding_model,
            embedding_dimension=settings.embedding_dimension,
            langsmith_tracing=False,
        )
        base = _load_local_pipeline(
            base_settings.embedding_backend,
            base_settings.embedding_model,
            base_settings.embedding_dimension,
            _artifact_revision(base_settings),
        )
        if settings.llm_provider == "deterministic" and not settings.langsmith_tracing:
            pipeline = base
        else:
            pipeline = GroundedAnswerPipeline.from_base(base, settings)
    else:
        manifest_path = settings.index_dir / "manifest.json"
        if not manifest_path.exists():
            LOGGER.info(
                "Remote policy index is missing; creating it from the trusted source bundle"
            )
            with st.spinner(
                f"Building the {EMBEDDING_LABELS[settings.embedding_backend]} policy index…"
            ):
                ingest_corpus(settings)
        pipeline = GroundedAnswerPipeline.load(settings)

    st.session_state["_session_runtime_pipeline"] = {
        "signature": signature,
        "pipeline": pipeline,
    }
    return pipeline


def _clear_session_credentials() -> None:
    for key in CREDENTIAL_WIDGET_KEYS.values():
        st.session_state[key] = ""
    st.session_state.pop("_session_runtime_pipeline", None)


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
    provider_options = available_answer_providers()
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
        help=(
            "Local modes keep policy text on this server. Hosted modes send policy "
            "clauses and questions to the selected embedding provider."
        ),
    )
    answer_provider = st.selectbox(
        "Answer phrasing",
        provider_options,
        key="answer_provider",
        format_func=lambda value: PROVIDER_LABELS[value],
        on_change=_runtime_selection_changed,
        help=(
            "Model phrasing is optional. Every generated claim and source ID is "
            "validated before the answer is displayed."
        ),
    )

    selected_embedding_model: str | None = None
    selected_embedding_dimension = 768
    if embedding_backend in REMOTE_EMBEDDING_KEY_PROVIDER:
        embedding_defaults = build_runtime_settings(
            embedding_backend,
            DEFAULT_ANSWER_PROVIDER,
        )
        selected_embedding_model = st.text_input(
            "Embedding model",
            value=embedding_defaults.embedding_model,
            key=f"{embedding_backend}_embedding_model",
            on_change=_runtime_selection_changed,
        )
        selected_embedding_dimension = int(
            st.number_input(
                "Embedding dimensions",
                min_value=128,
                max_value=3072,
                value=768,
                step=128,
                key=f"{embedding_backend}_embedding_dimension",
                on_change=_runtime_selection_changed,
            )
        )

    selected_answer_model: str | None = None
    if answer_provider != DEFAULT_ANSWER_PROVIDER:
        model_field = ANSWER_MODEL_FIELDS[answer_provider]
        selected_answer_model = st.text_input(
            "Answer model",
            value=str(getattr(capability_settings, model_field)),
            key=f"{answer_provider}_answer_model",
            on_change=_runtime_selection_changed,
        )

    runtime_status_slot = st.empty()

    with st.expander(
        "Provider API keys",
        icon=":material/key:",
        expanded=True,
    ):
        st.caption(
            "Pasted keys stay in this Streamlit session. This app does not write "
            "them to files, logs, answers, or chat history."
        )
        for provider in ("gemini", "openai", "anthropic", "llama"):
            deployment_key = answer_provider_key(capability_settings, provider)
            st.text_input(
                CREDENTIAL_LABELS[provider],
                type="password",
                key=CREDENTIAL_WIDGET_KEYS[provider],
                placeholder=(
                    "Deployment key configured"
                    if deployment_key
                    else "Paste key for this session"
                ),
                on_change=_runtime_selection_changed,
            )

        st.divider()
        st.caption(
            "LangSmith provides optional content-redacted tracing. Its API key "
            "does not generate embeddings."
        )
        st.text_input(
            CREDENTIAL_LABELS["langsmith"],
            type="password",
            key=CREDENTIAL_WIDGET_KEYS["langsmith"],
            placeholder=(
                "Deployment key configured"
                if capability_settings.langsmith_api_key
                else "Paste tracing key for this session"
            ),
            on_change=_runtime_selection_changed,
            disabled=not langsmith_available(),
        )
        langsmith_tracing_requested = st.toggle(
            "Enable redacted tracing",
            value=False,
            key="session_langsmith_tracing",
            on_change=_runtime_selection_changed,
            disabled=not langsmith_available(),
        )
        langsmith_project = st.text_input(
            "Tracing project",
            value=capability_settings.langsmith_project,
            key="session_langsmith_project",
            on_change=_runtime_selection_changed,
            disabled=not langsmith_tracing_requested,
        )
        st.button(
            "Clear session API keys",
            icon=":material/key_off:",
            width="stretch",
            on_click=_clear_session_credentials,
        )

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

api_keys: dict[str, str | None] = {}
for provider in ("gemini", "openai", "anthropic", "llama"):
    api_keys[provider], _ = _session_credential(
        provider,
        capability_settings,
    )
langsmith_api_key, _ = _session_credential(
    "langsmith",
    capability_settings,
)

runtime_notes: list[str] = []
active_embedding_backend = embedding_backend
embedding_key_provider = REMOTE_EMBEDDING_KEY_PROVIDER.get(embedding_backend)
if embedding_key_provider and not api_keys[embedding_key_provider]:
    active_embedding_backend = DEFAULT_EMBEDDING_BACKEND
    runtime_notes.append(
        f"{EMBEDDING_LABELS[embedding_backend]} requires "
        f"{CREDENTIAL_LABELS[embedding_key_provider]}; hashing is active until one is supplied."
    )

active_answer_provider = answer_provider
if answer_provider != DEFAULT_ANSWER_PROVIDER and not api_keys[answer_provider]:
    active_answer_provider = DEFAULT_ANSWER_PROVIDER
    runtime_notes.append(
        f"{PROVIDER_LABELS[answer_provider]} requires "
        f"{CREDENTIAL_LABELS[answer_provider]}; deterministic phrasing is active until one is supplied."
    )

active_langsmith_tracing = bool(
    langsmith_tracing_requested
    and langsmith_available()
    and langsmith_api_key
)
if langsmith_tracing_requested and not active_langsmith_tracing:
    runtime_notes.append(
        "LangSmith tracing needs its API key and installed SDK; tracing remains off."
    )

try:
    runtime_settings = build_runtime_settings(
        active_embedding_backend,
        active_answer_provider,
        api_keys=api_keys,
        embedding_model=(
            selected_embedding_model
            if active_embedding_backend == embedding_backend
            else None
        ),
        answer_model=(
            selected_answer_model
            if active_answer_provider == answer_provider
            else None
        ),
        embedding_dimension=(
            selected_embedding_dimension
            if active_embedding_backend == embedding_backend
            and embedding_backend in REMOTE_EMBEDDING_KEY_PROVIDER
            else None
        ),
        langsmith_tracing=active_langsmith_tracing,
        langsmith_api_key=langsmith_api_key,
        langsmith_project=langsmith_project,
    )
    pipeline = _load_runtime_pipeline(runtime_settings)
except (FileNotFoundError, ImportError, RuntimeError, ValueError) as exc:
    LOGGER.warning(
        "The selected policy runtime could not be loaded (%s)",
        type(exc).__name__,
    )
    if (
        active_embedding_backend != DEFAULT_EMBEDDING_BACKEND
        or active_answer_provider != DEFAULT_ANSWER_PROVIDER
        or active_langsmith_tracing
    ):
        st.warning(
            "The selected optional runtime was unavailable, so the assistant returned "
            "to the verified hashing and deterministic mode.",
            icon=":material/warning:",
        )
        active_embedding_backend = DEFAULT_EMBEDDING_BACKEND
        active_answer_provider = DEFAULT_ANSWER_PROVIDER
        active_langsmith_tracing = False
        runtime_notes.append(
            "The optional runtime could not start; this session used verified local defaults."
        )
        runtime_settings = build_runtime_settings(
            active_embedding_backend,
            active_answer_provider,
            langsmith_tracing=False,
        )
        pipeline = _load_runtime_pipeline(runtime_settings)
    else:
        st.error("The policy sources could not be loaded safely. Please try again later.")
        st.stop()

for note in runtime_notes:
    st.info(note, icon=":material/info:")

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
            fallback_notes = list(runtime_notes)
            answer_settings = runtime_settings
            answer_embedding_backend = active_embedding_backend
            answer_tracing = active_langsmith_tracing
            optional_runtime_failed = False
            with st.spinner("Retrieving and checking policy evidence…"):
                try:
                    answer = pipeline.ask(
                        prompt,
                        change_date=change_date,
                        determination_date=determination_date,
                    )
                except Exception as optional_exc:
                    if (
                        active_embedding_backend == DEFAULT_EMBEDDING_BACKEND
                        and active_answer_provider == DEFAULT_ANSWER_PROVIDER
                        and not active_langsmith_tracing
                    ):
                        raise
                    LOGGER.warning(
                        "Optional runtime failed during a request (%s)",
                        type(optional_exc).__name__,
                    )
                    fallback_settings = build_runtime_settings(
                        DEFAULT_EMBEDDING_BACKEND,
                        DEFAULT_ANSWER_PROVIDER,
                        langsmith_tracing=False,
                    )
                    fallback_pipeline = _load_runtime_pipeline(fallback_settings)
                    answer = fallback_pipeline.ask(
                        prompt,
                        change_date=change_date,
                        determination_date=determination_date,
                    )
                    active_provider = DEFAULT_ANSWER_PROVIDER
                    answer_settings = fallback_settings
                    answer_embedding_backend = DEFAULT_EMBEDDING_BACKEND
                    answer_tracing = False
                    optional_runtime_failed = True
                    fallback_notes.append(
                        "The selected optional runtime failed during this request, so "
                        "verified local hashing and deterministic phrasing produced "
                        "this answer."
                    )
                if (
                    not optional_runtime_failed
                    and active_answer_provider != DEFAULT_ANSWER_PROVIDER
                    and answer.decision.value == "REFUSE"
                    and any(
                        marker in str(answer.reason).lower()
                        for marker in (
                            "provider safety check",
                            "coverage evaluation failed",
                        )
                    )
                ):
                    fallback_settings = build_runtime_settings(
                        active_embedding_backend,
                        DEFAULT_ANSWER_PROVIDER,
                        api_keys=api_keys,
                        embedding_model=runtime_settings.embedding_model,
                        embedding_dimension=runtime_settings.embedding_dimension,
                        langsmith_tracing=active_langsmith_tracing,
                        langsmith_api_key=langsmith_api_key,
                        langsmith_project=langsmith_project,
                    )
                    fallback_pipeline = _load_runtime_pipeline(fallback_settings)
                    answer = fallback_pipeline.ask(
                        prompt,
                        change_date=change_date,
                        determination_date=determination_date,
                    )
                    active_provider = DEFAULT_ANSWER_PROVIDER
                    fallback_notes.append(
                        f"{PROVIDER_LABELS[active_answer_provider]} could not complete "
                        "the validated policy workflow, so this answer used the "
                        "deterministic fallback."
                    )
                elif active_answer_provider != DEFAULT_ANSWER_PROVIDER:
                    if answer.phrasing_mode == "model":
                        active_provider = active_answer_provider
                    else:
                        active_provider = DEFAULT_ANSWER_PROVIDER
                        fallback_notes.append(
                            "Model phrasing was not used for this answer; the validated "
                            "deterministic policy wording was shown."
                        )
            elapsed = time.perf_counter() - started
            payload = answer.model_dump(mode="json")
            answer_runtime = {
                "embedding_backend": answer_embedding_backend,
                "embedding_model": answer_settings.embedding_model,
                "answer_provider": active_provider,
                "answer_model": (
                    answer_settings.answer_model
                    if active_provider != DEFAULT_ANSWER_PROVIDER
                    else "deterministic"
                ),
                "langsmith_tracing": answer_tracing,
                "fallback_note": " ".join(fallback_notes) or None,
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
        except Exception as exc:
            LOGGER.warning("The Streamlit request failed safely (%s)", type(exc).__name__)
            st.error(
                "The request could not be completed safely, so no policy answer was shown. "
                "Please try again later."
            )

privacy_notes: list[str] = []
if active_embedding_backend in REMOTE_EMBEDDING_KEY_PROVIDER:
    privacy_notes.append(
        f"{EMBEDDING_LABELS[active_embedding_backend]} sends policy text while building "
        "the index and sends each question for retrieval"
    )
if active_answer_provider != DEFAULT_ANSWER_PROVIDER:
    privacy_notes.append(
        f"{PROVIDER_LABELS[active_answer_provider]} sends the question and selected "
        "policy excerpts for validated phrasing"
    )
if active_langsmith_tracing:
    privacy_notes.append("LangSmith receives only content-redacted diagnostics")

if privacy_notes:
    st.caption(
        "Privacy: " + "; ".join(privacy_notes) + ". Do not enter secrets or unnecessary personal information."
    )
else:
    st.caption(
        "Privacy: local deterministic mode does not send the question or corpus to an "
        "external model. Do not enter secrets or unnecessary personal information."
    )
