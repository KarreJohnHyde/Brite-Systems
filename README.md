# The Grounded Answer

Citation-Aware RAG Assistant for Government Policy Manuals

A three-state evidence engine that answers questions from the Calder County Household Support Program policy manual. Every answer is grounded in specific policy clauses, contradictions are surfaced rather than hidden, and the system refuses to answer when the manual doesn't cover the question.

## Quick Start

### Prerequisites

- Python 3.10+
- A Gemini API key (free tier: [aistudio.google.com](https://aistudio.google.com))

### Setup

```bash
# Clone the repository
git clone <repo-url>
cd grounded-answer

# Create a virtual environment (recommended)
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/Mac

# Install dependencies
pip install -r requirements.txt

# Set your Gemini API key
set GEMINI_API_KEY=your-key-here          # Windows CMD
$env:GEMINI_API_KEY="your-key-here"       # Windows PowerShell
# export GEMINI_API_KEY=your-key-here     # Linux/Mac
```

### Build the Index

```bash
python main.py ingest
```

This parses the policy manual into 148 clause-level chunks, generates embeddings, and builds a FAISS index. Takes ~5 seconds.

### Web UI (Streamlit)

```bash
streamlit run app.py
```

This will start a local web server and open an interactive chat interface in your browser.

### Ask a Question (CLI)

```bash
python main.py ask "What is the resource limit for household eligibility?"
```

### Interactive Mode

```bash
python main.py interactive
```

### View a Specific Clause

```bash
python main.py show-clause 4.3.2
```

### Run the Evaluation Suite

```bash
python main.py evaluate
```

## Architecture

```text
User Question
      │
      ▼
Sentence-Transformer Embedding
      │
      ▼
FAISS Top-15 → Cross-Encoder Rerank → Top-5
      │
      ▼
Evidence Assessment
      │
      ├── High confidence, consistent → ANSWER (grounded + cited)
      ├── High confidence, conflict   → CONFLICT (surface both clauses)
      └── Low confidence / no match   → REFUSE (say "I don't know" + who to ask)
```

### Three Output States

| State | When | What the user sees |
| :-- | :-- | :-- |
| **ANSWER** | Relevant clauses found, no conflict | Plain-language answer with §X.Y.Z citations |
| **CONFLICT** | Retrieved clauses contradict each other | Both clauses shown, escalation recommended |
| **REFUSE** | No relevant clauses or topic not covered | "I don't know" + contact information |

### Technology Stack

| Component | Technology |
| :-- | :-- |
| Embeddings | sentence-transformers/all-MiniLM-L6-v2 |
| Vector DB | FAISS (IndexFlatIP, cosine similarity) |
| Reranker | cross-encoder/ms-marco-MiniLM-L-6-v2 |
| LLM | Google Gemini 2.0 Flash |
| Language | Python 3.14 |

## Project Structure

```text
grounded-answer/
├── main.py                    # CLI entry point
├── requirements.txt           # Python dependencies
├── README.md                  # This file
├── DECISIONS.md               # Design decisions and rationale
├── AI-USAGE.md                # AI usage disclosure
│
├── data/
│   ├── policy-manual.md       # The corpus (Calder County HSP manual)
│   ├── contacts.json          # Contact info for refusal responses
│   └── faiss_index/           # Generated FAISS index (after ingest)
│
├── src/
│   ├── parser.py              # Clause-level Markdown parser
│   ├── embeddings.py          # Sentence-transformer encoding
│   ├── vector_store.py        # FAISS index management
│   ├── retriever.py           # Two-stage retrieval (embedding + reranker)
│   ├── evidence.py            # Evidence assessment (ANSWER/CONFLICT/REFUSE)
│   ├── contradiction.py       # Conflict detection and response
│   ├── refusal.py             # "I don't know" response generation
│   ├── generator.py           # LLM-powered grounded answer generation
│   └── citations.py           # Citation extraction and validation
│
└── evaluation/
    ├── questions.json          # 10-question test set
    ├── evaluate.py             # Automated evaluation runner
    └── results.md              # Generated evaluation report
```

## Evaluation

The test set includes 10 questions designed to probe the system's failure modes:

- **4 straightforward lookups** (expected: ANSWER with correct clause)
- **2 contradiction questions** targeting §4.3.2 vs §9.1.4 (expected: CONFLICT)
- **2 gap questions** — one where the manual appears to cover the topic but doesn't (expected: REFUSE)
- **2 absent topics** not covered at all (expected: REFUSE)

Run with: `python main.py evaluate`

Results are reported honestly — a test set where everything passes means the questions were too easy.
