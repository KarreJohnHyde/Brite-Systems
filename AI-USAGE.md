# AI Usage Disclosure

In accordance with the hackathon policy, this document outlines how AI tools were used in the development of **The Grounded Answer** project.

## 1. Code Generation
An autonomous AI coding agent (Google Antigravity) was used extensively to generate the foundational boilerplate and core logic for the repository. The agent was responsible for:
- Writing the `ClauseParser` logic to correctly chunk Markdown documents by section and clause.
- Setting up the FAISS vector store and `sentence-transformers` embedding pipelines.
- Implementing the three-state evidence engine (`evidence.py`) based on human-provided rules.
- Scaffolding the `Streamlit` user interface and CLI commands (`main.py`).

## 2. Architecture Assistance
The RAG architecture, explicitly the decision to separate the retrieval layer from the evidence analysis layer (refusal mechanism), was co-designed with the AI. The human developer provided the strict product constraints (refusal requirements, contradiction handling, no hallucinations), and the AI proposed the modular `src/` directory structure to accommodate these requirements cleanly.

## 3. Evaluation & Testing
The AI was used to parse the initial policy manual and extract edge cases to construct the 10-question evaluation suite (`evaluation/questions.json`). The AI drafted the evaluation logic that grades the system's responses against expected decisions and expected citations.

## 4. Human Oversight
While the AI wrote the majority of the code, human oversight was applied to ensure the system strictly adhered to the public policy constraints:
- The `RELEVANCE_THRESHOLD` for the Cross-Encoder was manually evaluated and tweaked to `-1.0` to balance precision and refusal safety.
- The `EvidenceLayer` logic was repeatedly tested by the human to ensure it correctly trapped contradictions without the LLM silently resolving them.
- Final code review and architectural validation were performed manually.
