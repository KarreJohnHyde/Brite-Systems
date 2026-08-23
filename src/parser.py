"""Exact-source, clause-aware ingestion for the supplied Markdown manual."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path

from src.models import CombinedCorpusReport, IngestionReport, PolicyChunk

PART_RE = re.compile(r"^#+\s+Part\s+(\d+)\s*[—–-]\s*(.+?)\s*$")
SECTION_RE = re.compile(r"^#+\s+(\d+\.\d+)\s+(.+?)\s*$")
CLAUSE_RE = re.compile(r"^\*\*(\d+\.\d+\.\d+)(?:\s+([^*]+?))?\*\*\s*(.*)$")
CROSS_REF_RE = re.compile(r"§(\d+\.\d+(?:\.\d+[A-Z]?)?)")
VERSION_RE = re.compile(r"Consolidated text as at\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4})", re.IGNORECASE)
AMENDMENT_NUMBER_RE = re.compile(r"^##\s+Amendment\s+No\.\s+([\d-]+)\s*$", re.IGNORECASE)
AMENDMENT_SECTION_RE = re.compile(r"^##\s+(\d+)\.\s+(.+?)\s*$")
AMENDMENT_PARAGRAPH_RE = re.compile(r"^\*\*(\d+\.\d+)\*\*\s*(.*)$")
INSERTED_CLAUSE_RE = re.compile(r"^>\s*\*\*(\d+\.\d+\.\d+[A-Z]?)\*\*", re.MULTILINE)
ISSUED_RE = re.compile(r"^\*\*Issued:\*\*\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4})\s*$", re.MULTILINE)
EFFECTIVE_RE = re.compile(r"^\*\*Effective:\*\*\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4})\s*$", re.MULTILINE)
_SOURCE_BUNDLE_DOMAIN = b"grounded-answer-policy-source-bundle-v1\0"


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


def _effective_date(version: str | None) -> str | None:
    if version is None:
        return None
    try:
        return datetime.strptime(version, "%d %B %Y").date().isoformat()
    except ValueError as exc:
        raise CorpusParseError(f"Invalid consolidated policy date: {version}") from exc


def _source_date(value: str, *, label: str) -> str:
    try:
        return datetime.strptime(value, "%d %B %Y").date().isoformat()
    except ValueError as exc:
        raise CorpusParseError(f"Invalid {label} date: {value}") from exc


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
    effective_date = _effective_date(document_version)
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
                source_kind="manual",
                document_title="Calder County Household Support Program Policy Manual",
                text=display_text,
                raw_text=raw_text,
                normalized_text=_normalized(raw_text),
                source_text=source_text,
                part_id=current_part_id,
                part_title=current_part_title,
                section_id=current_section_id,
                section_title=current_section_title,
                clause_id=clause_id,
                locator_kind="clause",
                source_locator=f"manual:{clause_id}",
                source_locator_label=f"Policy Manual §{clause_id}",
                page=None,
                line_start=start_idx + 1,
                line_end=content_end,
                start_offset=start_offset,
                end_offset=end_offset,
                source_order=len(chunks),
                document_index=0,
                document_order=len(chunks),
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


def parse_policy_amendment(filepath: str | Path) -> list[PolicyChunk]:
    """Parse numbered amendment paragraphs as document-qualified sources."""

    path = Path(filepath).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Policy amendment not found at {path}")
    raw_bytes = path.read_bytes()
    try:
        source = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CorpusParseError(f"Amendment must be UTF-8 text: {path}") from exc

    lines = source.splitlines(keepends=True)
    byte_offsets = _line_byte_offsets(lines)
    number_match = next(
        (
            AMENDMENT_NUMBER_RE.match(line.strip())
            for line in lines
            if AMENDMENT_NUMBER_RE.match(line.strip())
        ),
        None,
    )
    issued_match = ISSUED_RE.search(source)
    effective_match = EFFECTIVE_RE.search(source)
    if number_match is None or issued_match is None or effective_match is None:
        raise CorpusParseError(
            "Amendment must state its number, issued date, and effective date"
        )

    amendment_number = number_match.group(1)
    issued_date = _source_date(issued_match.group(1), label="amendment issued")
    effective_date = _source_date(effective_match.group(1), label="amendment effective")
    document_id = f"calder-hsp-amendment-{amendment_number.lower()}"
    document_title = (
        f"Calder County Household Support Program Amendment No. {amendment_number}"
    )

    chunks: list[PolicyChunk] = []
    current_section_id: str | None = None
    current_section_title: str | None = None
    seen_paragraphs: set[str] = set()
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        section_match = AMENDMENT_SECTION_RE.match(stripped)
        if section_match:
            current_section_id = section_match.group(1)
            current_section_title = section_match.group(2).strip()
            i += 1
            continue

        paragraph_match = AMENDMENT_PARAGRAPH_RE.match(stripped)
        if not paragraph_match:
            i += 1
            continue
        if current_section_id is None or current_section_title is None:
            raise CorpusParseError(
                f"Amendment paragraph on line {i + 1} has no numbered section context"
            )

        paragraph_id = paragraph_match.group(1)
        if paragraph_id in seen_paragraphs:
            raise CorpusParseError(f"Duplicate amendment paragraph ¶{paragraph_id}")
        if paragraph_id.split(".", 1)[0] != current_section_id:
            raise CorpusParseError(
                f"Amendment paragraph ¶{paragraph_id} is under section {current_section_id}"
            )
        seen_paragraphs.add(paragraph_id)

        start_idx = i
        j = i + 1
        while j < len(lines):
            candidate = lines[j].strip()
            if (
                AMENDMENT_SECTION_RE.match(candidate)
                or AMENDMENT_PARAGRAPH_RE.match(candidate)
                or candidate == "---"
            ):
                break
            j += 1

        content_end = j
        while content_end > start_idx + 1 and not lines[content_end - 1].strip():
            content_end -= 1
        first_content = (paragraph_match.group(2) or "").strip()
        content_lines = [first_content] + [
            line.rstrip("\r\n") for line in lines[start_idx + 1 : content_end]
        ]
        while content_lines and not content_lines[-1].strip():
            content_lines.pop()
        raw_text = "\n".join(content_lines).strip()
        source_text = "".join(lines[start_idx:content_end]).rstrip("\r\n")
        start_offset = byte_offsets[start_idx]
        end_offset = start_offset + len(source_text.encode("utf-8"))
        source_digest = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
        locator = f"amendment-{amendment_number}:{paragraph_id}"
        chunk_id = "chunk_" + hashlib.sha256(
            f"{document_id}|{effective_date}|{paragraph_id}|{source_digest}".encode()
        ).hexdigest()[:16]
        references = sorted(set(CROSS_REF_RE.findall(raw_text)))
        inserts = sorted(set(INSERTED_CLAUSE_RE.findall(source_text)))

        chunks.append(
            PolicyChunk(
                chunk_id=chunk_id,
                document_id=document_id,
                document_name=path.name,
                document_version=f"Amendment No. {amendment_number}",
                effective_date=effective_date,
                source_kind="amendment",
                document_title=document_title,
                amendment_number=amendment_number,
                issued_date=issued_date,
                text=_display_text(raw_text),
                raw_text=raw_text,
                normalized_text=_normalized(raw_text),
                source_text=source_text,
                part_id=f"amendment-{amendment_number}",
                part_title=f"Amendment No. {amendment_number}",
                section_id=f"amendment-{amendment_number}.{current_section_id}",
                section_title=current_section_title,
                clause_id=None,
                official_clause_id=False,
                locator_kind="paragraph",
                source_locator=locator,
                source_locator_label=f"Amendment No. {amendment_number} ¶{paragraph_id}",
                amends_clause_ids=references,
                inserts_clause_ids=inserts,
                page=None,
                line_start=start_idx + 1,
                line_end=content_end,
                start_offset=start_offset,
                end_offset=end_offset,
                source_order=len(chunks),
                document_index=0,
                document_order=len(chunks),
                cross_references=references,
            )
        )
        i = j

    expected = {"1.1", "2.1", "2.2", "3.1", "4.1", "4.2", "5.1", "5.2", "5.3"}
    actual = {
        (chunk.source_locator or "").rsplit(":", 1)[-1]
        for chunk in chunks
    }
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        detail = []
        if missing:
            detail.append("missing " + ", ".join(missing))
        if unexpected:
            detail.append("unexpected " + ", ".join(unexpected))
        raise CorpusParseError(
            "Amendment No. 2026-01 paragraph structure is incomplete: " + "; ".join(detail)
        )
    return chunks


def parse_policy_sources(
    manual_path: str | Path,
    amendment_paths: Sequence[str | Path] | None = None,
) -> list[PolicyChunk]:
    """Parse an ordered policy source set with globally stable source order."""

    documents = [parse_policy_manual(manual_path)]
    for amendment_path in amendment_paths or ():
        documents.append(parse_policy_amendment(amendment_path))

    combined: list[PolicyChunk] = []
    for document_index, document_chunks in enumerate(documents):
        for document_order, chunk in enumerate(document_chunks):
            combined.append(
                chunk.model_copy(
                    update={
                        "source_order": len(combined),
                        "document_index": document_index,
                        "document_order": document_order,
                    }
                )
            )
    if len({chunk.chunk_id for chunk in combined}) != len(combined):
        raise CorpusParseError("The source set produced duplicate trusted chunk IDs")
    locators = [chunk.source_locator for chunk in combined if chunk.source_locator]
    if len(set(locators)) != len(locators):
        raise CorpusParseError("The source set contains duplicate document-qualified locators")
    return combined


def source_bundle_sha256(source_paths: Sequence[str | Path]) -> str:
    """Hash an ordered source set; preserve the legacy digest for one file."""

    paths = [Path(path).expanduser().resolve() for path in source_paths]
    if not paths:
        raise ValueError("At least one policy source is required")
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(f"Policy source not found at {path}")
    if len(paths) == 1:
        return hashlib.sha256(paths[0].read_bytes()).hexdigest()

    digest = hashlib.sha256()
    digest.update(_SOURCE_BUNDLE_DOMAIN)
    for path in paths:
        name = path.name.encode("utf-8")
        content = path.read_bytes()
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


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
        document_title=chunks[0].document_title,
        source_kind="manual",
        effective_date=chunks[0].effective_date,
    )


def build_amendment_report(
    filepath: str | Path,
    chunks: list[PolicyChunk],
) -> IngestionReport:
    """Create exact-source diagnostics for one parsed amendment."""

    if not chunks or any(chunk.source_kind != "amendment" for chunk in chunks):
        raise ValueError("Amendment report requires parsed amendment chunks")
    path = Path(filepath).expanduser().resolve()
    raw = path.read_bytes()
    lengths = [len(chunk.text) for chunk in chunks]
    return IngestionReport(
        document_id=chunks[0].document_id,
        document_name=path.name,
        document_version=chunks[0].document_version,
        source_sha256=hashlib.sha256(raw).hexdigest(),
        source_bytes=len(raw),
        source_lines=len(raw.decode("utf-8").splitlines()),
        pages=None,
        parts=0,
        sections=len({chunk.section_id for chunk in chunks if chunk.section_id}),
        clauses=len(chunks),
        chunks=len(chunks),
        average_chunk_characters=round(sum(lengths) / len(lengths), 2),
        largest_chunk_characters=max(lengths),
        duplicate_clause_groups=[],
        unresolved_cross_references=[],
        parser="markdown-amendment-v1",
        document_title=chunks[0].document_title,
        source_kind="amendment",
        effective_date=chunks[0].effective_date,
        issued_date=chunks[0].issued_date,
    )


def build_combined_corpus_report(
    source_paths: Sequence[str | Path],
    chunks: list[PolicyChunk],
) -> CombinedCorpusReport:
    """Report provenance and cross-reference integrity for all authorities."""

    paths = [Path(path).expanduser().resolve() for path in source_paths]
    if not paths:
        raise ValueError("At least one policy source is required")
    by_document: dict[str, list[PolicyChunk]] = defaultdict(list)
    for chunk in chunks:
        by_document[chunk.document_id].append(chunk)

    reports: list[IngestionReport] = []
    for index, path in enumerate(paths):
        matching = sorted(
            (
                chunk
                for chunk in chunks
                if chunk.document_index == index
            ),
            key=lambda chunk: chunk.document_order or 0,
        )
        if not matching:
            raise ValueError(f"No parsed chunks were associated with policy source {path}")
        if matching[0].source_kind == "manual":
            reports.append(build_corpus_report(path, matching))
        else:
            reports.append(build_amendment_report(path, matching))

    locators = [chunk.source_locator for chunk in chunks if chunk.source_locator]
    locator_counts: dict[str, int] = defaultdict(int)
    for locator in locators:
        locator_counts[locator] += 1
    duplicates = sorted(locator for locator, count in locator_counts.items() if count > 1)

    known_clause_ids = {
        chunk.clause_id for chunk in chunks if chunk.clause_id
    } | {
        inserted
        for chunk in chunks
        for inserted in chunk.inserts_clause_ids
    }
    known_section_ids = {
        chunk.section_id for chunk in chunks if chunk.source_kind == "manual" and chunk.section_id
    }
    unresolved = sorted(
        {
            reference
            for chunk in chunks
            for reference in chunk.cross_references
            if reference not in known_clause_ids and reference not in known_section_ids
        }
    )
    combined_digest = source_bundle_sha256(paths)
    return CombinedCorpusReport(
        combined_source_sha256=combined_digest,
        source_sha256=combined_digest,
        source_reports=reports,
        documents=len(reports),
        source_bytes=sum(report.source_bytes for report in reports),
        source_lines=sum(report.source_lines for report in reports),
        clauses=sum(report.clauses for report in reports),
        chunks=len(chunks),
        duplicate_source_locators=duplicates,
        unresolved_cross_references=unresolved,
    )


def persist_chunks(
    chunks: list[PolicyChunk],
    report: IngestionReport | CombinedCorpusReport,
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
        f"LOCATOR: {chunk.source_locator_label or chunk.source_locator or chunk.clause_id or 'internal'}\n"
        f"SECTION: {chunk.section_id or 'unknown'} {chunk.section_title or ''}\n"
        f"PAGE: {page}\n"
        f"LINES: {chunk.line_start}-{chunk.line_end}\n"
        f"TEXT:\n{chunk.text}\n"
        "</POLICY_EXCERPT>"
    )


def find_chunks(chunks: Iterable[PolicyChunk], source_id: str) -> list[PolicyChunk]:
    """Resolve a trusted chunk, manual clause, section, amendment paragraph, or insertion."""

    raw = source_id.strip()
    cleaned = raw.removeprefix("§")
    normalized_locator = re.sub(
        r"^amendment\s+no\.\s+([\d-]+)\s*¶\s*",
        r"amendment-\1:",
        raw,
        flags=re.IGNORECASE,
    )
    return [
        chunk
        for chunk in chunks
        if chunk.chunk_id == cleaned
        or chunk.clause_id == cleaned
        or chunk.section_id == cleaned
        or chunk.source_locator == raw
        or chunk.source_locator == normalized_locator
        or cleaned in chunk.inserts_clause_ids
    ]


# Compatibility name retained for external imports from the original prototype.
PolicyClause = PolicyChunk


if __name__ == "__main__":
    default = Path(__file__).resolve().parent.parent / "data" / "policy-manual.md"
    parsed = parse_policy_manual(default)
    print(build_corpus_report(default, parsed).model_dump_json(indent=2))
