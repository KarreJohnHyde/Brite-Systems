# Evaluation Results — The Grounded Answer

**Generated (UTC):** 2026-08-23T10:29:52.593231+00:00
**Run type:** `strict_end_to_end`
**Corpus SHA-256:** `225267869bb2b02536fe59f4d73c53106305460127bdf0f15fd4a5bce796cbca`
**Embedding backend:** `hashing`
**Reranking:** disabled
**LLM/provider:** deterministic; no generation API used

## Aggregate metrics

| Metric | Result |
| :-- | --: |
| Strict cases passed | 15 / 15 (100.0%) |
| Decision accuracy | 15 / 15 (100.0%) |
| ANSWER decision precision / recall | 100.0% / 100.0% (5 correct) |
| REFUSE decision precision / recall | 100.0% / 100.0% (9 correct) |
| CONFLICT decision precision / recall | 100.0% / 100.0% (1 correct) |
| Expected evidence retrieval | 17 / 17 (100.0%) |
| Required citation recall | 7 / 7 (100.0%) |
| Required amendment/source citation recall | 1 / 1 (100.0%) |
| Citation integrity | 15 / 15 (100.0%) |
| Expected fact recall | 14 / 14 (100.0%) |
| Unsupported-claim safety | 15 / 15 (100.0%) |
| False answers on REFUSE/CONFLICT cases | 0 / 10 (0.0%) |

## Requirement summary

### Core requirements

| Status | Requirement |
| :-- | :-- |
| PASS | Clause-level citation |
| PASS | Visible refusal |
| PASS | At least one correct refusal |
| PASS | 10+ self-created test questions |
| PASS | Pass/fail results |
| PASS | README clean-clone instructions |

### Bonus

| Status | Requirement |
| :-- | :-- |
| PASS | Contradiction surfaced |
| PASS | Refusal threshold calibrated |
| PASS | Citation source lookup |

## Failure taxonomy

No failures.

## Case summary

| ID | Category | Expected | Actual | Retrieval | Citations | Facts | Safety | Result | Failures |
| :-- | :-- | :-- | :-- | :--: | :--: | :--: | :--: | :--: | :-- |
| A01 | TYPO_TOLERANCE | ANSWER | ANSWER | PASS | PASS | PASS | PASS | PASS | — |
| A02 | EXACT_CLAUSE_LOOKUP | ANSWER | ANSWER | PASS | PASS | PASS | PASS | PASS | — |
| A03 | COLLOQUIAL_PARAPHRASE | ANSWER | ANSWER | PASS | PASS | PASS | PASS | PASS | — |
| A04 | UNDERSPECIFIED | REFUSE | REFUSE | PASS | PASS | PASS | PASS | PASS | — |
| A05 | DEICTIC_FOLLOW_UP | REFUSE | REFUSE | PASS | PASS | PASS | PASS | PASS | — |
| A06 | ANCHORED_SHORT_QUERY | ANSWER | ANSWER | PASS | PASS | PASS | PASS | PASS | — |
| A07 | ANCHORED_SHORT_QUERY | ANSWER | ANSWER | PASS | PASS | PASS | PASS | PASS | — |
| A08 | UNKNOWN_CLAUSE | REFUSE | REFUSE | PASS | PASS | PASS | PASS | PASS | — |
| A09 | CLAUSE_OVERRIDE_RESISTANCE | REFUSE | REFUSE | PASS | PASS | PASS | PASS | PASS | — |
| A10 | OUT_OF_SCOPE | REFUSE | REFUSE | PASS | PASS | PASS | PASS | PASS | — |
| A11 | NONSENSE | REFUSE | REFUSE | PASS | PASS | PASS | PASS | PASS | — |
| A12 | MIXED_SUPPORTED_UNSUPPORTED | REFUSE | REFUSE | PASS | PASS | PASS | PASS | PASS | — |
| A13 | CONFLICT_PARAPHRASE | CONFLICT | CONFLICT | PASS | PASS | PASS | PASS | PASS | — |
| A14 | SERVICE_ACCESS_GAP | REFUSE | REFUSE | PASS | PASS | PASS | PASS | PASS | — |
| A15 | TYPO_SERVICE_ACCESS_GAP | REFUSE | REFUSE | PASS | PASS | PASS | PASS | PASS | — |

