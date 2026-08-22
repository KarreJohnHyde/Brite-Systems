# Evaluation Results — The Grounded Answer

**Date**: 2026-08-22 23:46:24
**Total questions**: 10
**Passed**: 5
**Failed**: 5
**Pass rate**: 50%

## Summary Table

| ID | Question | Expected | Actual | Score | Pass |
|:--|:--|:--|:--|:--|:--|
| Q01 | What is the resource limit for household eligibili... | answer | answer | 5.969 | ✅ |
| Q02 | How long can a recipient be temporarily absent fro... | answer | answer | 7.849 | ✅ |
| Q03 | What income is disregarded when calculating eligib... | answer | answer | 3.599 | ❌ |
| Q04 | Can a 17-year-old apply for assistance?... | answer | answer | -0.399 | ✅ |
| Q05 | How many days does a recipient have to report a ch... | conflict | conflict | 8.873 | ✅ |
| Q06 | If I fail to report a change, how much time does t... | conflict | answer | 0.472 | ❌ |
| Q07 | How is the needs figure calculated for a full-time... | refuse | answer | 9.678 | ❌ |
| Q08 | Does cryptocurrency count as income or a resource?... | refuse | refuse | -1.129 | ✅ |
| Q09 | What is the sanction for failing to attend an inte... | answer | answer | 6.775 | ❌ |
| Q10 | Can I appeal a decision, and what is the time limi... | answer | answer | 2.089 | ❌ |

## Detailed Results

### [Q01] What is the resource limit for household eligibility?

- **Expected state**: answer
- **Actual state**: answer
- **Top retrieval score**: 5.969
- **Retrieved clauses**: 2.4.1, 6.6.1, 2.1.3, 2.4.2, 2.4.3
- **Result**: ✅ PASS

> Straightforward lookup — §2.4.1 states $4,000 resource limit

**Response preview**:
```
(No LLM available for answer generation)
```

### [Q02] How long can a recipient be temporarily absent from the county and still remain eligible?

- **Expected state**: answer
- **Actual state**: answer
- **Top retrieval score**: 7.849
- **Retrieved clauses**: 3.2.1, 3.2.2, 5.2.1, 3.2.4, 5.2.2
- **Result**: ✅ PASS

> Clear answer: 28 days normally, 90 days for medical/bereavement reasons

**Response preview**:
```
(No LLM available for answer generation)
```

### [Q03] What income is disregarded when calculating eligibility?

- **Expected state**: answer
- **Actual state**: answer
- **Top retrieval score**: 3.599
- **Retrieved clauses**: 5.5.1, 1.4.7, 6.1.1, 6.4.2, 6.6.1
- **Result**: ❌ FAIL

- **Missing clauses**: 6.4.1

> Tests whether the system retrieves the full disregard list with sub-items

**Response preview**:
```
(No LLM available for answer generation)
```

### [Q04] Can a 17-year-old apply for assistance?

- **Expected state**: answer
- **Actual state**: answer
- **Top retrieval score**: -0.399
- **Retrieved clauses**: 2.3.1, 2.1.1, 1.4.1, 10.5.3, 7.3.1
- **Result**: ✅ PASS

> §2.3.1 covers 16-17 year olds with specific conditions

**Response preview**:
```
(No LLM available for answer generation)
```

### [Q05] How many days does a recipient have to report a change of circumstances?

- **Expected state**: conflict
- **Actual state**: conflict
- **Top retrieval score**: 8.873
- **Retrieved clauses**: 4.3.2, 9.1.4, 10.5.1, 9.6.1, 10.3.2
- **Result**: ✅ PASS

> DELIBERATE CONTRADICTION: §4.3.2 says 10 calendar days, §9.1.4 says '30 calendar days required under §4.3'. These directly conflict.

**Response preview**:
```
⚠ MANUAL CONFLICT

The policy manual does not provide a single consistent answer to this question. The following clauses appear to contradict each other:

  Clause §4.3.2 (4.3 Recipient obligations):
    "A recipient must report any change in household composition, income, address, or the circumstan
```

### [Q06] If I fail to report a change, how much time does the manual say I had to report it?

- **Expected state**: conflict
- **Actual state**: answer
- **Top retrieval score**: 0.472
- **Retrieved clauses**: 4.3.2, 4.3.4, 9.1.4, 11.2.3, 11.1.2
- **Result**: ❌ FAIL

> Same contradiction tested with different phrasing

**Response preview**:
```
(No LLM available for answer generation)
```

### [Q07] How is the needs figure calculated for a full-time student?

- **Expected state**: refuse
- **Actual state**: answer
- **Top retrieval score**: 9.678
- **Retrieved clauses**: 7.1.3, 7.3.3, 7.3.1, 1.4.6, 7.3.2
- **Result**: ❌ FAIL

> APPARENT GAP: §7.1.3 says 'except in the case of full-time students (see §5.4)' but §5.4 covers care allowances, not students. No section actually defines student needs figures.

**Response preview**:
```
(No LLM available for answer generation)
```

### [Q08] Does cryptocurrency count as income or a resource?

- **Expected state**: refuse
- **Actual state**: refuse
- **Top retrieval score**: -1.129
- **Retrieved clauses**: 6.3.1, 6.1.2, 6.3.2, 2.4.3, 2.4.1
- **Result**: ✅ PASS

> Completely absent from the manual — no clause mentions cryptocurrency, digital assets, or virtual currency

**Response preview**:
```
I don't know based on the current policy manual.

Reason: The closest matching clauses scored below the confidence threshold (best score: -1.13, threshold: -1.0). The manual may not address this topic.

Please contact:
  Benefits Eligibility Team
  Phone: (555) 234-5679
  Email: eligibility@calderco
```

### [Q09] What is the sanction for failing to attend an interview?

- **Expected state**: answer
- **Actual state**: answer
- **Top retrieval score**: 6.775
- **Retrieved clauses**: 10.5.1, 8.5.1, 4.3.4, 4.3.1, 8.6.1
- **Result**: ❌ FAIL

- **Missing clauses**: 10.5.2

> §10.5.1(b) lists interview failure as sanctionable; §10.5.2 states 20% reduction for 4 weeks (first) or 8 weeks (subsequent)

**Response preview**:
```
(No LLM available for answer generation)
```

### [Q10] Can I appeal a decision, and what is the time limit?

- **Expected state**: answer
- **Actual state**: answer
- **Top retrieval score**: 2.089
- **Retrieved clauses**: 12.1.2, 12.1.3, 12.3.3, 11.3.2, 12.2.3
- **Result**: ❌ FAIL

- **Missing clauses**: 12.1.1

> §12.1.1 gives the right of appeal; §12.1.2 gives the 30-day time limit

**Response preview**:
```
(No LLM available for answer generation)
```

## Analysis

### What worked

- **Q01**: Correctly produced `answer` state
- **Q02**: Correctly produced `answer` state
- **Q04**: Correctly produced `answer` state
- **Q05**: Correctly produced `conflict` state
- **Q08**: Correctly produced `refuse` state

### What failed

- **Q03**: Expected `answer` but got `answer`. Missing clauses: 6.4.1
- **Q06**: Expected `conflict` but got `answer`. 
- **Q07**: Expected `refuse` but got `answer`. 
- **Q09**: Expected `answer` but got `answer`. Missing clauses: 10.5.2
- **Q10**: Expected `answer` but got `answer`. Missing clauses: 12.1.1

### Threshold calibration

The current relevance threshold is set at the value defined in `src/evidence.py`.
See DECISIONS.md for the rationale behind this threshold.
