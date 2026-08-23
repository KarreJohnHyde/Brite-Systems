"""Public Streamlit interface regression checks."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_public_app_exposes_only_working_runtime_options(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """The UI must start safely and review the runtime used for each answer."""

    monkeypatch.setenv("EMBEDDING_BACKEND", "sentence-transformers")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", " ")
    monkeypatch.setenv("INDEX_DIR", str(tmp_path / "indexes"))
    monkeypatch.setenv("PROCESSED_PATH", str(tmp_path / "processed" / "chunks.json"))
    monkeypatch.setenv(
        "CORPUS_REPORT_PATH",
        str(tmp_path / "processed" / "corpus-report.json"),
    )

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
    ]
    assert app.selectbox[1].options == ["Deterministic · verified"]
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
        for item in app.markdown
    )
