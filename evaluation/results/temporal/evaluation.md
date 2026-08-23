# Evaluation Results — The Grounded Answer

**Generated (UTC):** 2026-08-23T10:29:39.425573+00:00
**Run type:** `strict_end_to_end`
**Corpus SHA-256:** `225267869bb2b02536fe59f4d73c53106305460127bdf0f15fd4a5bce796cbca`
**Embedding backend:** `hashing`
**Reranking:** disabled
**LLM/provider:** deterministic; no generation API used

## Aggregate metrics

| Metric | Result |
| :-- | --: |
| Strict cases passed | 16 / 16 (100.0%) |
| Decision accuracy | 16 / 16 (100.0%) |
| ANSWER decision precision / recall | 100.0% / 100.0% (10 correct) |
| REFUSE decision precision / recall | 100.0% / 100.0% (4 correct) |
| CONFLICT decision precision / recall | 100.0% / 100.0% (2 correct) |
| Expected evidence retrieval | 25 / 25 (100.0%) |
| Required citation recall | 18 / 18 (100.0%) |
| Required amendment/source citation recall | 27 / 27 (100.0%) |
| Citation integrity | 16 / 16 (100.0%) |
| Expected fact recall | 28 / 28 (100.0%) |
| Unsupported-claim safety | 16 / 16 (100.0%) |
| False answers on REFUSE/CONFLICT cases | 0 / 6 (0.0%) |

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
| T01 | TEMPORAL_BEFORE_EFFECTIVE_DATE | ANSWER | ANSWER | PASS | PASS | PASS | PASS | PASS | — |
| T02 | TEMPORAL_AFTER_EFFECTIVE_DATE | ANSWER | ANSWER | PASS | PASS | PASS | PASS | PASS | — |
| T03 | MISSING_DETERMINATION_DATE | REFUSE | REFUSE | PASS | PASS | PASS | PASS | PASS | — |
| T04 | PRE_AMENDMENT_CONFLICT | CONFLICT | CONFLICT | PASS | PASS | PASS | PASS | PASS | — |
| T05 | POST_AMENDMENT_REPORTING | ANSWER | ANSWER | PASS | PASS | PASS | PASS | PASS | — |
| T06 | MISSING_CHANGE_DATE | REFUSE | REFUSE | PASS | PASS | PASS | PASS | PASS | — |
| T07 | TEMPORAL_THRESHOLD_BEFORE | ANSWER | ANSWER | PASS | PASS | PASS | PASS | PASS | — |
| T08 | TEMPORAL_THRESHOLD_AFTER | ANSWER | ANSWER | PASS | PASS | PASS | PASS | PASS | — |
| T09 | TEMPORAL_SANCTION_RATE_BEFORE | ANSWER | ANSWER | PASS | PASS | PASS | PASS | PASS | — |
| T10 | TEMPORAL_SANCTION_RATE_AFTER | ANSWER | ANSWER | PASS | PASS | PASS | PASS | PASS | — |
| T11 | INSERTED_PROTECTION_AFTER | ANSWER | ANSWER | PASS | PASS | PASS | PASS | PASS | — |
| T12 | INSERTED_PROTECTION_BEFORE | REFUSE | REFUSE | PASS | PASS | PASS | PASS | PASS | — |
| T13 | SPANNING_CLAIM_PERIOD | ANSWER | ANSWER | PASS | PASS | PASS | PASS | PASS | — |
| T14 | AMBIGUOUS_NUMERIC_DATE | REFUSE | REFUSE | PASS | PASS | PASS | PASS | PASS | — |
| T15 | PRE_AMENDMENT_PRONOUN_REPORTING | CONFLICT | CONFLICT | PASS | PASS | PASS | PASS | PASS | — |
| T16 | POST_AMENDMENT_PRONOUN_REPORTING | ANSWER | ANSWER | PASS | PASS | PASS | PASS | PASS | — |

## Full case results

### T01 — PASS

For a determination made on 28 February 2026, what is the monthly earnings disregard?

- Expected / actual: `ANSWER` / `ANSWER`
- Retrieved clauses: `6.4.1`, `6.4.2`, `1.2.3`, `chunk_506c806640ea4c17`, `chunk_8ee444fd49d9421c`
- Cited clauses: `6.4.1`, `6.4.2`, `1.2.3`, `chunk_506c806640ea4c17`, `chunk_8ee444fd49d9421c`
- Cited source locators: `manual:6.4.1`, `manual:6.4.2`, `manual:1.2.3`, `amendment-2026-01:1.1`, `amendment-2026-01:5.1`
- Missing evidence: none
- Missing citations: none
- Missing source-locator evidence: none
- Missing source-locator citations: none
- Missing facts: none
- Forbidden claims found: none
- Failure taxonomy: none

