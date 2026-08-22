"""
Citation extraction and validation.

Ensures that every cited clause in the LLM's answer actually appears
in the retrieved context. Prevents hallucinated citations.
"""

import re
from typing import Optional

from src.parser import PolicyClause
from src.retriever import RetrievalResult


def extract_citations_from_answer(answer_text: str) -> list[str]:
    """
    Extract clause references (§X.Y.Z) from LLM-generated answer text.
    
    Returns: list of clause IDs found in the answer.
    """
    pattern = re.compile(r"§(\d+\.\d+(?:\.\d+)?)")
    return pattern.findall(answer_text)


def validate_citations(
    cited_ids: list[str],
    provided_clauses: list[PolicyClause],
) -> tuple[list[str], list[str]]:
    """
    Validate that cited clause IDs were actually in the provided context.
    
    Returns:
        (valid_ids, invalid_ids) — invalid citations were hallucinated.
    """
    available_ids = {c.clause_id for c in provided_clauses}
    # Also include section-level references (e.g. §4.3 matches if §4.3.x exists)
    available_sections = {c.clause_id.rsplit(".", 1)[0] for c in provided_clauses}
    available_ids.update(available_sections)

    valid = []
    invalid = []
    for cid in cited_ids:
        if cid in available_ids:
            valid.append(cid)
        else:
            invalid.append(cid)

    return valid, invalid


def format_citations(
    results: list[RetrievalResult],
    cited_ids: Optional[list[str]] = None,
) -> list[dict]:
    """
    Format retrieval results into citation objects for the response.
    
    If cited_ids is provided, only include clauses that were actually cited.
    Otherwise, include all results.
    """
    citations = []
    seen = set()

    for r in results:
        cid = r.clause.clause_id
        
        # Skip if filtering by cited IDs and this one wasn't cited
        if cited_ids is not None:
            # Match exact clause or section-level reference
            section_id = cid.rsplit(".", 1)[0]
            if cid not in cited_ids and section_id not in cited_ids:
                continue

        if cid in seen:
            continue
        seen.add(cid)

        citations.append({
            "clause_id": cid,
            "section": r.clause.section,
            "part": r.clause.part,
            "lines": f"{r.clause.line_start}-{r.clause.line_end}",
            "text_preview": r.clause.display_text()[:150] + ("..." if len(r.clause.display_text()) > 150 else ""),
            "score": round(r.final_score, 3),
        })

    return citations
