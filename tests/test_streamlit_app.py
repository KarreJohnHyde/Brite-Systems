"""Public Streamlit interface regression checks."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_public_app_uses_only_the_verified_runtime(monkeypatch, tmp_path: Path) -> None:
    """Unsafe environment defaults must not become public runtime controls."""

    monkeypatch.setenv("EMBEDDING_BACKEND", "sentence-transformers")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("INDEX_DIR", str(tmp_path / "indexes"))
    monkeypatch.setenv("PROCESSED_PATH", str(tmp_path / "processed" / "chunks.json"))
    monkeypatch.setenv(
        "CORPUS_REPORT_PATH",
        str(tmp_path / "processed" / "corpus-report.json"),
    )

    app = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=30).run()

    assert not app.exception
    assert app.title[0].value == "⚖️ The Grounded Answer"
    assert not app.selectbox
    assert "Runtime mode" not in [header.value for header in app.header]
    assert (tmp_path / "indexes" / "manifest.json").is_file()

    app.chat_input[0].set_value(
        "How many days do I have to report a change that happened on 15 March 2026?"
    ).run(timeout=30)

    assert not app.exception
    assert app.success[0].icon == "⚖️"
    assert app.success[0].value.startswith("ANSWER")
    assert any("14 calendar days" in item.value for item in app.markdown)