#### Complete answer (T01)

```text
For a determination made 28 February 2026, the standard disregards are: the first $120 of monthly household earnings; child support for a dependent child; a qualifying training allowance; disability payments intended for additional disability costs; irregular charitable payments not intended for ordinary living costs; care allowance payments up to $200 per month; and a dependent child's income. The earnings disregard applies once per household, not once per earner.
```

### T02 — PASS

For a determination made on 2 March 2026, what is the monthly earnings disregard?

- Expected / actual: `ANSWER` / `ANSWER`
- Retrieved clauses: `6.4.1`, `6.4.2`, `1.2.3`, `chunk_506c806640ea4c17`, `chunk_8ee444fd49d9421c`
- Cited clauses: `6.4.1`, `6.4.2`, `1.2.3`, `chunk_506c806640ea4c17`, `chunk_8ee444fd49d9421c`
- Cited source locators: `manual:6.4.1`, `manual:6.4.2`, `manual:1.2.3`, `amendment-2026-01:1.1`, `amendment-2026-01:5.1`
- Missing evidence: none
- Missing citations: none
- Missing source-locator evidence: none
- Missing source-locator citations: none
- Missing facts: none
- Forbidden claims found: none
- Failure taxonomy: none

#### Complete answer (T02)

```text
For a determination made 2 March 2026, the standard disregards are: the first $175 of monthly household earnings; child support for a dependent child; a qualifying training allowance; disability payments intended for additional disability costs; irregular charitable payments not intended for ordinary living costs; care allowance payments up to $200 per month; and a dependent child's income. The earnings disregard applies once per household, not once per earner.
```

### T03 — PASS

What is the monthly earnings disregard?

- Expected / actual: `REFUSE` / `REFUSE`
- Retrieved clauses: `6.4.1`, `6.4.2`, `1.2.3`, `chunk_506c806640ea4c17`, `chunk_8ee444fd49d9421c`
- Cited clauses: `6.4.1`, `6.4.2`, `1.2.3`, `chunk_506c806640ea4c17`, `chunk_8ee444fd49d9421c`
- Cited source locators: `manual:6.4.1`, `manual:6.4.2`, `manual:1.2.3`, `amendment-2026-01:1.1`, `amendment-2026-01:5.1`
- Missing evidence: none
- Missing citations: none
- Missing source-locator evidence: none
- Missing source-locator citations: none
- Missing facts: none
- Forbidden claims found: none
- Failure taxonomy: none

#### Complete answer (T03)

```text
I don't know based on the current policy sources which version of the rule applies from the question alone. Please provide the date the determination was made; the amendment makes that date legally controlling.
```

### T04 — PASS

How many days do I have to report a change that happened on 15 February 2026?

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

#### Complete answer (T04)

```text
The change occurred on 15 February 2026, so the pre-amendment wording remains applicable. Section 4.3.2 says the change must be reported within 10 calendar days of the change or awareness, whichever is later. Section 9.1.4 instead describes 30 calendar days as the period required under §4.3 for its overpayment protection. The amendment does not retroactively align those provisions, so I cannot give one conflict-free deadline for this pre-March change.
```

### T05 — PASS

How many days do I have to report a change that happened on 15 March 2026?

- Expected / actual: `ANSWER` / `ANSWER`
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

#### Complete answer (T05)

```text
Because the change occurred on 15 March 2026, it is subject to the amended 14-calendar-day rule. The 14 days run from the later of the date the change occurred and the date the recipient became aware of it. The aligned overpayment provision also uses 14 calendar days for changes on or after 1 March 2026.
```

### T06 — PASS

How many days do I have to report a change?

- Expected / actual: `REFUSE` / `REFUSE`
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

#### Complete answer (T06)

```text
I don't know based on the current policy sources which version of the rule applies from the question alone. Please provide the date the change of circumstances occurred; the amendment makes that date legally controlling.
```

### T07 — PASS

For a determination made on 28 February 2026, what is the monthly countable-income threshold for a household of three?

