import pytest
import os
import tempfile
from src.parser import parse_policy_manual

def test_parse_policy_manual():
    # Create a dummy markdown file to test the clause parser
    dummy_markdown = """
# Part 1 — Introduction
## 1.1 Scope

**1.1.1 Purpose** This is the purpose of the manual.

**1.1.2** This applies to everyone.

# Part 2 — Eligibility
## 2.1 Income

**2.1.1** Income must be below $2000.
    """
    
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.md') as f:
        f.write(dummy_markdown)
        temp_path = f.name
        
    try:
        chunks = parse_policy_manual(temp_path)
        
        # We expect 3 distinct policy clauses to be parsed out
        assert len(chunks) == 3
        
        # Validate metadata extraction
        assert chunks[0].clause_id == "1.1.1"
        assert "This is the purpose of the manual." in chunks[0].text
        
        assert chunks[1].clause_id == "1.1.2"
        assert "This applies to everyone." in chunks[1].text
        
        assert chunks[2].clause_id == "2.1.1"
        assert "Income must be below $2000." in chunks[2].text
        
    finally:
        os.unlink(temp_path)
