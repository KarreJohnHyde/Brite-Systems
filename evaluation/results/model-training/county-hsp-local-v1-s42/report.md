# Local model training and evaluation

**Status:** complete
**Run:** `county-hsp-local-v1-s42`

The bi-encoder and cross-encoder are the only trainable local models. Gemini is hosted and the deterministic retrieval/safety components have no learned weights.

## Dataset and split

- Queries: 33
- Clauses: 148
- Expected evidence pairs: 65
- Evaluation: every query held out once in two clause-disjoint folds

## Pretrained baseline

| Stage | Recall@1 | Recall@6 | MRR | nDCG@10 |
|---|---:|---:|---:|---:|
| Dense | 0.308 | 0.662 | 0.836 | 0.749 |
| Reranked | 0.308 | 0.646 | 0.836 | 0.769 |

## Trained held-out cross-validation

- Dense: Recall@6 0.615 (σ 0.000), MRR 0.794 (σ 0.000)
- Reranked: Recall@6 0.646 (σ 0.000), MRR 0.837 (σ 0.000)

## Final experimental candidate

This model was fitted on all reviewed queries. Its values are regression checks, not blind metrics.

- Dense in-sample Recall@6: 0.892
- Reranked in-sample Recall@6: 0.754
- Core end-to-end: 18 passed, 0 failed
- Adversarial end-to-end: 15 passed, 0 failed

## Release decision

Keep this candidate opt-in until it improves held-out ranking without any safety regression and is validated on a newly collected blind staff-query set.
