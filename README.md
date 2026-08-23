# The Grounded Answer

The Grounded Answer is a policy-grounded decision-support assistant for the
Calder County Household Support Program source bundle. It retrieves exact policy
provisions, resolves a reviewed amendment against the date in the question, and
emits one of three explicit decisions: `ANSWER`, `CONFLICT`, or `REFUSE`.

This is not a generic chatbot and it is not an autonomous eligibility
decision-maker. Retrieval relevance alone never authorizes an answer. A
transparent refusal is the intended result when the authoritative source bundle
is silent, incomplete, ambiguous, or dependent on missing case facts.

## Source authority and provenance

The runtime uses a reviewed source bundle. It does not fetch a replacement
manual, silently repair source wording, or use general benefits knowledge as
policy.

| Supplied file | Role in this repository | May support an answer citation? |
| --- | --- | --- |
| `Data pack/policy-manual.md` → `data/policy-manual.md` | Base Calder County Household Support Program Policy Manual, consolidated as at 31 December 2025 | Yes — cite the official `§part.section.clause` identifier |
| `Amendment No. 2026-01.md` → `data/amendment-2026-01.md` | Authority issued 12 February 2026 and effective 1 March 2026; it amends, rather than replaces, the base manual | Yes — cite `Amendment No. 2026-01 ¶paragraph` and the affected manual clause where useful |
| `1 - The Grounded Answer.docx`, `Data pack/README.md`, and `READ ME FIRST.md` | Challenge and delivery requirements, including the Day-2 change | No — these are not policy evidence |
| Attached `pasted-text.txt` | Implementation brief and desired source-first RAG pipeline | No — it guided architecture and verification, not policy answers |
| `.DS_Store` | Finder metadata | No — it is deliberately ignored |

The base manual identifies its persons, places, figures, and case references as
fictitious. The amendment becomes part of the authoritative bundle on its
effective date. Before then, its text is retained as provenance but does not
silently change the historical rule.

Ingestion preserves the official part, section, and clause hierarchy; amendment
paragraph identity; exact source text; normalized retrieval text; UTF-8 byte
offsets; source line numbers; cross-references; source order; and a source-bundle
SHA-256 digest. Because the supplied sources are Markdown rather than paginated
documents, page numbers are unavailable. Citations use either official clause
IDs or amendment paragraph locators, with source-line ranges and exact excerpts.
Repository attributes force source files to LF on every operating system so
digests, byte offsets, and deterministic opaque IDs remain stable.

Human-reviewed candidate gaps and contradictions are recorded separately in
`data/policy_findings.json`. The reviewed amendment operations and their date
bases are recorded in `data/policy_timeline.json`. These controls guide
conservative resolution without changing source truth.

## Decision contract

| Decision | When it is used | What is returned |
| --- | --- | --- |
| `ANSWER` | Direct, complete, internally consistent evidence clears the configured support boundary | Plain answer, trusted clause citations, exact excerpts, and evidence level |
| `CONFLICT` | Materially incompatible relevant provisions have no source-backed precedence rule | Both sides, both citations, why no single rule can be chosen, and an escalation step |
| `REFUSE` | Evidence is absent, related-only, partial, below threshold, dependent on missing case facts (including a legally controlling date), affected by a known gap, or cannot produce any citation-valid fallback | Explicit “I don't know based on the authoritative policy sources,” the reason, and a non-fabricated next step |

`ANSWER` requires at least one trusted citation. `CONFLICT` requires at least
two. An LLM cannot change the decision already made by the deterministic
decision engine, and it can select only opaque source IDs supplied to it.

## Architecture

```text
base manual + effective amendment
              │
              ▼
clause / amendment parser ──► exact chunks + source-bundle digest
              │
              ▼
hybrid search index ◄──── dense + lexical representations
              │
question + optional case date
              │
              ▼
query normalization + date / fact extraction
              │
              ▼
hybrid clause retrieval + optional local reranker
              │
              ▼
source-verified temporal policy resolution
              │
              ▼
evidence + contradiction / gap checks
              │
              ▼
       evidence sufficient?
          ├─ yes ─► ANSWER or CONFLICT
          └─ no  ─► REFUSE + who to ask
                         │
                         ▼
deterministic answer builder or optional Gemini phrasing
                         │
                         ▼
claim, policy-version, and citation validation
                         │
                         ▼
                  CLI / Streamlit response
```

