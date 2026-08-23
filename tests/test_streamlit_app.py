"""Public Streamlit interface regression checks."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from streamlit.testing.v1 import AppTest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CREDENTIAL_LABELS = {
    "Gemini API key",
    "OpenAI API key",
    "Anthropic API key",
    "Groq API key for Llama",
    "LangSmith / LangChain API key",
}


def test_public_app_exposes_session_provider_controls_and_safe_defaults(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """The UI must start safely and review the runtime used for each answer."""

    monkeypatch.setenv("EMBEDDING_BACKEND", "sentence-transformers")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", " ")
    monkeypatch.setenv("ENABLE_RERANKING", "false")
    monkeypatch.setenv("REQUIRE_RERANKER", "false")
    monkeypatch.setenv("INDEX_DIR", str(tmp_path / "indexes"))
    monkeypatch.setenv("PROCESSED_PATH", str(tmp_path / "processed" / "chunks.json"))
    monkeypatch.setenv(
        "CORPUS_REPORT_PATH",
        str(tmp_path / "processed" / "corpus-report.json"),
    )

    class FakeOpenAIEmbeddings:
        @staticmethod
        def create(**kwargs):
            inputs = kwargs["input"]
            if len(inputs) == 1:
                raise ValueError("invalid session credential")
            dimension = int(kwargs["dimensions"])
            data = []
            for index, _ in enumerate(inputs):
                vector = [0.0] * dimension
                vector[index % dimension] = 1.0
                data.append(SimpleNamespace(index=index, embedding=vector))
            return SimpleNamespace(data=data)

    fake_openai = SimpleNamespace(embeddings=FakeOpenAIEmbeddings())
    monkeypatch.setattr("openai.OpenAI", lambda **kwargs: fake_openai)

    app = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=30).run()

    assert not app.exception
    assert app.title[0].value == "⚖️ The Grounded Answer"
    assert [item.label for item in app.selectbox] == [
        "Embedding backend",
        "Answer phrasing",
    ]
    assert "Runtime mode" in [header.value for header in app.header]
    assert app.selectbox[0].value == "hashing"
    assert app.selectbox[1].value == "deterministic"
    assert app.selectbox[0].options == [
        "Hashing · fast and offline",
        "MiniLM · semantic search",
        "OpenAI · hosted embeddings",
        "Gemini · hosted embeddings",
    ]
    assert app.selectbox[1].options == [
        "Deterministic · verified",
        "Gemini · model phrasing",
        "OpenAI · model phrasing",
        "Claude · model phrasing",
        "Llama via Groq · model phrasing",
    ]
    assert [item.label for item in app.text_input] == [
        "Gemini API key",
        "OpenAI API key",
        "Anthropic API key",
        "Groq API key for Llama",
        "LangSmith / LangChain API key",
        "Tracing project",
    ]
    assert all(
        item.value == ""
        for item in app.text_input
        if item.label in CREDENTIAL_LABELS
    )

    assert (tmp_path / "indexes" / "hashing" / "manifest.json").is_file()

    app.chat_input[0].set_value(
        "How many days do I have to report a change that happened on 15 March 2026?"
    ).run(timeout=30)

    assert not app.exception
    assert app.success[0].icon == "⚖️"
    assert app.success[0].value.startswith("ANSWER")
    assert any("14 calendar days" in item.value for item in app.markdown)
    assert any(
        "**Embedding backend:** Hashing · fast and offline" in item.value
        and "**Answer phrasing:** Deterministic · verified" in item.value
        and "**LangSmith tracing:** Off" in item.value
        for item in app.markdown
    )

    app.selectbox[1].select("openai").run(timeout=30)

    assert not app.exception
    assert app.selectbox[1].value == "openai"
    assert any(
        "OpenAI · model phrasing requires OpenAI API key" in item.value
        and "deterministic phrasing is active" in item.value
        for item in app.info
    )

    app.chat_input[0].set_value(
        "What is the household resource limit for eligibility?"
    ).run(timeout=30)

    assert not app.exception
    assert any("$4,000" in item.value for item in app.markdown)
    assert any(
        "**Answer phrasing:** Deterministic · verified" in item.value
        for item in app.markdown
    )
    assert any(
        "OpenAI · model phrasing requires OpenAI API key" in item.value
        for item in app.caption
    )

    openai_key = next(
        item for item in app.text_input if item.label == "OpenAI API key"
    )
    openai_key.set_value("session-only-test-key").run(timeout=30)
    assert next(
        item for item in app.text_input if item.label == "OpenAI API key"
    ).value == "session-only-test-key"

    clear_keys = next(
        button for button in app.button if button.label == "Clear session API keys"
    )
    clear_keys.click().run(timeout=30)

    assert not app.exception
    assert all(
        item.value == ""
        for item in app.text_input
        if item.label in CREDENTIAL_LABELS
    )

    app.selectbox[1].select("deterministic").run(timeout=30)
    app.selectbox[0].select("openai").run(timeout=30)
    next(
        item for item in app.text_input if item.label == "OpenAI API key"
    ).set_value("invalid-session-key").run(timeout=30)

    assert not app.exception
    assert app.selectbox[0].value == "openai"

    app.chat_input[0].set_value(
        "What is the household resource limit for eligibility?"
    ).run(timeout=30)

    assert not app.exception
    reviews = [
        item.value
        for item in app.markdown
        if "**Embedding backend:**" in item.value
    ]
    assert "**Embedding backend:** Hashing · fast and offline" in reviews[-1]
    assert any(
        "selected optional runtime failed during this request" in item.value
        for item in app.caption
    )
