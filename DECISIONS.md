# Architecture and Safety Decisions

This document records the decisions that define the answering/refusal boundary
for The Grounded Answer. The product is a policy lookup and evidence system, not
an autonomous benefits or legal decision-maker.

## 1. Architecture decision: explicit evidence pipeline

**Decision:** Keep source parsing, temporal applicability, indexing, retrieval,
evidence assessment, contradiction detection, decision logic, answer
construction, provider access, citation validation, and presentation as separate
components.

**Why:** A monolithic RAG chain makes it difficult to distinguish a retrieval
miss from insufficient support, a missed conflict, a generation error, or a bad
citation. The composition root in `src/pipeline.py` makes the order explicit:

```text
parse source bundle → validate timeline → resolve controlling date
                    → retrieve when needed → assess support
                    → detect conflicts/gaps → decide
                    → build answer/refusal/conflict → validate citations
```

Generation occurs only after the state machine decides. There is no answer-first
or post-hoc citation-matching path.

**Trade-off:** More interfaces and trace objects are required, but failures are
inspectable and a day-two change can replace one stage without rewriting the
whole application.

## 2. Parsing decision: preserve the supplied Markdown sources

**Decision:** Parse the actual `data/policy-manual.md` hierarchy of Parts,
sections, numbered clauses, sub-items, and tables, plus
`data/amendment-2026-01.md` paragraph structure and inserted text. Do not use
fixed character windows as the primary chunking strategy.

The base source identifies itself as the Calder County Household Support Program
Policy Manual, consolidated as at 31 December 2025, and says that all named
entities and case details are fictitious. Amendment No. 2026-01 is an additional
authority effective 1 March 2026, not a synthetic replacement consolidated
manual. Challenge instructions and Finder metadata are not evidence sources.

Each `PolicyChunk` preserves:

- exact source text separately from normalized retrieval text;
- official clause, section, and part identifiers or an amendment paragraph
  locator;
- source order, line range, UTF-8 offsets, and cross-references;
- document name, source kind, effective date, and version metadata; and
- a deterministic opaque chunk ID derived from trusted source content.

The Markdown sources have no authoritative pages. The system records `page=None`
and renders exact manual-clause or amendment-paragraph citations with line ranges
instead of inventing page numbers. Ingestion records a source-bundle SHA-256 and
refuses to load an index built from different authoritative sources.

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

Exact official clause references are pinned into the final evidence set. BM25
uses only unique, one-edit corpus-vocabulary corrections for words of at least
five characters, and reranking cannot discard BM25's top lexical candidate.
These are recall safeguards, not evidence authorization; every result still
passes independent support assessment.

### 3.1 Local training and promotion decision

**Decision:** Training is limited to the Sentence Transformer bi-encoder and
CrossEncoder reranker. Do not fine-tune the answer generator from the
source-derived labels: they contain decisions, evidence IDs, facts, and forbidden
claims, but no human-authored target answers. Gemini is hosted and outside this
local training boundary. Hashing, BM25, FAISS `IndexFlatIP`, and deterministic
safety logic have no learned parameters.

Training uses two rotating, clause-disjoint folds so every query is held out
once. Hard negatives exclude gold clauses, their section, adjacent clauses,
cross-references, reverse cross-references, and protected evidence from the
other fold. Final all-data artifacts are explicitly in-sample candidates, not
test evidence. Local model directories and their separate FAISS index are
immutable and SHA-256 bound; required-reranker evaluation fails closed.

Earlier training artifacts are preserved as historical experiments, not as
evidence that a candidate remains safe after a source-bundle or timeline change.
The small reviewed sample, single seed, and lack of a blind staff-query set mean
that candidate promotion requires fresh amendment-aware evaluation, no safety
regression, and a material held-out ranking improvement.

## 4. Evidence decision: relevance is not support

**Decision:** Classify question-to-clause support separately from retrieval as
`DIRECT`, `PARTIAL`, `RELATED_ONLY`, or `NONE`. Conflict evidence is represented
through explicit `ConflictFinding` records.

The evidence analyzer combines topic coverage, question intent, answer
alignment, and retrieval signals. These values are transparent heuristics, not
probabilities. A top-ranked passage cannot authorize `ANSWER` merely because it
is semantically similar.

Human-reviewed source findings live in `data/policy_findings.json`, while
date-bound amendment operations live in `data/policy_timeline.json`. They are
metadata about the authoritative sources, not corrected or invented policy rules.

