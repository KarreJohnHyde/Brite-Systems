"""
Grounded answer generator using Gemini API.

Sends retrieved policy clauses to the LLM with a strict grounding prompt
that enforces citation discipline and prevents hallucination.
"""

import os
from typing import Optional

from google import genai

from src.parser import PolicyClause, format_clause_for_context
from src.retriever import RetrievalResult
from src.citations import extract_citations_from_answer, validate_citations, format_citations
from src.evidence import EvidenceAssessment, AnswerState


SYSTEM_PROMPT = """You are a county benefits policy assistant for the Calder County Household Support Program (HSP).

Answer the user's question using ONLY the policy excerpts supplied below. Follow these rules strictly:

1. Do NOT use outside knowledge. Every factual claim must come from the supplied excerpts.
2. Explain the answer in simple, plain language that a member of the public would understand.
3. Cite every factual claim using the clause number in the format §X.Y.Z (e.g. §4.3.2).
4. Never invent or assume the existence of a policy clause.
5. If the excerpts do not clearly answer the question, say so explicitly.
6. Never guess eligibility determinations, benefit amounts, or deadlines that are not stated in the excerpts.
7. If a clause refers to another section (e.g. "see §5.4"), and that section is not in the supplied excerpts, note that the cross-reference could not be verified.
8. Keep your answer concise — typically 2-4 sentences plus citations.

Format your response as:
ANSWER: [your plain-language answer with inline §X.Y.Z citations]

SOURCES: [list each clause you relied on, one per line, as "§X.Y.Z — Section title"]
"""


class AnswerGenerator:
    """Generates grounded answers using Gemini API."""

    def __init__(self, api_key: Optional[str] = None, model: str = "gemini-2.0-flash"):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Gemini API key required. Set GEMINI_API_KEY environment variable "
                "or pass api_key parameter."
            )
        self.client = genai.Client(api_key=self.api_key)
        self.model = model

    def generate_answer(
        self,
        question: str,
        assessment: EvidenceAssessment,
    ) -> dict:
        """
        Generate a grounded answer from the supporting evidence.
        
        Only called when assessment.state == ANSWER.
        
        Returns a dict with:
            - answer: The plain-language answer
            - state: "answer"
            - citations: list of citation objects
            - raw_llm_response: The full LLM output
        """
        # Build context from supporting results
        context_parts = []
        for r in assessment.supporting_results:
            context_parts.append(format_clause_for_context(r.clause))

        context = "\n\n".join(context_parts)

        # Build the prompt
        user_prompt = f"""POLICY EXCERPTS:

{context}

QUESTION: {question}"""

        # Call the LLM
        response = self.client.models.generate_content(
            model=self.model,
            contents=user_prompt,
            config={
                "system_instruction": SYSTEM_PROMPT,
                "temperature": 0.1,  # Low temperature for factual accuracy
                "max_output_tokens": 1024,
            },
        )

        raw_response = response.text

        # Extract and validate citations
        provided_clauses = [r.clause for r in assessment.supporting_results]
        cited_ids = extract_citations_from_answer(raw_response)
        valid_ids, hallucinated_ids = validate_citations(cited_ids, provided_clauses)

        # Format citations for display
        citations = format_citations(assessment.supporting_results, cited_ids=valid_ids)

        # Build the response
        result = {
            "answer": raw_response,
            "state": "answer",
            "citations": citations,
            "raw_llm_response": raw_response,
            "top_score": assessment.top_score,
        }

        # Warn if any citations were hallucinated
        if hallucinated_ids:
            result["warnings"] = [
                f"The LLM cited §{cid} which was not in the provided context. "
                f"This citation could not be verified."
                for cid in hallucinated_ids
            ]

        return result

    def check_conflict(
        self,
        question: str,
        clause_a: PolicyClause,
        clause_b: PolicyClause,
    ) -> bool:
        """
        Use the LLM to check if two clauses contradict each other
        in the context of the user's question.
        
        Returns True if a contradiction is detected.
        """
        prompt = f"""Given the following two policy clauses and a user question, determine if the clauses contradict each other on the matter raised by the question.

CLAUSE A (§{clause_a.clause_id}):
{clause_a.display_text()}

CLAUSE B (§{clause_b.clause_id}):
{clause_b.display_text()}

QUESTION: {question}

Do these two clauses provide contradictory guidance on this question? Answer with exactly "YES" or "NO" followed by a brief explanation."""

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config={
                    "temperature": 0.0,
                    "max_output_tokens": 200,
                },
            )
            return response.text.strip().upper().startswith("YES")
        except Exception:
            return False