The default path uses stable local hashing embeddings, lexical retrieval,
deterministic answer construction, and no credentials. Sentence Transformers,
CrossEncoder reranking, and Gemini phrasing are opt-in runtime modes.

## Prerequisites

- CPython 3.11 or newer
- Git
- Internet access for the initial dependency installation
- Additional network access only when downloading optional Hugging Face models
  or calling Gemini

Run all commands from the repository root. The generated index records its
embedding backend and source-bundle digest; asking with a different backend or
changed authoritative source fails safely until the bundle is re-ingested.

## Clean-clone setup

Clone the repository to the directory name used by the commands below:

```powershell
git clone https://github.com/KarreJohnHyde/Brite-Systems.git grounded-answer
cd grounded-answer
```

### Windows PowerShell

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

If local policy blocks script activation, allow it only for the current shell
and rerun the activation command:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

### macOS or Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

The checked-in `.env.example` already selects the safe deterministic defaults.
Do not add credentials unless you intentionally enable an external provider.

## Ingest the corpus

Inspect the source structure without creating an index:

```powershell
python main.py corpus-report
```

Build the default deterministic hashing index:

```powershell
python main.py ingest --embedding-backend hashing
```

Ingestion writes generated chunks and diagnostics under `data/processed/` and
the FAISS index under `data/indexes/`. Both directories are ignored because
they are reproducible from the checked-in source bundle.

To inspect or ingest a different manual without overwriting the checked-in
sources, pass its path explicitly. An explicit manual intentionally has no
default amendment: pair it with its reviewed amendment when one applies.

```powershell
python main.py corpus-report --corpus "C:\path\to\policy-manual.md"
python main.py ingest --corpus "C:\path\to\policy-manual.md" --embedding-backend hashing
python main.py ingest --corpus "C:\path\to\policy-manual.md" `
  --amendment "C:\path\to\amendment.md" --embedding-backend hashing
```

For a continuing alternate-corpus workflow, set `CORPUS_PATH` to that same file
and, where applicable, `AMENDMENT_PATH` and `POLICY_TIMELINE_PATH` in `.env` so
every command validates against the indexed source bundle. Create and
human-review a corresponding source-derived evaluation set before using the
checked-in evaluator or calibrator with another bundle. The parser expects the
actual manual's `Part`, section, and numbered-clause structure and fails with a
clear error when that structure is not present.

### Quarterly manual update

For each newly issued amendment or consolidated manual:

1. Preserve the reviewed base source. Do not overwrite it merely because an
   amendment arrives; set or update `CORPUS_PATH` only for a replacement
   consolidated manual.
2. Add or repoint `AMENDMENT_PATH` to the reviewed amendment, then update
   `POLICY_TIMELINE_PATH` with source-verified operations, affected clauses,
   effective date, and the legally controlling date basis.
3. Update and human-review `data/policy_findings.json` and `data/contacts.json`
   so their reviewed source identity and cited provisions match the bundle.
4. Run `corpus-report`, then re-ingest with the selected embedding backend.
5. Run unit, core, adversarial, and date-sensitive evaluation cases. Include
   before/effective/after dates and any transitional rule before treating the
   revised bundle as release-ready.
6. Restart long-running CLI workers. Streamlit automatically uses a new cached
   pipeline key when source, timeline, manifest, findings, or contact metadata
   changes.

The runtime refuses stale companion metadata, a changed source bundle with an
old index, unknown reviewed references, an invalid amendment timeline, or an
embedding/index mismatch.

## CLI usage

Ask one question using the safe default:

```powershell
python main.py ask "What is the household resource limit?"
```

Inspect the complete decision trace or validated JSON:

```powershell
python main.py ask "What is the household resource limit?" --debug
python main.py ask "What is the household resource limit?" --json
```

Supply the legally controlling date as structured case context when it is not
written in the question:

```powershell
python main.py ask "How many days do I have to report an income change?" --change-date 2026-02-15
python main.py ask "How many days do I have to report an income change?" --change-date 2026-04-15
python main.py ask "What earnings disregard applies?" --determination-date 2026-04-15
```

Structured dates use ISO `YYYY-MM-DD`. If a structured date conflicts with a
date written in the question, the request fails safely instead of choosing one.

Look up exact source text by official clause ID, section ID, amendment paragraph,
or opaque chunk ID:

```powershell
python main.py source 2.4.1
python main.py source 4.3
python main.py source "Amendment No. 2026-01 ¶1.1"
python main.py source 2.4.1 --json
```

`show-clause` remains an alias for `source`:

```powershell
python main.py show-clause 2.4.1
```

Start independent-question interactive mode:

```powershell
python main.py interactive --embedding-backend hashing
```

The interactive and Streamlit histories are display conveniences. Each question
is evaluated independently; prior messages do not become policy evidence.
Streamlit provides the same optional change-date or determination-date context
in its sidebar.

### Date-sensitive examples

The amendment does not make an undated question answerable. Include the
determination date for earnings, thresholds, and sanctions; include the date the
change occurred for a reporting deadline. For a period spanning the effective
date, give the period bounds.

```powershell
python main.py ask "For a determination on 28 February 2026, what monthly earnings disregard applies?"
python main.py ask "For a determination on 1 March 2026, what monthly earnings disregard applies?"
python main.py ask "How many days do I have to report an income change?" --change-date 2026-02-15
python main.py ask "How many days do I have to report an income change?" --change-date 2026-04-15
python main.py ask "How should a claim from 20 February 2026 through 10 March 2026 be treated?"
```

If the supplied facts do not identify the controlling date, the safe result is a
visible `REFUSE` that asks for the date and directs the user to the appropriate
reviewer rather than selecting a historical or current rule by guesswork.

## Evaluation, calibration, and tests

Run the source-derived evaluation set. The command returns a non-zero process
status when one or more cases fail:

```powershell
python main.py evaluate --embedding-backend hashing
python main.py evaluate --embedding-backend hashing --quiet
python main.py evaluate --embedding-backend hashing `
  --questions evaluation/adversarial_questions.json `
  --output-dir evaluation/results/adversarial --quiet
