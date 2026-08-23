# AI Usage Disclosure

AI-assisted development was used extensively on The Grounded Answer. This file
describes that assistance and separates machine-generated implementation work
from decisions that require accountable human judgment.

## Tools used

- **Google Antigravity coding agent** was used for the initial project scaffold,
  parser, retrieval prototype, evidence logic, CLI, and Streamlit prototype.
- **OpenAI Codex** was used for repository and corpus inspection, architecture
  review, implementation and refactoring assistance, debugging, test and
  evaluation-case suggestions, prompt development, security review, and
  documentation drafting.

Git history retains the staged implementation work. It was not rewritten to
simulate a development process.

## How AI assisted

### Architecture brainstorming

AI helped translate the challenge into explicit components for source parsing,
temporal applicability, retrieval, evidence assessment, conflict detection,
decision logic, answer construction, provider access, citation validation, and
presentation. It also suggested the three-state `ANSWER` / `CONFLICT` /
`REFUSE` contract and the source-first execution order.

### Code generation and refactoring

AI drafted and revised Python modules, Pydantic schemas, configuration loading,
the CLI, the optional Streamlit interface, deterministic retrieval/generation,
the Gemini, OpenAI, Anthropic/Claude, and Groq-hosted Llama phrasing adapters,
OpenAI and Gemini embedding adapters, session-only credential controls, and
citation safeguards. It also assisted with the amendment parser, source-bundle
integrity checks, a source-verified policy timeline, and date-sensitive
resolution after hybrid retrieval. Generated code was inspected in the
repository rather than accepted solely from prose output. Codex also added
direct LangSmith instrumentation with a strict diagnostic allowlist; raw
questions, answers, policy text, reasons, and next steps are not included in
remote trace payloads.

### Corpus analysis and test suggestions

AI searched the supplied base manual and amendment for clause structure,
cross-references, numeric differences, apparent gaps, conflicts, amendment
operations, and transition wording. It proposed date-sensitive evaluation and
unit-test cases grounded in those sources. Reviewed findings are stored in
`data/policy_findings.json`, and the amendment mapping is in
`data/policy_timeline.json`; neither file alters source text.

### Debugging and verification

AI ran local commands, read tracebacks and evaluation output, identified failure
categories, and proposed repairs in the responsible pipeline stages. Examples
include clean-clone checks, dependency/runtime checks, retrieval misses, refusal
boundary errors, missed conflicts, citation-contract failures, stale UI or
provider integrations, session-key fallback behavior, public Streamlit protocol
checks, and historical/effective-date regression cases.

AI also implemented and executed the local retrieval-model training harness. It
helped design the clause-disjoint folds, guarded hard-negative rules, CPU
hyperparameters, artifact hashing, and model-level metrics. The resulting
candidate was not promoted merely because its in-sample and end-to-end regression
checks passed; the held-out comparison and data limitations remain recorded in
the model-training report for human release review.

### Documentation drafting

AI drafted the clean-clone instructions, architecture explanation, ADRs,
privacy/security notes, known limitations, command examples, the Day-2 amendment
record, dependency profiles, the complete evaluation-question catalog, and this
disclosure. Documentation claims still need to agree with executed commands and
recorded evaluation artifacts before release.

### Prompt development

AI helped draft the shared optional-provider prompt that limits each model to
supplied policy excerpts, treats source text as untrusted data, requires
structured output, and restricts source selection to opaque IDs supplied by the
program.

## Human judgment and responsibility

The following are not delegated to a language model and require human review:

- deciding whether the base manual and amendment are authentic, complete, and
  the correct source bundle;
- approving the source-verified timeline mapping, including which question fact
  controls each amendment's effective date;
- approving the final architecture and release scope;
- interpreting whether two provisions are truly contradictory or merely scoped
  differently;
- confirming that a claimed corpus gap is genuine;
- assigning expected decisions and source clauses to evaluation cases;
- choosing the refusal and direct-coverage thresholds after inspecting false
  answers, false refusals, and missed conflicts;
- deciding which escalation roles are supported by the manual;
- assessing privacy, security, legal, and operational suitability; and
- accepting residual failure modes and the final measured evaluation result.

AI-generated labels and findings are hypotheses until reviewed against the
authoritative sources. The checked-in `source_verified` markers mean that cited
wording and timeline mappings were rechecked against the supplied manual and
amendment; they do not imply independent human, legal, or operational approval.

## Safeguards against AI-authored policy

- The checked-in base manual and effective amendment are the policy sources of
  truth; AI did not rewrite either source.
- The system does not use AI to invent official clause IDs, page numbers,
  amendment paragraph locators, deadlines, amounts, effective-date rules,
  contact details, exceptions, or precedence rules.
- LLM generation is optional and downstream of the deterministic decision.
- Provider-selected source IDs are allowlisted against retrieved chunks and
  mapped back to trusted ingestion metadata in code.
- Unsupported provider output is discarded. The system falls back to the exact
  already-validated source clause; it refuses only if that trusted fallback also
  cannot satisfy the answer contract.
- Evaluation failures are retained and must not be relabeled merely to improve a
  score.

## Limitations of AI assistance

AI review can miss bugs, misread policy scope, overfit rules to known questions,
or produce plausible but incorrect documentation. Passing generated tests does
not prove policy correctness. Final claims should therefore be based on the
checked-in source, source-verified labels, executed tests, and the generated
evaluation report—not on an AI statement that the project “should work.”