- Expected / actual: `ANSWER` / `ANSWER`
- Retrieved clauses: `6.6.1`, `1.2.3`, `1.3.3`, `chunk_3f90d6139537779e`, `chunk_8ee444fd49d9421c`
- Cited clauses: `6.6.1`, `1.2.3`, `1.3.3`, `chunk_3f90d6139537779e`, `chunk_8ee444fd49d9421c`
- Cited source locators: `manual:6.6.1`, `manual:1.2.3`, `manual:1.3.3`, `amendment-2026-01:3.1`, `amendment-2026-01:5.1`
- Missing evidence: none
- Missing citations: none
- Missing source-locator evidence: none
- Missing source-locator citations: none
- Missing facts: none
- Forbidden claims found: none
- Failure taxonomy: none

#### Complete answer (T07)

```text
For a determination made 28 February 2026, the monthly countable-income threshold for a household of 3 is $2,000. The threshold rule makes a household ineligible only when countable income exceeds that amount.
```

### T08 — PASS

For a determination made on 2 March 2026, what is the monthly countable-income threshold for a household of three?

- Expected / actual: `ANSWER` / `ANSWER`
- Retrieved clauses: `6.6.1`, `1.2.3`, `1.3.3`, `chunk_3f90d6139537779e`, `chunk_8ee444fd49d9421c`
- Cited clauses: `6.6.1`, `1.2.3`, `1.3.3`, `chunk_3f90d6139537779e`, `chunk_8ee444fd49d9421c`
- Cited source locators: `manual:6.6.1`, `manual:1.2.3`, `manual:1.3.3`, `amendment-2026-01:3.1`, `amendment-2026-01:5.1`
- Missing evidence: none
- Missing citations: none
- Missing source-locator evidence: none
- Missing source-locator citations: none
- Missing facts: none
- Forbidden claims found: none
- Failure taxonomy: none

#### Complete answer (T08)

```text
For a determination made 2 March 2026, the monthly countable-income threshold for a household of 3 is $2,075. The threshold rule makes a household ineligible only when countable income exceeds that amount.
```

### T09 — PASS

What is the sanction percentage for a determination made on 28 February 2026?

- Expected / actual: `ANSWER` / `ANSWER`
- Retrieved clauses: `10.5.2`, `1.2.3`, `chunk_c7fbfed025fcffb5`, `chunk_8ee444fd49d9421c`
- Cited clauses: `10.5.2`, `1.2.3`, `chunk_c7fbfed025fcffb5`, `chunk_8ee444fd49d9421c`
- Cited source locators: `manual:10.5.2`, `manual:1.2.3`, `amendment-2026-01:4.1`, `amendment-2026-01:5.1`
- Missing evidence: none
- Missing citations: none
- Missing source-locator evidence: none
- Missing source-locator citations: none
- Missing facts: none
- Forbidden claims found: none
- Failure taxonomy: none

#### Complete answer (T09)

```text
For a determination made 28 February 2026, a sanction is a 20% reduction of the monthly award for 4 weeks for a first sanction, or 8 weeks for a subsequent sanction within 12 months.
```

### T10 — PASS

What is the sanction percentage for a determination made on 2 March 2026?

- Expected / actual: `ANSWER` / `ANSWER`
- Retrieved clauses: `10.5.2`, `1.2.3`, `chunk_c7fbfed025fcffb5`, `chunk_8ee444fd49d9421c`
- Cited clauses: `10.5.2`, `1.2.3`, `chunk_c7fbfed025fcffb5`, `chunk_8ee444fd49d9421c`
- Cited source locators: `manual:10.5.2`, `manual:1.2.3`, `amendment-2026-01:4.1`, `amendment-2026-01:5.1`
- Missing evidence: none
- Missing citations: none
- Missing source-locator evidence: none
- Missing source-locator citations: none
- Missing facts: none
- Forbidden claims found: none
- Failure taxonomy: none

#### Complete answer (T10)

```text
For a determination made 2 March 2026, a sanction is a 15% reduction of the monthly award for 4 weeks for a first sanction, or 8 weeks for a subsequent sanction within 12 months.
```

### T11 — PASS

For a determination made on 2 March 2026, may a sanction be imposed for failure to report a change that would have increased the award?