python main.py evaluate --embedding-backend hashing `
  --questions evaluation/temporal_questions.json `
  --output-dir evaluation/results/temporal --quiet
```

Sweep evidence thresholds against the labeled evaluation set:

```powershell
python main.py calibrate --embedding-backend hashing
```

Calibration is evidence for a threshold choice, not permission to hide
failures. Review both false answers and false refusals, then record any adopted
threshold change in `DECISIONS.md` and `.env`.

Run the automated tests:

```powershell
python -m pytest -q
```

The generated evaluation report is the authoritative record of measured
results. Do not infer release readiness solely from an aggregate score; inspect
every false answer, missed conflict, bad citation, and false refusal.

The Day-2 source-bundle change invalidates any earlier aggregate claim as a
release statement. Regenerate the core, adversarial, date-sensitive, calibration,
and automated test reports after every policy/timeline change and report the
resulting passes and failures without relabeling cases to improve a score. The
dedicated [`temporal_questions.json`](evaluation/temporal_questions.json) suite
exercises historical and post-effective rules, a spanning-period rule,
missing-date refusals, and amendment-paragraph citations. These remain bounded
measurements, not generalization guarantees; see the generated reports under
[`evaluation/results`](evaluation/results) for current case-level evidence.

Latest local verification for the checked-in source bundle:

| Check | Result |
| --- | --- |
| Core source-derived suite | 18 / 18 strict cases passed |
| Adversarial suite | 15 / 15 strict cases passed |
| Date-sensitive amendment suite | 16 / 16 strict cases passed, including amendment-locator assertions and sentence-separated reporting intent |
| Offline calibration | Recommended `REFUSAL_THRESHOLD=0.58`, `DIRECT_COVERAGE_THRESHOLD=0.34`; zero false answers and zero missed conflicts on the development set |
| Automated regression suite | 145 tests passed |

These are local development measurements, not a claim of legal correctness or
generalization beyond the supplied sources and the recorded cases.

## Short judging demo

```powershell
python main.py ingest --embedding-backend hashing
python main.py ask "What is the household resource limit?"
python main.py ask "How is the needs figure calculated for a full-time student?"
python main.py ask "How many days do I have to report an income change?" --change-date 2026-02-15
python main.py ask "How many days do I have to report an income change?" --change-date 2026-04-15
python main.py ask "For a change on 15 February 2026, do the reporting duty and overpayment protection agree?"
python main.py source 4.3.2
python main.py source "Amendment No. 2026-01 ¶2.1"
python main.py evaluate --embedding-backend hashing --quiet
python -m pytest -q
```

These questions exercise supported, policy-gap/refusal, historical reporting,
and post-effective amendment paths. Example output shape is:

```text
STATUS: ANSWER | CONFLICT | REFUSE

