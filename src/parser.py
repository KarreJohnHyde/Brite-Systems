"""Exact-source, clause-aware ingestion for the supplied Markdown manual."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

from src.models import IngestionReport, PolicyChunk

PART_RE = re.compile(r"^#\s+Part\s+(\d+)\s*[—–-]\s*(.+?)\s*$")
SECTION_RE = re.compile(r"^##\s+(\d+\.\d+)\s+(.+?)\s*$")
CLAUSE_RE = re.compile(r"^\*\*(\d+\.\d+\.\d+)(?:\s+([^*]+?))?\*\*\s*(.*)$")
CROSS_REF_RE = re.compile(r"§(\d+\.\d+(?:\.\d+)?)")
VERSION_RE = re.compile(r"Consolidated text as at\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4})", re.IGNORECASE)


class CorpusParseError(ValueError):
    """Raised when the supplied corpus does not match its declared structure."""


def _document_id(path: Path) -> str:
    stem = re.sub(r"[^a-z0-9]+", "-", path.stem.lower()).strip("-")
    if stem == "policy-manual":
        return "calder-hsp-policy-manual"
    return stem or "policy-document"


def _normalized(text: str) -> str:
    without_markdown = text.replace("**", "").replace("`", "")
    return re.sub(r"\s+", " ", without_markdown).strip()


def _display_text(raw_text: str) -> str:
    """Remove emphasis markup while retaining policy wording and layout."""

    return raw_text.replace("**", "").replace("`", "").strip()


def _line_byte_offsets(lines: list[str]) -> list[int]:
    offsets = [0]
    total = 0
    for line in lines:
        total += len(line.encode("utf-8"))
        offsets.append(total)
    return offsets


def parse_policy_manual(filepath: str | Path) -> list[PolicyChunk]:
    """Parse official `X.Y.Z` provisions without inventing page metadata.

    The returned half-open offsets are UTF-8 byte offsets into the original file.
    `source_text` contains the exact Markdown source for the provision; `raw_text`
    removes only the bold clause-ID marker; and `normalized_text` is retrieval-only.
    """

    path = Path(filepath).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(
            f"Policy corpus not found at {path}. Place the supplied policy-manual.md "
            "there or pass --corpus PATH."
        )
    raw_bytes = path.read_bytes()
    try:
        source = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CorpusParseError(f"Corpus must be UTF-8 text: {path}") from exc

    lines = source.splitlines(keepends=True)
    byte_offsets = _line_byte_offsets(lines)
    version_match = VERSION_RE.search(source)
    document_version = version_match.group(1) if version_match else None
    effective_date = "2025-12-31" if document_version == "31 December 2025" else None
    doc_id = _document_id(path)

    chunks: list[PolicyChunk] = []
    current_part_id: str | None = None
    current_part_title: str | None = None
    current_section_id: str | None = None
    current_section_title: str | None = None
    seen_clause_ids: set[str] = set()

    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        part_match = PART_RE.match(stripped)
        if part_match:
            current_part_id = part_match.group(1)
            current_part_title = part_match.group(2).strip()
            current_section_id = None
            current_section_title = None
            i += 1
            continue

        section_match = SECTION_RE.match(stripped)
        if section_match:
            current_section_id = section_match.group(1)
            current_section_title = section_match.group(2).strip()
            i += 1
            continue

        clause_match = CLAUSE_RE.match(stripped)
        if not clause_match:
            i += 1
            continue

        if not current_part_id or not current_section_id:
            raise CorpusParseError(f"Clause on line {i + 1} has no Part/section context")

        clause_id = clause_match.group(1)
        if clause_id in seen_clause_ids:
            raise CorpusParseError(f"Duplicate official clause ID §{clause_id}")
        seen_clause_ids.add(clause_id)

        start_idx = i
        j = i + 1
        while j < len(lines):
            candidate = lines[j].strip()
            if (
                PART_RE.match(candidate)
                or SECTION_RE.match(candidate)
                or CLAUSE_RE.match(candidate)
                or candidate == "---"
            ):
                break
            j += 1

        content_end = j
        while content_end > start_idx + 1 and not lines[content_end - 1].strip():
            content_end -= 1

        first_title = (clause_match.group(2) or "").strip()
        first_remainder = (clause_match.group(3) or "").strip()
        first_content = " ".join(part for part in (first_title, first_remainder) if part)
        content_lines = [first_content] + [line.rstrip("\r\n") for line in lines[start_idx + 1 : content_end]]
        while content_lines and not content_lines[-1].strip():
            content_lines.pop()
        raw_text = "\n".join(content_lines).strip()
        source_text = "".join(lines[start_idx:content_end]).rstrip("\r\n")

        start_offset = byte_offsets[start_idx]
        end_offset = start_offset + len(source_text.encode("utf-8"))
        source_digest = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
        chunk_id = "chunk_" + hashlib.sha256(
            f"{doc_id}|{document_version}|{clause_id}|{source_digest}".encode()
        ).hexdigest()[:16]
        display_text = _display_text(raw_text)

        chunks.append(
            PolicyChunk(
                chunk_id=chunk_id,
                document_id=doc_id,
                document_name=path.name,
                document_version=document_version,
                effective_date=effective_date,
                text=display_text,
                raw_text=raw_text,
                normalized_text=_normalized(raw_text),
                source_text=source_text,
                part_id=current_part_id,
                part_title=current_part_title,
                section_id=current_section_id,
                section_title=current_section_title,
                clause_id=clause_id,
                page=None,
                line_start=start_idx + 1,
                line_end=content_end,
                start_offset=start_offset,
                end_offset=end_offset,
                source_order=len(chunks),
                cross_references=sorted(set(CROSS_REF_RE.findall(raw_text))),
            )
        )
        i = j

    if not chunks:
        raise CorpusParseError(
            "No official clauses were detected. Expected Markdown provisions such as "
            "'**4.3.2** Policy text'."
        )
    return chunks


def build_corpus_report(filepath: str | Path, chunks: list[PolicyChunk]) -> IngestionReport:
    """Create reproducible corpus diagnostics without changing source truth."""

    path = Path(filepath).expanduser().resolve()
    raw = path.read_bytes()
    by_text: dict[str, list[str]] = defaultdict(list)
    for chunk in chunks:
        by_text[chunk.normalized_text].append(chunk.clause_id or chunk.chunk_id)
    duplicate_groups = [ids for ids in by_text.values() if len(ids) > 1]

    clause_ids = {chunk.clause_id for chunk in chunks if chunk.clause_id}
    section_ids = {chunk.section_id for chunk in chunks if chunk.section_id}
    unresolved: set[str] = set()
    for chunk in chunks:
        for ref in chunk.cross_references:
            if ref not in clause_ids and ref not in section_ids:
                unresolved.add(ref)

    lengths = [len(chunk.text) for chunk in chunks]
    return IngestionReport(
        document_id=chunks[0].document_id,
        document_name=path.name,
        document_version=chunks[0].document_version,
        source_sha256=hashlib.sha256(raw).hexdigest(),
        source_bytes=len(raw),
        source_lines=len(raw.decode("utf-8").splitlines()),
        pages=None,
        parts=len({chunk.part_id for chunk in chunks}),
        sections=len(section_ids),
        clauses=len({chunk.clause_id for chunk in chunks}),
        chunks=len(chunks),
        average_chunk_characters=round(sum(lengths) / len(lengths), 2),
        largest_chunk_characters=max(lengths),
        duplicate_clause_groups=sorted(duplicate_groups),
        unresolved_cross_references=sorted(unresolved),
    )


def persist_chunks(
    chunks: list[PolicyChunk],
    report: IngestionReport,
    chunks_path: str | Path,
    report_path: str | Path,
) -> None:
    """Persist trusted chunk metadata and corpus diagnostics as UTF-8 JSON."""

    chunks_target = Path(chunks_path)
    report_target = Path(report_path)
    chunks_target.parent.mkdir(parents=True, exist_ok=True)
    report_target.parent.mkdir(parents=True, exist_ok=True)
    chunks_target.write_text(
        json.dumps([chunk.model_dump(mode="json") for chunk in chunks], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    report_target.write_text(
        report.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )


def load_chunks(path: str | Path) -> list[PolicyChunk]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return [PolicyChunk.model_validate(item) for item in payload]


def get_embedding_text(chunk: PolicyChunk) -> str:
    """Retrieval representation with official hierarchy as context."""

    hierarchy = " | ".join(
        part
        for part in (
            f"Part {chunk.part_id}: {chunk.part_title}" if chunk.part_id else None,
            f"Section {chunk.section_id}: {chunk.section_title}" if chunk.section_id else None,
            f"Clause {chunk.clause_id}" if chunk.clause_id else None,
        )
        if part
    )
    return f"{hierarchy} | {chunk.normalized_text}"


def format_clause_for_context(chunk: PolicyChunk) -> str:
    """Delimit corpus text as untrusted data with an opaque trusted ID."""

    page = str(chunk.page) if chunk.page is not None else "not available"
    return (
        "<POLICY_EXCERPT>\n"
        f"SOURCE_ID: {chunk.chunk_id}\n"
        f"CLAUSE: {chunk.clause_id or 'internal'}\n"
        f"SECTION: {chunk.section_id or 'unknown'} {chunk.section_title or ''}\n"
        f"PAGE: {page}\n"
        f"LINES: {chunk.line_start}-{chunk.line_end}\n"
        f"TEXT:\n{chunk.text}\n"
        "</POLICY_EXCERPT>"
    )


def find_chunks(chunks: Iterable[PolicyChunk], source_id: str) -> list[PolicyChunk]:
    """Resolve an opaque chunk ID, official clause ID, or section ID."""

    cleaned = source_id.strip().removeprefix("§")
    return [
        chunk
        for chunk in chunks
        if chunk.chunk_id == cleaned
        or chunk.clause_id == cleaned
        or chunk.section_id == cleaned
    ]


# Compatibility name retained for external imports from the original prototype.
PolicyClause = PolicyChunk


if __name__ == "__main__":
    default = Path(__file__).resolve().parent.parent / "data" / "policy-manual.md"
    parsed = parse_policy_manual(default)
    print(build_corpus_report(default, parsed).model_dump_json(indent=2))
