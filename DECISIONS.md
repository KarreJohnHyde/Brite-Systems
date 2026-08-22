# Architecture and Safety Decisions

This document records the decisions that define the answering/refusal boundary
for The Grounded Answer. The product is a policy lookup and evidence system, not
an autonomous benefits or legal decision-maker.

## 1. Architecture decision: explicit evidence pipeline

**Decision:** Keep parsing, indexing, retrieval, evidence assessment,
contradiction detection, decision logic, answer construction, provider access,
citation validation, and presentation as separate components.

**Why:** A monolithic RAG chain makes it difficult to distinguish a retrieval
miss from insufficient support, a missed conflict, a generation error, or a bad
citation. The composition root in `src/pipeline.py` makes the order explicit:

```text
retrieve → assess support → detect conflicts/gaps → decide
         → build answer/refusal/conflict → validate citations
```

Generation occurs only after the state machine decides. There is no answer-first
or post-hoc citation-matching path.

**Trade-off:** More interfaces and trace objects are required, but failures are
inspectable and a day-two change can replace one stage without rewriting the
whole application.

## 2. Parsing decision: preserve the supplied Markdown structure

**Decision:** Parse the actual `data/policy-manual.md` hierarchy of Parts,
sections, numbered clauses, sub-items, and tables. Do not use fixed character
windows as the primary chunking strategy.

The source identifies itself as the Calder County Household Support Program
Policy Manual, consolidated as at 31 December 2025, and says that all named
entities and case details are fictitious. No synthetic replacement corpus is
generated.

Each `PolicyChunk` preserves:

- exact source text separately from normalized retrieval text;
- official clause, section, and part identifiers;
- source order, line range, UTF-8 offsets, and cross-references;
- document name and version metadata; and
- a deterministic opaque chunk ID derived from trusted source content.

The Markdown source has no authoritative pages. The system records `page=None`
and renders exact clause and line citations instead of inventing page numbers.
Ingestion also records the corpus SHA-256 and refuses to load an index built from
a different source file.

## 3. Retrieval decision: deterministic hybrid baseline

**Decision:** Use stable local hashing vectors plus lexical BM25 and reciprocal
rank fusion by default. Neighbor and cross-reference expansion may add adjacent
or incorporated clauses. Preserve vector, lexical, fused, and reranker scores as
different fields.

**Why:** Policy questions often depend on exact identifiers, deadlines, amounts,
and defined terms that lexical retrieval handles well. Hashing is reproducible,
credential-free, fast to rebuild, and requires no model download. It gives the
challenge a safe baseline that works without an API key.

**Optional path:** `sentence-transformers/all-MiniLM-L6-v2` can replace hashing,
and `cross-encoder/ms-marco-MiniLM-L-6-v2` can rerank candidates. Reranking is
disabled by default. Its score distribution is not treated as a probability or
as evidence sufficiency. An unavailable reranker is skipped rather than making
the baseline unusable.

**Integrity rule:** The query backend and embedding model must match the index
manifest. Switching backends requires re-ingestion.

## 4. Evidence decision: relevance is not support

**Decision:** Classify question-to-clause support separately from retrieval as
`DIRECT`, `PARTIAL`, `RELATED_ONLY`, or `NONE`. Conflict evidence is represented
through explicit `ConflictFinding` records.

The evidence analyzer combines topic coverage, question intent, answer
alignment, and retrieval signals. These values are transparent heuristics, not
probabilities. A top-ranked passage cannot authorize `ANSWER` merely because it
is semantically similar.

Human-reviewed corpus findings live in `data/policy_findings.json`. They are
metadata about the unchanged source, not corrected policy rules.

## 5. Refusal boundary

**Decision:** Default toward refusal whenever a safe complete answer cannot be
established.

The decision engine returns `REFUSE` when any of the following applies:

1. A reviewed manual gap matches the material question.
2. The question asks for an individual determination or case-history explanation
   that requires facts or records not supplied by the manual.
3. No retrieved clause is classified as `DIRECT` support.
4. Only related or partial evidence exists.
5. A compound question has a material aspect that lacks direct support.
6. The best direct support is below the configured refusal threshold.
7. Provider output is malformed, changes the trusted decision, selects an
   unretrieved source ID, or fails claim/citation validation.
8. The index and current corpus or selected embedding backend do not match; in
   this case the command fails safely and asks for re-ingestion.

The deterministic refusal wording states that the manual does not clearly settle
the question. The next step comes from source-backed organizational roles in
`data/contacts.json`; no phone number, email address, or personal name is
invented.

**Rationale:** In this domain, false answers can cause users to miss deadlines,
misstate eligibility, or take action on a rule the source never established.
Precision and citation integrity are therefore prioritized over answer coverage.

## 6. Contradiction handling

**Decision:** Return `CONFLICT` before considering `ANSWER` when relevant clauses
are materially incompatible and the manual provides no precedence rule.

The detector combines:

- source-verified conflict findings tied to exact clause IDs; and
- conservative deterministic checks for incompatible quantities or polarity
  among sufficiently relevant clauses.

Scoped exceptions, extensions, and different populations should not be treated
as conflicts merely because their numbers differ. Where scope cannot be resolved,
the system does not choose a winner. `CONFLICT` must cite at least two trusted
sources, explain why no single rule controls, and provide escalation guidance.

Confirmed source issues currently include:

- §4.3.2 versus §9.1.4 on a 10-day versus 30-day change-reporting period; and
- §4.1.1 versus §10.5.2 on exclusion from eligibility versus a 20% award
  reduction as the effect of a sanction.