## 5. Refusal boundary

**Decision:** Default toward refusal whenever a safe complete answer cannot be
established.

The decision engine returns `REFUSE` when any of the following applies:

1. A standalone question supplies no policy anchor, depends on missing
   conversational context, or omits a legally controlling date, such as “How long
   do I have?” when an amendment makes the event date decisive.
2. A reviewed manual gap matches the material question.
3. The question asks for an individual determination or case-history explanation
   that requires facts or records not supplied by the manual.
4. No retrieved clause is classified as `DIRECT` support.
5. Only related or partial evidence exists.
6. A compound question has a material aspect that lacks direct support.
7. The best direct support is below the configured refusal threshold.
8. Neither optional model phrasing nor the trusted-source fallback can produce
   a valid answer contract.
9. The index and current source bundle, reviewed metadata/timeline, or selected
   embedding backend do not match; in this case the command fails safely and asks
   for re-ingestion.

The deterministic refusal wording states that the authoritative policy sources
do not clearly settle the question. The next step comes from source-backed
organizational roles in `data/contacts.json`; no phone number, email address, or
personal name is invented.

**Rationale:** In this domain, false answers can cause users to miss deadlines,
misstate eligibility, or take action on a rule the source never established.
Precision and citation integrity are therefore prioritized over answer coverage.

## 6. Contradiction handling

**Decision:** Return `CONFLICT` before considering `ANSWER` when relevant
provisions are materially incompatible and the authoritative sources provide no
date-appropriate precedence rule.

The detector combines:

- source-verified conflict findings tied to exact clause IDs; and
- conservative deterministic checks for incompatible quantities or polarity
  among sufficiently relevant clauses.

Scoped exceptions, extensions, and different populations should not be treated
as conflicts merely because their numbers differ. Where scope cannot be resolved,
the system does not choose a winner. `CONFLICT` must cite at least two trusted
sources, explain why no single rule controls, and provide escalation guidance.

Confirmed source issues currently include:

- for a change occurring before 1 March 2026, §4.3.2 versus §9.1.4 on a 10-day
  versus 30-day reporting period; amendment ¶5.2 retains the historical period
  but does not choose between those inconsistent base provisions;
- for a change occurring on or after 1 March 2026, amendment ¶¶2.1 and 2.2 align
  both provisions to 14 days, using the change-occurrence date; and
- §4.1.1 versus §10.5.2 on exclusion from eligibility versus an award reduction
  as the effect of a sanction. Amendment ¶4.1 changes the reduction to 15% for a
  post-effective determination, but does not resolve that separate conflict.

## 7. Known-gap handling

**Decision:** Record reviewed gaps outside the authoritative sources and use them
to force a transparent refusal for matching questions. Do not insert missing
rules into the source bundle.

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
check. Any backend, source bundle, timeline, model, or retrieval-setting change
requires calibration and evaluation to be rerun.

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

Claim validation also rejects obvious invented manual clause IDs, amendment
paragraph locators, and numeric values absent from the selected sources. A
validation failure becomes `REFUSE`, not a warning attached to an unsafe answer.

Persisted FAISS and metadata artifacts carry SHA-256 checksums. At load time,
the program also reparses the authoritative source bundle and requires every
indexed citation field—including exact text, source locator, offsets, and line
range—to match that source-derived record. The manifest alone is not treated as
proof of citation truth.

## 10. Answer-construction and provider decision

**Decision:** Deterministic, source-forward answer construction is the default.
It uses selected source text and requires no API key.

Gemini is an optional implementation of the `LLMProvider` interface. It can
rephrase only an already-authorized `ANSWER`; it cannot override the decision
engine. Structured provider output is validated with Pydantic and source-ID
allowlisting. Pure official-clause lookups are rendered verbatim because the
provider intentionally receives only opaque IDs. Any malformed, unsupported,
or invalid provider output is discarded and replaced with the already validated
exact source text. If that fallback cannot satisfy the answer contract, the
pipeline refuses.

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

The parser converts valid English source dates to ISO form rather than
hard-coding one release. Settings bind the base manual, optional amendment, and
policy timeline into one validated source bundle. Reviewed findings, timeline
rules, and escalation metadata must declare compatible reviewed source identities
and may cite only locators present in that bundle. Streamlit cache identity
includes those files and the index manifest so a quarterly update invalidates the
in-memory pipeline.