- Expected / actual: `ANSWER` / `ANSWER`
- Retrieved clauses: `4.3.4`, `10.5.1`, `1.2.3`, `chunk_75b4dc8667339d2e`, `chunk_8ee444fd49d9421c`
- Cited clauses: `4.3.4`, `10.5.1`, `1.2.3`, `chunk_75b4dc8667339d2e`, `chunk_8ee444fd49d9421c`
- Cited source locators: `manual:4.3.4`, `manual:10.5.1`, `manual:1.2.3`, `amendment-2026-01:4.2`, `amendment-2026-01:5.1`
- Missing evidence: none
- Missing citations: none
- Missing source-locator evidence: none
- Missing source-locator citations: none
- Missing facts: none
- Forbidden claims found: none
- Failure taxonomy: none

#### Complete answer (T11)

```text
For a determination made 2 March 2026, no sanction may be imposed for failure to report if the change would have increased the award. That protection does not remove the separate duty to report the change.
```

### T12 — PASS

For a determination made on 28 February 2026, may a sanction be imposed for failure to report a change that would have increased the award?

- Expected / actual: `REFUSE` / `REFUSE`
- Retrieved clauses: `4.3.4`, `10.5.1`, `1.2.3`, `chunk_75b4dc8667339d2e`, `chunk_8ee444fd49d9421c`
- Cited clauses: `4.3.4`, `10.5.1`, `1.2.3`, `chunk_75b4dc8667339d2e`, `chunk_8ee444fd49d9421c`
- Cited source locators: `manual:4.3.4`, `manual:10.5.1`, `manual:1.2.3`, `amendment-2026-01:4.2`, `amendment-2026-01:5.1`
- Missing evidence: none
- Missing citations: none
- Missing source-locator evidence: none
- Missing source-locator citations: none
- Missing facts: none
- Forbidden claims found: none
- Failure taxonomy: none

#### Complete answer (T12)

```text
I don't know of a pre-amendment rule that specifically protects a late report when the change would have increased the award. The general manual allows a failure-to-report sanction, but the new specific prohibition was not yet in force for a determination made 28 February 2026.
```

### T13 — PASS

For a claim period from 20 February 2026 through 10 March 2026, how should the award be calculated?

- Expected / actual: `ANSWER` / `ANSWER`
- Retrieved clauses: `7.4.3`, `chunk_ef0704842e697c03`
- Cited clauses: `7.4.3`, `chunk_ef0704842e697c03`
- Cited source locators: `manual:7.4.3`, `amendment-2026-01:5.3`
- Missing evidence: none
- Missing citations: none
- Missing source-locator evidence: none
- Missing source-locator citations: none
- Missing facts: none
- Forbidden claims found: none
- Failure taxonomy: none

#### Complete answer (T13)

```text
For a claim period spanning 1 March 2026, do not use one blended or latest figure for the whole period. Use the figures in force on each day: the pre-amendment figures before 1 March and the amended figures from 1 March onward, then apportion the award by the number of days. An exact award still requires the period dates and the other calculation facts.
```

### T14 — PASS

How many days do I have to report a change that happened on 03/04/2026?

- Expected / actual: `REFUSE` / `REFUSE`
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

#### Complete answer (T14)

```text
I don't know based on the current policy sources which version of the rule applies from the question alone. Please provide the date the change of circumstances occurred; the amendment makes that date legally controlling.
```

### T15 — PASS

A change occurred on 15 February 2026. How many days did the recipient have to report it?

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

#### Complete answer (T15)

```text
The change occurred on 15 February 2026, so the pre-amendment wording remains applicable. Section 4.3.2 says the change must be reported within 10 calendar days of the change or awareness, whichever is later. Section 9.1.4 instead describes 30 calendar days as the period required under §4.3 for its overpayment protection. The amendment does not retroactively align those provisions, so I cannot give one conflict-free deadline for this pre-March change.
```

### T16 — PASS

A change occurred on 15 March 2026. How many days did the recipient have to report it?

- Expected / actual: `ANSWER` / `ANSWER`
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

#### Complete answer (T16)

```text
Because the change occurred on 15 March 2026, it is subject to the amended 14-calendar-day rule. The 14 days run from the later of the date the change occurred and the date the recipient became aware of it. The aligned overpayment provision also uses 14 calendar days for changes on or after 1 March 2026.
```

## Method

Every case exercised `GroundedAnswerPipeline.ask(..., include_trace=True)` with deterministic answer construction and reranking disabled. A case passes only when all recorded checks pass; retrieval-only success is insufficient.