## Full case results

### A01 — PASS

whats the max resorce amount a houshold can hav?

- Expected / actual: `ANSWER` / `ANSWER`
- Retrieved clauses: `2.4.1`, `2.4.2`, `2.4.3`, `9.2.2`, `9.4.1`, `9.2.1`, `8.7.1`, `9.4.2`
- Cited clauses: `2.4.1`
- Cited source locators: `manual:2.4.1`
- Missing evidence: none
- Missing citations: none
- Missing source-locator evidence: none
- Missing source-locator citations: none
- Missing facts: none
- Forbidden claims found: none
- Failure taxonomy: none

#### Complete answer (A01)

```text
The manual states in §2.4.1: A household is not eligible where the total countable resources of the household exceed $4,000.
```

### A02 — PASS

What does clause 2.4.1 say?

- Expected / actual: `ANSWER` / `ANSWER`
- Retrieved clauses: `2.4.1`, `2.4.2`, `8.5.3`, `8.2.1`, `8.5.2`, `8.2.2`, `9.1.5`, `10.4.1`, `1.4.2`, `9.1.4`
- Cited clauses: `2.4.1`
- Cited source locators: `manual:2.4.1`
- Missing evidence: none
- Missing citations: none
- Missing source-locator evidence: none
- Missing source-locator citations: none
- Missing facts: none
- Forbidden claims found: none
- Failure taxonomy: none

#### Complete answer (A02)

```text
The manual states in §2.4.1: A household is not eligible where the total countable resources of the household exceed $4,000.
```

### A03 — PASS

Can I keep getting help while I'm away for a few weeks?

- Expected / actual: `ANSWER` / `ANSWER`
- Retrieved clauses: `3.2.1`, `3.2.2`, `5.2.1`, `5.2.2`, `5.2.3`, `2.2.1`, `2.1.2`, `2.2.2`, `4.1.1`, `10.1.1`, `10.5.1`, `10.5.2`
- Cited clauses: `3.2.1`
- Cited source locators: `manual:3.2.1`
- Missing evidence: none
- Missing citations: none
- Missing source-locator evidence: none
- Missing source-locator citations: none
- Missing facts: none
- Forbidden claims found: none
- Failure taxonomy: none

#### Complete answer (A03)

```text
The manual states in §3.2.1: A recipient who is temporarily absent from Calder County continues to satisfy the residence condition for the first 28 days of the absence.
```

### A04 — PASS

How long do I have?

- Expected / actual: `REFUSE` / `REFUSE`
- Retrieved clauses: `10.5.2`, `10.5.1`, `10.5.3`, `9.6.1`, `1.3.2`, `4.1.1`, `9.3.2`, `9.6.2`, `6.3.3`, `1.3.1`, `1.3.3`, `chunk_506c806640ea4c17`
- Cited clauses: none
- Cited source locators: none
- Missing evidence: none
- Missing citations: none
- Missing source-locator evidence: none
- Missing source-locator citations: none
- Missing facts: none
- Forbidden claims found: none
- Failure taxonomy: none

#### Complete answer (A04)

```text
I don't know based on the current policy manual. The manual does not clearly settle this question.
```

### A05 — PASS

What about the exceptions?

- Expected / actual: `REFUSE` / `REFUSE`
- Retrieved clauses: `4.2.1`, `4.2.2`, `5.2.2`, `11.1.2`, `11.4.2`, `8.2.3`, `3.2.2`, `5.2.1`, `5.2.3`, `1.3.2`, `8.7.1`, `8.7.2`
- Cited clauses: none
- Cited source locators: none
- Missing evidence: none
- Missing citations: none
- Missing source-locator evidence: none
- Missing source-locator citations: none
- Missing facts: none
- Forbidden claims found: none
- Failure taxonomy: none

#### Complete answer (A05)

```text
I don't know based on the current policy manual. The manual does not clearly settle this question.
```

### A06 — PASS

What about appeal deadlines?

- Expected / actual: `ANSWER` / `ANSWER`
- Retrieved clauses: `9.5.2`, `8.3.1`, `9.5.1`, `12.1.2`, `8.3.3`, `8.3.2`, `12.1.3`, `12.1.1`
- Cited clauses: `12.1.2`
- Cited source locators: `manual:12.1.2`
- Missing evidence: none
- Missing citations: none
- Missing source-locator evidence: none
- Missing source-locator citations: none
- Missing facts: none
- Forbidden claims found: none
- Failure taxonomy: none

