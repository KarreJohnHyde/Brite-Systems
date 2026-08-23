from __future__ import annotations

import json
from pathlib import Path


QUESTION_FILES = (
    "questions.json",
    "adversarial_questions.json",
    "temporal_questions.json",
)


def test_readme_catalogs_every_evaluation_question(project_root: Path) -> None:
    readme = (project_root / "README.md").read_text(encoding="utf-8")
    missing: list[str] = []

    for filename in QUESTION_FILES:
        cases = json.loads(
            (project_root / "evaluation" / filename).read_text(encoding="utf-8")
        )
        missing.extend(
            f"{filename}:{case['id']}"
            for case in cases
            if case["question"] not in readme
        )

    assert not missing, f"README question catalog is missing: {', '.join(missing)}"


def test_required_delivery_documents_cover_setup_and_disclosure(
    project_root: Path,
) -> None:
    readme = (project_root / "README.md").read_text(encoding="utf-8")
    decisions = (project_root / "DECISIONS.md").read_text(encoding="utf-8")
    ai_usage = (project_root / "AI-USAGE.md").read_text(encoding="utf-8")

    assert "python -m pip install -r requirements-dev.txt" in readme
    assert "python main.py ingest --embedding-backend hashing" in readme
    assert "python -m pytest -q" in readme
    assert "python -m streamlit run app.py" in readme
    assert "Rejected scope, delivery cuts, and next improvements" in decisions
    assert "AI-assisted development was used extensively" in ai_usage
