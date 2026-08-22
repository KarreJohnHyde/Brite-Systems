# Architectural Decisions

This document details the critical design decisions made while building **The Grounded Answer**, balancing the need for accuracy in public policy with the capabilities of generative AI.

## 1. Architecture: Why RAG?
We chose a Retrieval-Augmented Generation (RAG) architecture because fine-tuning an LLM on the policy manual risks the model hallucinating answers or learning policy rules that quickly become outdated. In a county benefits office, an answer is only valid if it corresponds to current, written policy. By using RAG, the LLM is restricted to reasoning over explicitly provided excerpts, allowing us to build an audit trail (citations) for every claim.

## 2. Chunking: Clause-Aware vs. Fixed-Size
Standard character-count or token-count chunking often splits sentences mid-thought or groups unrelated clauses together. For this project, we implemented **clause-aware chunking**. The `ClauseParser` reads the Markdown corpus and segments text based on heading and list hierarchies (e.g., `§4.3.2`). This ensures that each chunk represents a discrete, atomic policy rule, preventing the LLM from conflating rules from adjacent sections. 

## 3. Embeddings
We selected `sentence-transformers/all-MiniLM-L6-v2`. It is lightweight enough to run locally without a GPU while providing strong semantic similarity matching for standard English text. While larger models (like OpenAI `text-embedding-3-small`) could offer marginal improvements in recall, the MiniLM model allows for rapid iteration and entirely offline deployment.

## 4. Reranking
Semantic similarity (from the embedding model) is insufficient for determining whether a clause actually *answers* a question. A clause might use identical vocabulary (e.g., "full-time student") but fail to provide the requested procedural instruction. We introduced a Cross-Encoder (`cross-encoder/ms-marco-MiniLM-L-6-v2`) to rerank the top-k results from FAISS. The Cross-Encoder scores the relationship between the query and the clause, drastically improving the precision of the evidence supplied to the LLM.

## 5. Answer / Refusal Boundary
The system refuses to answer when:
1. Retrieval is weak (no clause scores above the threshold).
2. The retrieved passages discuss a related topic but do not contain a substantive answer.
3. The manual points to a broken cross-reference (a policy gap).

By placing the refusal logic upstream of the LLM in an explicit `EvidenceLayer`, we guarantee the LLM is never forced to guess.

## 6. Threshold Calibration
We calibrated the Cross-Encoder refusal threshold using a 10-question evaluation suite (`evaluation/evaluate.py`). Initially, a higher positive threshold was tested, but it resulted in false negatives (refusing correctly supported answers). We recalibrated the threshold to `-1.0` based on the logit output of the MS MARCO model. This threshold struck the ideal balance:
- It consistently filters out highly irrelevant clauses.
- It permits valid, paraphrased matches to pass to the LLM.
- **Trade-off:** We biased the threshold slightly toward refusal, recognizing that in public benefits, an unsupported confident answer is significantly worse than a transparent refusal.

## 7. Contradictions
When multiple highly-ranked clauses provide materially different instructions (e.g., §4.3.2 dictating 10 days, and §9.1.4 dictating 30 days), the system emits a `CONFLICT` state. We explicitly chose **not** to have the LLM resolve the conflict automatically. LLMs tend to average out differences or confidently pick one side based on internet pre-training. By surfacing both clauses, we empower the caseworker to escalate the ambiguity to a human policy authority.

## 8. Citation Integrity
Citations are inherently tied to the retrieval process. The LLM does not invent section numbers; it is only permitted to output `supporting_clause_ids` that exist in the payload provided by the retrieval engine. If the LLM generates an invalid or hallucinated clause ID, the system intercepts it and prevents the answer from being rendered. 

## 9. Key Trade-offs
- **Precision vs. Recall:** We optimized for precision over recall. If the system is uncertain, it refuses.
- **Speed vs. Retrieval Quality:** Reranking adds computational overhead per query, but the gain in evidence quality is strictly necessary for policy work.
- **Simplicity vs. Agentic Frameworks:** We avoided complex multi-agent reasoning loops in favor of a deterministic, three-state state machine (ANSWER, CONFLICT, REFUSE). This makes the system's behavior highly predictable.