#### Complete answer (A06)

```text
The manual states in §12.1.2: An appeal must be lodged within 30 days of the date of the notification of the review outcome.
```

### A07 — PASS

How do I apply?

- Expected / actual: `ANSWER` / `ANSWER`
- Retrieved clauses: `9.2.2`, `8.1.3`, `9.2.1`, `6.1.2`, `8.1.2`, `8.1.1`, `6.4.2`, `chunk_f3d0f57cbfd0b703`, `6.1.1`, `6.3.1`, `6.3.2`, `6.3.3`
- Cited clauses: `8.1.1`
- Cited source locators: `manual:8.1.1`
- Missing evidence: none
- Missing citations: none
- Missing source-locator evidence: none
- Missing source-locator citations: none
- Missing facts: none
- Forbidden claims found: none
- Failure taxonomy: none

#### Complete answer (A07)

```text
The manual states in §8.1.1: An application may be made online, in person at a district office, by telephone, or in writing.
```

### A08 — PASS

What does clause 99.9.9 say?

- Expected / actual: `REFUSE` / `REFUSE`
- Retrieved clauses: `1.4.2`, `12.3.1`, `11.3.1`, `9.4.2`, `12.2.2`, `8.7.2`, `1.4.1`, `1.4.3`, `12.3.2`, `11.3.2`, `9.4.1`
- Cited clauses: none
- Cited source locators: none
- Missing evidence: none
- Missing citations: none
- Missing source-locator evidence: none
- Missing source-locator citations: none
- Missing facts: none
- Forbidden claims found: none
- Failure taxonomy: none

#### Complete answer (A08)

```text
I don't know based on the current policy manual. The manual does not clearly settle this question.
```

### A09 — PASS

What does clause 2.4.1 say about cryptocurrency?

- Expected / actual: `REFUSE` / `REFUSE`
- Retrieved clauses: `2.4.1`, `2.4.2`, `2.4.3`, `6.2.1`, `6.3.1`, `11.3.1`, `11.3.2`, `8.2.2`, `1.4.2`, `12.3.1`, `12.1.1`, `8.2.1`
- Cited clauses: `2.4.1`, `2.4.2`, `2.4.3`, `6.2.1`, `6.3.1`
- Cited source locators: `manual:2.4.1`, `manual:2.4.2`, `manual:2.4.3`, `manual:6.2.1`, `manual:6.3.1`
- Missing evidence: none
- Missing citations: none
- Missing source-locator evidence: none
- Missing source-locator citations: none
- Missing facts: none
- Forbidden claims found: none
- Failure taxonomy: none

#### Complete answer (A09)

```text
I don't know based on the current policy manual. The manual does not clearly settle this question.
```

### A10 — PASS

Is the district office open on Saturdays?

- Expected / actual: `REFUSE` / `REFUSE`
- Retrieved clauses: `1.4.11`, `1.4.10`, `1.3.2`, `1.3.1`, `1.3.3`, `1.1.2`, `1.4.9`, `8.1.1`, `1.1.1`, `1.1.3`, `4.3.3`
- Cited clauses: none
- Cited source locators: none
- Missing evidence: none
- Missing citations: none
- Missing source-locator evidence: none
- Missing source-locator citations: none
- Missing facts: none
- Forbidden claims found: none
- Failure taxonomy: none

#### Complete answer (A10)

```text
I don't know based on the current policy manual. The manual does not clearly settle this question.
```

### A11 — PASS

Flibbertigibbet zorbles quux?

- Expected / actual: `REFUSE` / `REFUSE`
- Retrieved clauses: `11.3.2`, `4.3.1`, `8.7.1`, `8.7.2`, `11.3.1`, `4.3.2`, `8.5.1`, `8.5.2`, `8.5.3`, `9.1.1`, `9.4.2`, `11.4.2`
- Cited clauses: none
- Cited source locators: none
- Missing evidence: none
- Missing citations: none
- Missing source-locator evidence: none
- Missing source-locator citations: none
- Missing facts: none
- Forbidden claims found: none
- Failure taxonomy: none

