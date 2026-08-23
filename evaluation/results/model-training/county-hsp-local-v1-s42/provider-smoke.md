# Optional Gemini provider smoke test

**Executed:** 2026-08-23T04:23:04Z  
**Provider profile:** `gemini-3.6-flash`, minimal thinking  
**Retrieval profile:** pretrained local Sentence Transformer plus pretrained local reranker

Credentials were loaded from the ignored runtime environment and are not included
in this artifact. No personal case data was used.

| Query class | Expected | Observed | Contract check |
|---|---|---|---|
| Supported resource-limit lookup | `ANSWER` | `ANSWER` | Returned the exact `exceed $4,000` boundary with trusted citation §2.4.1. |
| Unsupported service/referral request | `REFUSE` | `REFUSE` | Returned no citation and directed the user to a Department caseworker at a district office. |

The provider was permitted to phrase only the already-authorized supported answer.
The unsupported query remained on the deterministic refusal path. This is an
external-service smoke test, not training evidence or a guarantee of future model
behavior.