## 7. Known-gap handling

**Decision:** Record reviewed gaps outside the manual and use them to force a
transparent refusal for matching questions. Do not insert missing rules into the
corpus.

Reviewed gaps include the broken full-time-student needs cross-reference,
full-time-education absence, classification or valuation of unlisted resources,
some multi-adult needs calculations, no-fixed-address application details, and
the undefined cost components used by the housing-assistance adjustment. The
complete scopes and citations are in `data/policy_findings.json`.

## 8. Calibration decision

**Decision:** Keep retrieval relevance and evidence sufficiency thresholds
separate and calibrate them against source-derived labeled cases. The checked-in
safe starting values are:

```text
REFUSAL_THRESHOLD=0.58
DIRECT_COVERAGE_THRESHOLD=0.34
```

`python main.py calibrate --embedding-backend hashing` sweeps candidate support
thresholds. `python main.py evaluate --embedding-backend hashing` is the release
check. Any backend, corpus, model, or retrieval-setting change requires the
calibration and evaluation to be rerun.

Threshold selection must inspect the error types, not only aggregate accuracy.
The governing priority is:

```text
false ANSWER / unsupported claim
    > bad or missing citation
    > missed CONFLICT
    > false REFUSE
```

The evaluation report, rather than prose in this file, is the authoritative
record of measured results. Failed cases must remain visible.

## 9. Citation-integrity decision

**Decision:** Treat citation metadata as trusted program data, never model-authored
text.

The provider receives opaque chunk IDs with selected excerpts. It may select only
those IDs. The program maps selected IDs back to ingestion metadata, rejects
unknown or duplicate IDs, and enforces the state contract:

- `ANSWER` requires at least one trusted citation;
- `CONFLICT` requires at least two trusted citations; and
- `REFUSE` never fabricates supporting evidence.

Claim validation also rejects obvious invented official clause IDs and numeric
values absent from the selected sources. A validation failure becomes `REFUSE`,
not a warning attached to an unsafe answer.

Persisted FAISS and metadata artifacts carry SHA-256 checksums. At load time,
the program also reparses the authoritative corpus and requires every indexed
citation field—including exact text, official ID, offsets, and line range—to
match that source-derived record. The manifest alone is not treated as proof of
citation truth.

## 10. Answer-construction and provider decision

**Decision:** Deterministic, source-forward answer construction is the default.
It uses selected source text and requires no API key.

Gemini is an optional implementation of the `LLMProvider` interface. It can
rephrase only an already-authorized `ANSWER`; it cannot override the decision
engine. Structured provider output is validated with Pydantic and source-ID
allowlisting. Any provider or validation exception produces a safe refusal.

**Trade-off:** Deterministic answers are less conversational, but they are stable,
inspectable, private by default, and remain available when an external service is
unavailable.

## 11. Privacy and prompt-injection decision

**Decision:** Keep the default path local and treat both user input and policy
text as untrusted data.

- Deterministic mode does not send questions or excerpts to an external model.
- Gemini mode sends only the question and selected policy excerpts with opaque
  IDs. Unrelated local files are never included.
- The provider system prompt explicitly treats policy excerpts as data whose
  embedded instructions must not be followed.
- `.env` and Streamlit secrets are ignored by Git.
- Logs and debug traces can contain questions and source excerpts, so they must
  be handled as potentially sensitive artifacts.

## 12. Configuration decision

**Decision:** Centralize paths, backend selection, feature flags, retrieval sizes,
thresholds, and provider settings in the validated `Settings` model. Precedence
is explicit CLI override, then environment/`.env`, then safe defaults.

The generated index and processed chunks are reproducible artifacts and are not
committed. The source corpus, reviewed findings, escalation descriptions,
evaluation labels, and documentation are committed.

## 13. Key trade-offs

- **Precision over recall:** unanswered questions are acceptable; unsupported
  answers are not.
- **Safety over coverage:** partial evidence triggers refusal when a material
  aspect remains open.
- **Traceability over abstraction:** custom, small components are preferred to an
  opaque framework chain.
- **Local determinism over fluent prose:** optional generation cannot become a
  runtime dependency for core behavior.
- **Retrieval quality over minimum latency:** hybrid search and neighbor retrieval
  add work but improve exact-term and incorporated-rule recall.
- **Curated findings over silent normalization:** reviewed source problems are
  surfaced, not repaired.

## 14. Known failure modes

1. Novel paraphrases or vocabulary outside the manual can cause retrieval misses
   or false refusals.
2. Compound questions may be split imperfectly, causing a false refusal or an
   incomplete source selection.
3. Numeric conflict rules can confuse a scoped exception with a contradiction;
   the detector is deliberately conservative and reviewed findings take priority.
4. A contradiction or gap not yet represented in reviewed metadata can be missed.
5. Line citations change if the source file is reformatted; the corpus digest
   forces re-ingestion but cannot preserve old line numbers.
6. Sentence Transformer and reranker behavior depends on downloaded model files,
   hardware, and library versions; it must be evaluated separately from hashing.
7. Gemini behavior and service availability are external variables. Provider
   failure safely reduces coverage to refusal.
8. The parser is tailored to the supplied numbered Markdown structure and does
   not handle scanned PDFs or arbitrary manual layouts.
9. The system has no case record, external statute, or regulatory database. It
   cannot determine source precedence beyond what the manual itself establishes.
10. Evaluation cases demonstrate selected behavior but cannot prove that every
    possible wording or policy issue is handled.

These limitations are release information, not optional future clean-up. New
failures should be classified, preserved as regression cases, and repaired in
the responsible component.