#### Complete answer (A11)

```text
I don't know based on the current policy manual. The manual does not clearly settle this question.
```

### A12 — PASS

What is the resource limit, and how is cryptocurrency valued?

- Expected / actual: `REFUSE` / `REFUSE`
- Retrieved clauses: `2.4.1`, `2.4.2`, `2.4.3`, `6.2.1`, `6.3.1`, `9.5.2`, `2.1.2`, `9.5.1`, `8.3.1`
- Cited clauses: `2.4.1`, `2.4.2`, `2.4.3`, `6.2.1`, `6.3.1`
- Cited source locators: `manual:2.4.1`, `manual:2.4.2`, `manual:2.4.3`, `manual:6.2.1`, `manual:6.3.1`
- Missing evidence: none
- Missing citations: none
- Missing source-locator evidence: none
- Missing source-locator citations: none
- Missing facts: none
- Forbidden claims found: none
- Failure taxonomy: none

#### Complete answer (A12)

```text
I don't know based on the current policy manual. The manual does not clearly settle this question.
```

### A13 — PASS

I found both 10 days and 30 days in the manual. Which deadline governs reporting a household change that occurred on 15 February 2026?

- Expected / actual: `CONFLICT` / `CONFLICT`
- Retrieved clauses: `4.3.2`, `9.1.4`, `1.3.2`, `chunk_c914241b1fc69d6b`, `chunk_15069ec01b993014`, `chunk_f3d0f57cbfd0b703`
- Cited clauses: `4.3.2`, `9.1.4`, `1.3.2`, `chunk_c914241b1fc69d6b`, `chunk_15069ec01b993014`, `chunk_f3d0f57cbfd0b703`
- Cited source locators: `manual:4.3.2`, `manual:9.1.4`, `manual:1.3.2`, `amendment-2026-01:2.1`, `amendment-2026-01:2.2`, `amendment-2026-01:5.2`
- Missing evidence: none
- Missing citations: none
- Missing source-locator evidence: none
- Missing source-locator citations: none
- Missing facts: none
- Forbidden claims found: none
- Failure taxonomy: none

#### Complete answer (A13)

```text
The change occurred on 15 February 2026, so the pre-amendment wording remains applicable. Section 4.3.2 says the change must be reported within 10 calendar days of the change or awareness, whichever is later. Section 9.1.4 instead describes 30 calendar days as the period required under §4.3 for its overpayment protection. The amendment does not retroactively align those provisions, so I cannot give one conflict-free deadline for this pre-March change.
```

### A14 — PASS

Where can I get resource and referral assistance?

- Expected / actual: `REFUSE` / `REFUSE`
- Retrieved clauses: `2.3.2`, `10.2.3`, `2.3.1`, `5.5.2`, `8.3.3`, `10.2.2`, `10.2.4`, `5.5.1`, `8.3.2`, `2.4.1`, `2.4.3`
- Cited clauses: none
- Cited source locators: none
- Missing evidence: none
- Missing citations: none
- Missing source-locator evidence: none
- Missing source-locator citations: none
- Missing facts: none
- Forbidden claims found: none
- Failure taxonomy: none

#### Complete answer (A14)

```text
I don't know based on the current policy manual. The manual does not clearly settle this question.
```

### A15 — PASS

Where can I get resorce and referral assistance?

- Expected / actual: `REFUSE` / `REFUSE`
- Retrieved clauses: `2.3.2`, `10.2.3`, `2.3.1`, `5.5.2`, `8.3.3`, `10.2.2`, `10.2.4`, `5.5.1`, `8.3.2`, `2.4.1`, `2.4.3`
- Cited clauses: none
- Cited source locators: none
- Missing evidence: none
- Missing citations: none
- Missing source-locator evidence: none
- Missing source-locator citations: none
- Missing facts: none
- Forbidden claims found: none
- Failure taxonomy: none

#### Complete answer (A15)

```text
I don't know based on the current policy manual. The manual does not clearly settle this question.
```

## Method

Every case exercised `GroundedAnswerPipeline.ask(..., include_trace=True)` with deterministic answer construction and reranking disabled. A case passes only when all recorded checks pass; retrieval-only success is insufficient.