plain-language result

WHY
decision reason

NEXT STEP
source-backed escalation guidance, when needed

SOURCES
official manual clause and/or amendment paragraph, source lines, and exact excerpt

Evidence: HIGH | MEDIUM | LOW
```

## Optional local semantic embeddings and reranking

Install the optional local-model dependencies first:

```powershell
python -m pip install -r requirements-ml.txt
```

Edit `.env`:

```dotenv
EMBEDDING_BACKEND=sentence-transformers
ENABLE_RERANKING=true
```

Then rebuild and query with the matching backend:

```powershell
python main.py ingest --embedding-backend sentence-transformers
python main.py ask "What is the household resource limit?" --embedding-backend sentence-transformers
python main.py evaluate --embedding-backend sentence-transformers
```

The first run downloads `sentence-transformers/all-MiniLM-L6-v2` and, when
reranking is enabled, `cross-encoder/ms-marco-MiniLM-L-6-v2`. These models run
locally after download. If the reranker cannot load, retrieval continues without
it; reranking is never required for the safe baseline. Set
`REQUIRE_RERANKER=true` for candidate evaluation so load or prediction failures
fail closed instead of silently testing a different profile.

## Reproducible local model training

The supplied labels can train the bi-encoder and cross-encoder only. Stable
hashing, BM25, FAISS `IndexFlatIP`, and the safety rules have no learned weights.
Gemini is a hosted phrasing API and is tested through its provider contract; it
is not fine-tuned by this repository. The query files do not contain
human-authored target answers, so generation fine-tuning would fabricate labels.

Create the ignored training environment on a drive with enough space and run:

```powershell
python -m venv .training-venv --system-site-packages
.\.training-venv\Scripts\python.exe -m pip install -r requirements-training.txt
.\.training-venv\Scripts\python.exe -m training.train_models `
  --run-name county-hsp-local-v1-s42 `
  --seeds 42
