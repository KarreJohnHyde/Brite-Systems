# The Grounded Answer

The Grounded Answer is a policy-grounded decision-support assistant for the
Calder County Household Support Program manual. It retrieves exact policy
clauses, assesses whether those clauses actually settle a question, and emits
one of three explicit decisions: `ANSWER`, `CONFLICT`, or `REFUSE`.

This is not a generic chatbot and it is not an autonomous eligibility
decision-maker. Retrieval relevance alone never authorizes an answer. A
transparent refusal is the intended result when the manual is silent,
incomplete, ambiguous, or dependent on missing case facts.

## Corpus and provenance

The supplied challenge corpus is checked in at
`data/policy-manual.md`. Its own header identifies it as the **Calder County
Household Support Program Policy Manual**, consolidated as at **31 December
2025**, and states that its persons, places, figures, and case references are
fictitious. The repository does not fetch a replacement manual or silently
repair its content.

Ingestion preserves the official part, section, and clause hierarchy; exact
source text; normalized retrieval text; UTF-8 byte offsets; source line
numbers; cross-references; version metadata; source order; and a SHA-256 digest.
Because the supplied source is Markdown rather than a paginated document, page
numbers are unavailable and citations use official clause IDs plus source-line
ranges. Repository attributes force source files to LF on every operating
system so the digest, byte offsets, and deterministic opaque IDs remain stable.

Human-reviewed candidate gaps and contradictions are recorded separately in
`data/policy_findings.json`. They guide conservative retrieval and decision
checks without changing source truth.

## Decision contract

| Decision | When it is used | What is returned |
| --- | --- | --- |
| `ANSWER` | Direct, complete, internally consistent evidence clears the configured support boundary | Plain answer, trusted clause citations, exact excerpts, and evidence level |
| `CONFLICT` | Materially incompatible relevant provisions have no source-backed precedence rule | Both sides, both citations, why no single rule can be chosen, and an escalation step |
| `REFUSE` | Evidence is absent, related-only, partial, below threshold, dependent on missing case facts, affected by a known gap, or cannot produce any citation-valid fallback | Explicit “I don't know based on the current policy manual,” the reason, and a non-fabricated next step |

`ANSWER` requires at least one trusted citation. `CONFLICT` requires at least
two. An LLM cannot change the decision already made by the deterministic
decision engine, and it can select only opaque source IDs supplied to it.

## Architecture

```text
supplied Markdown corpus
        │
        ▼
clause-aware parser ──► exact chunks + corpus report + SHA-256
        │
        ▼
dense index + lexical BM25
        │
question ──► hybrid retrieval ──► optional local reranker
                                      │
                                      ▼
                              evidence assessment
                                      │
                                      ▼
                         contradiction / gap checks
                                      │
                                      ▼
                     ANSWER │ CONFLICT │ REFUSE
                                      │
                                      ▼
                    deterministic answer builder
                       or optional Gemini phrasing
                                      │
                                      ▼
                         citation and claim validation
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
embedding backend and source digest; asking with a different backend or a
changed corpus fails safely until the corpus is re-ingested.

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
they are reproducible from the checked-in corpus.

To inspect or ingest a different supplied Markdown file without overwriting the
checked-in manual, pass its path explicitly:

```powershell
python main.py corpus-report --corpus "C:\path\to\policy-manual.md"
python main.py ingest --corpus "C:\path\to\policy-manual.md" --embedding-backend hashing
```

For a continuing alternate-corpus workflow, set `CORPUS_PATH` to that same file
in `.env` so every command validates against the indexed source. Create and
human-review a corresponding source-derived evaluation set before using the
checked-in evaluator or calibrator with another corpus. The parser expects the
actual manual's `Part`, section, and numbered-clause structure and fails with a
clear error when that structure is not present.

### Quarterly manual update

For each new consolidated manual:

1. Replace or repoint `CORPUS_PATH` to the reviewed Markdown source.
2. Update and human-review `data/policy_findings.json` and `data/contacts.json`
   so their `document_id`, `consolidated_as_of`, and cited clauses match it.
3. Run `corpus-report`, then re-ingest with the selected embedding backend.
4. Run the unit, core evaluation, and adversarial evaluation commands below.
5. Restart long-running CLI workers. Streamlit automatically uses a new cached
   pipeline key when the corpus, manifest, findings, or contact metadata changes.

The runtime refuses stale companion metadata, a changed corpus with an old
index, unknown reviewed clause references, or an embedding/index mismatch.

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

Look up exact source text by official clause ID, section ID, or opaque chunk ID:

```powershell
python main.py source 2.4.1
python main.py source 4.3
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

## Evaluation, calibration, and tests

Run the source-derived evaluation set. The command returns a non-zero process
status when one or more cases fail:

```powershell
python main.py evaluate --embedding-backend hashing
python main.py evaluate --embedding-backend hashing --quiet
python main.py evaluate --embedding-backend hashing `
  --questions evaluation/adversarial_questions.json `
  --output-dir evaluation/results/adversarial --quiet
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

The checked-in deterministic baseline was executed on 23 August 2026. It passed
18 / 18 strict source-derived cases with 100% decision accuracy, retrieval
recall, required-citation recall, and unsupported-claim safety on this
development set. The calibration sweep evaluated 28 threshold combinations and
retained `REFUSAL_THRESHOLD=0.58` and `DIRECT_COVERAGE_THRESHOLD=0.34`, with
zero false answers and zero missed conflicts for the recommended candidate.
The separate adversarial set passed 15 / 15 cases covering ambiguity, deictic
follow-ups, exact and forged clause references, colloquial wording, typos,
service-access gaps, out-of-scope questions, nonsense input, and mixed
supported/unsupported asks. The automated suite passed 128 tests. These remain
bounded measurements, not generalization guarantees; see
[`evaluation/results/evaluation.md`](evaluation/results/evaluation.md) and
[`evaluation/results/adversarial/evaluation.md`](evaluation/results/adversarial/evaluation.md) and
[`evaluation/results/calibration.md`](evaluation/results/calibration.md) for the
complete case-level evidence.

## Short judging demo

```powershell
python main.py ingest --embedding-backend hashing
python main.py ask "What is the household resource limit?"
python main.py ask "How is the needs figure calculated for a full-time student?"
python main.py ask "How many days does a recipient have to report a change of circumstances?"
python main.py source 4.3.2
python main.py source 9.1.4
python main.py evaluate --embedding-backend hashing --quiet
python -m pytest -q
```

These questions exercise the intended supported, policy-gap, and contradiction
paths. Example output shape is:

```text
STATUS: ANSWER | CONFLICT | REFUSE

plain-language result

WHY
decision reason

NEXT STEP
source-backed escalation guidance, when needed

SOURCES
official clause, source lines, and exact excerpt

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

The command uses all 33 canonical queries in two rotating folds. Every query is
held out once, and no expected-evidence clause or protected local context crosses
from the test fold into training negatives. It mines guarded hard negatives,
trains both models on CPU, hashes each immutable artifact, builds a separate
candidate index under `data/trained-indexes/`, and runs both strict end-to-end
sets with reranking required. Model weights and candidate indexes are ignored;
the compact JSON/Markdown evaluation reports are retained.

The executed 23 August 2026 run found that training did not improve held-out
reranked Recall@6 (`0.646` for both pretrained and trained), while pairwise
reranker ROC AUC decreased from `0.653` to `0.641`. Some secondary metrics
improved slightly, and the full candidate still passed 18 / 18 core plus 15 / 15
adversarial cases. Because the sample is small, only one seed was run, and no
blind staff-query set exists, the trained model remains opt-in and the pretrained
semantic profile remains recommended. See the complete
[`model-training report`](evaluation/results/model-training/county-hsp-local-v1-s42/report.md).

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
`REFUSE`.

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
match the index built by `ingest`. The page displays the active consolidated
manual version. Its cached pipeline key includes the corpus, index manifest,
reviewed findings, and contact metadata, so a quarterly change cannot keep
serving an old in-memory pipeline. Restart Streamlit after editing unrelated
runtime-only `.env` settings. The CLI is the canonical interface for evaluation
and reproducibility.

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
  embedding backend, model identity where applicable, the current corpus
  SHA-256, every citation field against a fresh parse of the source, and the
  version/clause references in reviewed findings and escalation metadata.

## Known corpus conflicts and gaps

The source intentionally contains issues that must remain visible:

- **Reporting deadline conflict:** §4.3.2 says 10 calendar days, while §9.1.4
  describes 30 calendar days as required under §4.3.
- **Sanction-effect conflict:** §4.1.1 describes a person with an unexpired
  §10.5 sanction as excluded from eligibility, while §10.5.2 defines a sanction
  as a 20% award reduction for 4 or 8 weeks.
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
- Thresholds are corpus- and backend-specific. Re-run calibration and evaluation
  after changing a backend, model, corpus, or retrieval setting.
- Curated findings cover reviewed issues; they do not prove that every gap or
  contradiction has been discovered.
- The default deterministic answer is intentionally source-forward rather than
  highly conversational.
- Gemini availability, latency, pricing, and output can change independently of
  this repository. The safe local path does not depend on Gemini.
- The system has no case database and cannot explain an individual case outcome
  or make an eligibility determination from missing facts.
- Version metadata is preserved, but multi-version policy selection and policy
  diffs are not implemented.

## Project structure

```text
grounded-answer/
├── main.py                     CLI and output formatting
├── app.py                      optional Streamlit interface
├── config/settings.py          validated environment-backed settings
├── data/
│   ├── policy-manual.md        supplied source corpus
│   ├── policy_findings.json    reviewed conflict/gap metadata
│   └── contacts.json           source-backed escalation descriptions
├── src/
│   ├── parser.py               exact-source clause ingestion
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
