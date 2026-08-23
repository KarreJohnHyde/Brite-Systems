"""Central, environment-backed settings for The Grounded Answer."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Settings(BaseModel):
    """Validated settings shared by ingestion, retrieval, and decision logic."""

    model_config = ConfigDict(frozen=True)

    project_root: Path = PROJECT_ROOT
    corpus_path: Path = PROJECT_ROOT / "data" / "policy-manual.md"
    processed_path: Path = PROJECT_ROOT / "data" / "processed" / "chunks.json"
    corpus_report_path: Path = PROJECT_ROOT / "data" / "processed" / "corpus-report.json"
    index_dir: Path = PROJECT_ROOT / "data" / "indexes"
    findings_path: Path = PROJECT_ROOT / "data" / "policy_findings.json"
    contacts_path: Path = PROJECT_ROOT / "data" / "contacts.json"

    embedding_backend: Literal["hashing", "sentence-transformers"] = "hashing"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dimension: int = Field(default=768, ge=64, le=4096)
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    enable_hybrid_search: bool = True
    enable_reranking: bool = False
    require_reranker: bool = False
    enable_neighbor_retrieval: bool = True
    enable_contradiction_check: bool = True
    enable_claim_validation: bool = True
    initial_retrieval_k: int = Field(default=18, ge=3, le=100)
    rerank_k: int = Field(default=8, ge=2, le=50)
    final_k: int = Field(default=6, ge=2, le=25)
    rrf_k: int = Field(default=60, ge=1, le=500)
    refusal_threshold: float = Field(default=0.58, ge=0.0, le=1.0)
    direct_coverage_threshold: float = Field(default=0.34, ge=0.0, le=1.0)

    llm_provider: Literal["deterministic", "gemini"] = "deterministic"
    gemini_model: str = "gemini-3.6-flash"
    gemini_thinking_level: Literal["minimal", "low", "medium", "high"] = "minimal"
    gemini_api_key: str | None = None
    langsmith_tracing: bool = False
    langsmith_api_key: str | None = None
    langsmith_project: str = "grounded-answer"
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    langsmith_workspace_id: str | None = None
    log_level: str = "WARNING"

    @field_validator(
        "corpus_path",
        "processed_path",
        "corpus_report_path",
        "index_dir",
        "findings_path",
        "contacts_path",
        mode="before",
    )
    @classmethod
    def _expand_path(cls, value: str | Path) -> Path:
        return Path(value).expanduser().resolve()

    @classmethod
    def from_env(
        cls,
        *,
        project_root: str | Path | None = None,
        corpus_path: str | Path | None = None,
        embedding_backend: str | None = None,
        llm_provider: str | None = None,
    ) -> "Settings":
        """Load `.env`, environment values, and explicit CLI overrides."""

        try:
            from dotenv import load_dotenv

            load_dotenv((Path(project_root) if project_root else PROJECT_ROOT) / ".env")
        except ImportError:
            pass

        root = Path(project_root).resolve() if project_root else PROJECT_ROOT

        def path_env(name: str, relative: str) -> Path:
            raw = os.getenv(name)
            return Path(raw).expanduser().resolve() if raw else root / relative

        data: dict[str, object] = {
            "project_root": root,
            "corpus_path": Path(corpus_path).resolve() if corpus_path else path_env("CORPUS_PATH", "data/policy-manual.md"),
            "processed_path": path_env("PROCESSED_PATH", "data/processed/chunks.json"),
            "corpus_report_path": path_env("CORPUS_REPORT_PATH", "data/processed/corpus-report.json"),
            "index_dir": path_env("INDEX_DIR", "data/indexes"),
            "findings_path": path_env("POLICY_FINDINGS_PATH", "data/policy_findings.json"),
            "contacts_path": path_env("CONTACTS_PATH", "data/contacts.json"),
            "embedding_backend": embedding_backend or os.getenv("EMBEDDING_BACKEND", "hashing"),
            "embedding_model": os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"),
            "embedding_dimension": int(os.getenv("EMBEDDING_DIMENSION", "768")),
            "reranker_model": os.getenv("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2"),
            "enable_hybrid_search": _env_bool("ENABLE_HYBRID_SEARCH", True),
            "enable_reranking": _env_bool("ENABLE_RERANKING", False),
            "require_reranker": _env_bool("REQUIRE_RERANKER", False),
            "enable_neighbor_retrieval": _env_bool("ENABLE_NEIGHBOR_RETRIEVAL", True),
            "enable_contradiction_check": _env_bool("ENABLE_CONTRADICTION_CHECK", True),
            "enable_claim_validation": _env_bool("ENABLE_CLAIM_VALIDATION", True),
            "initial_retrieval_k": int(os.getenv("INITIAL_RETRIEVAL_K", "18")),
            "rerank_k": int(os.getenv("RERANK_K", "8")),
            "final_k": int(os.getenv("FINAL_K", "6")),
            "rrf_k": int(os.getenv("RRF_K", "60")),
            "refusal_threshold": float(os.getenv("REFUSAL_THRESHOLD", "0.58")),
            "direct_coverage_threshold": float(os.getenv("DIRECT_COVERAGE_THRESHOLD", "0.34")),
            "llm_provider": llm_provider or os.getenv("LLM_PROVIDER", "deterministic"),
            "gemini_model": os.getenv("GEMINI_MODEL", "gemini-3.6-flash"),
            "gemini_thinking_level": os.getenv("GEMINI_THINKING_LEVEL", "minimal"),
            "gemini_api_key": os.getenv("GEMINI_API_KEY") or None,
            "langsmith_tracing": _env_bool("LANGSMITH_TRACING", False),
            "langsmith_api_key": (
                os.getenv("LANGSMITH_API_KEY")
                or os.getenv("LANGCHAIN_API_KEY")
                or None
            ),
            "langsmith_project": os.getenv("LANGSMITH_PROJECT", "grounded-answer"),
            "langsmith_endpoint": os.getenv(
                "LANGSMITH_ENDPOINT", "https://api.smith.langchain.com"
            ),
            "langsmith_workspace_id": os.getenv("LANGSMITH_WORKSPACE_ID") or None,
            "log_level": os.getenv("LOG_LEVEL", "WARNING").upper(),
        }
        return cls.model_validate(data)