```

The command uses the checked-in source-derived labels in rotating folds. Every
query is held out once, and no expected-evidence clause or protected local
context crosses from the test fold into training negatives. It mines guarded hard
negatives, trains both models on CPU, hashes each immutable artifact, builds a
separate candidate index under `data/trained-indexes/`, and runs strict
end-to-end sets with reranking required. Model weights and candidate indexes are
ignored; compact JSON/Markdown reports are retained.

Any earlier model-training report is an archived experiment, not evidence that a
candidate remains safe for the revised source bundle. The sample is small, only
one seed has been run, and there is no blind staff-query set, so a trained model
remains opt-in until it is re-evaluated against the amendment-aware cases. See
the [`model-training report`](evaluation/results/model-training/county-hsp-local-v1-s42/report.md)
for its historical details.

## Optional Gemini phrasing

The deterministic decision, evidence, and citation checks remain authoritative.
Gemini is used only to phrase an already-supported answer and cannot convert a
trusted `REFUSE` or `CONFLICT` decision into `ANSWER`.

Install the optional provider dependency:

```powershell
python -m pip install -r requirements-llm.txt
```

Then set these values in the untracked `.env` file:

```dotenv
LLM_PROVIDER=gemini
GEMINI_MODEL=gemini-3.6-flash
GEMINI_THINKING_LEVEL=minimal
GEMINI_API_KEY=
```

Set `GEMINI_API_KEY` to your own credential in the untracked file, then run:

```powershell
python main.py ask "What is the household resource limit?" --provider gemini
```

Gemini 3 requests use minimal thinking for this short structured phrasing task.
Provider errors, malformed output, unsupported claims, decision changes, and
invalid source IDs are discarded. The assistant then shows the already
validated exact policy text and trusted citation; rejected model text is never
rendered. If that fallback also fails validation, the pipeline returns
`REFUSE`. A credential-redacted live supported/refusal check is recorded in the
[`Gemini provider smoke report`](evaluation/results/model-training/county-hsp-local-v1-s42/provider-smoke.md).

## Optional LangSmith tracing

The custom pipeline can emit privacy-preserving LangSmith spans without
installing LangChain. Install the pinned optional SDK:

```powershell
python -m pip install -r requirements-tracing.txt
```

Then configure the untracked `.env` file:

```dotenv
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=grounded-answer
```

`LANGCHAIN_API_KEY` remains accepted as a legacy fallback, but new setups
should use the official `LANGSMITH_API_KEY` name. Traces contain timing and
state diagnostics for retrieval, evidence assessment, decision, and validated
answer construction. Raw questions, generated answers, reasons, next steps,
policy excerpts, and full debug traces are excluded by a strict allowlist.

## Streamlit interface

After ingestion:

```powershell
python -m pip install -r requirements-ui.txt
python -m streamlit run app.py
```

The sidebar selects the embedding backend and answer provider. Its backend must
match the index built by `ingest`. The page displays the active base manual and
amendment metadata. Its cached pipeline key includes the source bundle, policy
timeline, index manifest, reviewed findings, and contact metadata, so a quarterly
change cannot keep serving an old in-memory pipeline. Restart Streamlit after
editing unrelated runtime-only `.env` settings. The CLI is the canonical
interface for evaluation and reproducibility.

## Privacy and security

- Default deterministic mode keeps questions and excerpts local and makes no
  model API call.
- Gemini mode sends the question and only the selected policy excerpts with
  opaque source IDs to the configured Gemini API. Do not use it for sensitive
  case data without an approved privacy review.
- Policy excerpts are treated as untrusted data, not executable instructions.
- The model may select only source IDs already supplied by the program. Trusted
  clause metadata is mapped back in code and invented IDs are rejected.
- Claim validation rejects obvious invented clause IDs and unsupported numeric
  values before rendering.
- `.env` and Streamlit secrets are ignored. Never commit API keys.
- Debug traces contain the question, retrieved excerpts, scores, and decision
  rationale. Treat exported traces as potentially sensitive.
- LangSmith tracing is content-redacted by design and records only allowlisted
  diagnostics such as counts, decisions, evidence levels, and clause IDs.
- Index loading verifies schema, chunk count, dimensions, artifact checksums,
  embedding backend, model identity where applicable, the current source-bundle
  SHA-256, every citation field against a fresh parse of its source, and the
  reviewed source/locator references in findings, timeline, and escalation
  metadata.

## Known source conflicts and gaps

The base manual intentionally contains issues that must remain visible. The
amendment changes their treatment only where it expressly says so:

- **Reporting duty, before 1 March 2026:** §4.3.2 specifically requires a change
  to be reported within 10 calendar days, measured from occurrence or awareness,
  whichever is later. Amendment ¶5.2 preserves that period for a pre-effective
  change. A direct reporting-duty question therefore returns `ANSWER` with 10
  days.
- **Historical overpayment wording conflict:** §9.1.4 separately describes 30
  calendar days as the period required under §4.3 for overpayment protection.
  That does not replace the specific duty in §4.3.2. A question about
  overpayment protection or whether the provisions agree returns `CONFLICT` and
  shows both clauses.
- **Reporting deadline, on or after 1 March 2026:** amendment ¶¶2.1 and 2.2
  substitutes 14 calendar days in both provisions. The event date—not the later
  determination date—controls under ¶5.2.
- **Sanction-effect conflict:** §4.1.1 describes a person with an unexpired
  §10.5 sanction as excluded from eligibility, while §10.5.2 defines a sanction
  as an award reduction for 4 or 8 weeks. Amendment ¶4.1 changes that reduction
  from 20% to 15% for determinations on or after 1 March under ¶5.1, but does not
  resolve the incompatible sanction effects.
- **Failure-to-report exception:** amendment ¶4.2 inserts §10.5.3A. For a
  post-effective determination, a sanction must not be imposed for a failure to
  report when the change would have increased the award. This is not a general
  answer to every failure-to-report question; the required facts still matter.
- **Full-time-student needs gap:** §7.1.3 sends the reader to §5.4, but §5.4
  concerns care allowance and supplies no student calculation.
- **Education-absence gap:** §§3.2.3 and 5.2.3 say full-time education is handled
  separately, but no separate rule appears.
- **Unlisted-resource gap:** the manual does not classify or value asset types
  such as cryptocurrency or a second vehicle.
- **Household-calculation gaps:** the needs table does not resolve some
  multi-adult compositions, and the housing-assistance adjustment refers to
  cost components the table does not identify.
- **No-fixed-address gap:** the residence rules permit no fixed address while
  the application rule requires an address, without saying what to enter.

The complete reviewed list, scopes, triggers, and clause IDs is in
`data/policy_findings.json`. The assistant surfaces or refuses on these issues;
it does not choose which provision should prevail.

## Known limitations

- The parser supports the supplied structured Markdown corpus, not arbitrary
  PDFs, scans, OCR output, or unrelated policy formats.
- Markdown has no authoritative pages, so line ranges and exact excerpts are
  used for verification.
- Retrieval and evidence scoring are English-language heuristics and can still
  miss paraphrases, compound questions, exceptions, or scope distinctions.
- Thresholds are source-bundle- and backend-specific. Re-run calibration and
  evaluation after changing a backend, model, source, timeline, or retrieval
  setting.
- Curated findings cover reviewed issues; they do not prove that every gap or
  contradiction has been discovered.
- The default deterministic answer is intentionally source-forward rather than
  highly conversational.
- Gemini availability, latency, pricing, and output can change independently of
  this repository. The safe local path does not depend on Gemini.
- The system has no case database and cannot explain an individual case outcome
  or make an eligibility determination from missing facts.
- The date resolver currently implements only the source-verified amendment
  operations recorded in `data/policy_timeline.json`. Every future amendment
  requires a reviewed timeline mapping and date-sensitive regression cases.
- A missing legally controlling date is intentionally a refusal condition, even
  when the words of a question otherwise resemble a known policy topic.

## Project structure

```text
grounded-answer/
├── main.py                     CLI and output formatting
├── app.py                      optional Streamlit interface
├── config/settings.py          validated environment-backed settings
├── data/
│   ├── policy-manual.md        supplied base policy source
│   ├── amendment-2026-01.md    effective policy amendment
│   ├── policy_timeline.json    source-verified amendment/date rules
│   ├── policy_findings.json    reviewed conflict/gap metadata
│   └── contacts.json           source-backed escalation descriptions
├── src/
│   ├── parser.py               exact-source manual and amendment ingestion
│   ├── temporal.py             date-aware amendment applicability resolver
│   ├── embeddings.py           hashing and Sentence Transformer backends
│   ├── lexical.py              lexical retrieval
│   ├── vector_store.py         persisted FAISS index and integrity checks
│   ├── retriever.py            hybrid retrieval, neighbors, optional reranking
│   ├── query_analysis.py        exact-reference and ambiguity guards
│   ├── evidence.py             support classification
│   ├── contradiction.py        curated and deterministic conflict checks
│   ├── decision_engine.py      ANSWER / CONFLICT / REFUSE state machine
│   ├── generator.py            deterministic answer builder
│   ├── citations.py            citation and claim validation
│   ├── refusal.py              refusal and escalation text
│   ├── observability.py        content-redacted LangSmith tracing
│   ├── pipeline.py             composition root and fail-safe orchestration
│   └── llm/                    optional provider interface and Gemini adapter
├── evaluation/                 core/adversarial labels, runner, calibration, results
├── training/                   guarded data building, metrics, and local trainers
├── tests/                      automated tests
├── requirements.txt            pinned Python dependencies
├── requirements-ml.txt         optional local models and reranker
├── requirements-training.txt   optional local CPU training stack
├── requirements-llm.txt        optional Gemini provider
├── requirements-tracing.txt    optional LangSmith observability
├── requirements-ui.txt         optional Streamlit interface
├── .env.example                safe runtime defaults
├── DECISIONS.md                architecture and safety decisions
└── AI-USAGE.md                 AI assistance disclosure
```

See `DECISIONS.md` for the refusal boundary, calibration policy, citation trust
model, trade-offs, and known failure modes.