The generated index and processed chunks are reproducible artifacts and are not
committed. The source bundle, reviewed timeline/findings, escalation descriptions,
evaluation labels, and documentation are committed.

## 13. Observability and tracing decision

**Decision:** LangSmith tracing is optional, uses the standalone SDK rather
than LangChain, and records only a strict allowlist of content-free diagnostic
fields.

The root query run and its retrieval, evidence, decision, and answer-construction
children record timing, state, counts, evidence levels, and clause IDs. They do
not record raw questions, generated answers, policy excerpts, decision reasons,
next steps, or full debug traces. Runtime metadata is omitted and all client
inputs, outputs, and metadata pass through the same allowlist before upload.

`LANGSMITH_TRACING=false` is the safe default. Enabling it requires the optional
pinned SDK and either `LANGSMITH_API_KEY` or the legacy `LANGCHAIN_API_KEY`
fallback. Observability failures must not turn a safe policy answer into an
application failure.

**Trade-off:** Content-redacted traces are less useful for semantic debugging,
but retain operational latency and state-machine visibility without copying
case questions or policy text to another service.

## 14. Key trade-offs

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

## 15. Known failure modes

1. Novel paraphrases or vocabulary outside the authoritative source bundle can
   cause retrieval misses or false refusals.
2. Compound questions may be split imperfectly, causing a false refusal or an
   incomplete source selection.
3. Numeric conflict rules can confuse a scoped exception with a contradiction;
   the detector is deliberately conservative and reviewed findings take priority.
4. A contradiction or gap not yet represented in reviewed metadata can be missed.
5. Line citations change if a source file is reformatted; the source-bundle
   digest forces re-ingestion but cannot preserve old line numbers.
6. Sentence Transformer and reranker behavior depends on downloaded model files,
   hardware, and library versions; it must be evaluated separately from hashing.
7. Gemini behavior and service availability are external variables. Provider
   failure safely reduces coverage to refusal.
8. The parser is tailored to the supplied numbered Markdown structure and does
   not handle scanned PDFs or arbitrary manual layouts.
9. The system has no case record, external statute, or regulatory database. It
   applies only the explicit amendment precedence and transition rules recorded
   in the reviewed timeline; it cannot infer an unstated rule or resolve an
   ambiguity the authoritative sources leave open.
10. Evaluation cases demonstrate selected behavior but cannot prove that every
    possible wording or policy issue is handled.

These limitations are release information, not optional future clean-up. New
failures should be classified, preserved as regression cases, and repaired in
the responsible component.

## 16. Day-2 amendment decision record

### Source-authority audit

The base policy authority is `data/policy-manual.md`. Amendment No. 2026-01,
stored as `data/amendment-2026-01.md`, is a second authority effective 1 March
2026 and amends rather than replaces that manual. The challenge DOCX, the data
pack README, and `READ ME FIRST.md` supply requirements but never evidence for a
policy answer. `.DS_Store` is Finder metadata and is excluded from parsing,
retrieval, and citations.

### What changed

- The parser, index manifest, citations, and source lookups now retain both
  manual-clause and amendment-paragraph provenance.
- `data/policy_timeline.json` records source-verified amendment operations and
  `src/temporal.py` resolves them before ordinary retrieval when a question is
  amendment-sensitive.
- Paragraphs 1, 3, and 4 use the determination date under amendment ¶5.1;
  paragraph 2 uses the date the change of circumstances occurred under ¶5.2.
  A period spanning 1 March uses figures in force on each day and is apportioned
  under ¶5.3 and §7.4.3.
- A missing legally controlling date is a refusal/clarification condition, not
  permission to use today's value. Date-sensitive cases must be added to the
  evaluation set and rerun with every timeline update.

### What did not change

The three-state `ANSWER` / `CONFLICT` / `REFUSE` contract, source-first answer
construction, citation validation, policy-gap handling, and prohibition on
inventing facts or escalation contacts remain unchanged. The amendment is not
treated as a reason to silently repair base-manual ambiguity: where its transition
does not settle a historical conflict, the result remains `CONFLICT`.

### Hindsight

Had the amendment been known on Day 1, policy sources, effective dates,
supersession rules, and controlling-fact requirements would have been modeled as
first-class ingestion data from the start. The original component boundaries made
the correction localized, but baseline evaluation claims and demos still needed
to be revisited; future policy work should establish a timeline test matrix before
publishing aggregate results.
