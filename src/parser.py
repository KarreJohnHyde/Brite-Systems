"""
Clause-level parser for the Calder County HSP policy manual.

Reads the Markdown policy manual and splits it into structured chunks,
preserving the legal hierarchy: Part -> Section -> Clause.

Each chunk is a complete policy clause with metadata for citation.
"""

import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


@dataclass
class PolicyClause:
    """A single policy clause with its full metadata for citation."""
    clause_id: str              # e.g. "4.3.2"
    text: str                   # The full text of the clause
    part: str                   # e.g. "Part 4 — Exclusions"
    section: str                # e.g. "4.3 Recipient obligations"
    line_start: int             # Line number in source file
    line_end: int               # Line number in source file
    sub_items: list[str] = field(default_factory=list)  # (a), (b), (c) items

    def full_reference(self) -> str:
        """Format a citation reference string."""
        return f"§{self.clause_id} — {self.section}, lines {self.line_start}-{self.line_end}"

    def short_reference(self) -> str:
        """Short citation for inline use."""
        return f"§{self.clause_id}"

    def to_dict(self) -> dict:
        return asdict(self)

    def display_text(self) -> str:
        """The clause text formatted for display, including sub-items."""
        result = self.text
        if self.sub_items:
            result += "\n" + "\n".join(self.sub_items)
        return result


def parse_policy_manual(filepath: str | Path) -> list[PolicyClause]:
    """
    Parse the Markdown policy manual into structured clause objects.
    
    The manual uses this structure:
        # Part X — Title          (Part heading)
        ## X.Y Title              (Section heading)
        **X.Y.Z** Text...        (Clause with optional sub-items)
        **X.Y.Z Title** — Text   (Clause with title in bold)
    
    Sub-items are lines starting with (a), (b), etc.
    
    Returns a list of PolicyClause objects ready for embedding.
    """
    filepath = Path(filepath)
    lines = filepath.read_text(encoding="utf-8").splitlines()

    clauses: list[PolicyClause] = []
    current_part: str = ""
    current_section: str = ""

    # Patterns
    part_pattern = re.compile(r"^#\s+Part\s+(\d+)\s*[—–-]\s*(.+)$")
    section_pattern = re.compile(r"^##\s+(\d+\.\d+)\s+(.+)$")
    # Match **X.Y.Z** or **X.Y.Z Title** at start of line
    clause_pattern = re.compile(r"^\*\*(\d+\.\d+\.\d+)(?:\s+([^*]+?))?\*\*\s*(.*)$")
    # Sub-items: (a), (b), etc. — possibly indented
    sub_item_pattern = re.compile(r"^\s*\(([a-z])\)\s+(.+)$")
    # Continuation line (not a heading, not a blank, not a new clause)
    # Table rows
    table_pattern = re.compile(r"^\|")

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Check for Part heading
        part_match = part_pattern.match(stripped)
        if part_match:
            current_part = f"Part {part_match.group(1)} — {part_match.group(2)}"
            i += 1
            continue

        # Check for Section heading
        section_match = section_pattern.match(stripped)
        if section_match:
            current_section = f"{section_match.group(1)} {section_match.group(2)}"
            i += 1
            continue

        # Check for Clause start
        clause_match = clause_pattern.match(stripped)
        if clause_match:
            clause_id = clause_match.group(1)
            clause_title = clause_match.group(2)  # May be None
            clause_text_start = clause_match.group(3)

            # Build the clause text
            text_parts = []
            if clause_title:
                text_parts.append(f"{clause_title.strip()} — {clause_text_start}" if clause_text_start else clause_title.strip())
            elif clause_text_start:
                text_parts.append(clause_text_start)

            line_start = i + 1  # 1-indexed
            sub_items = []

            # Consume continuation lines, sub-items, and tables
            i += 1
            while i < len(lines):
                next_line = lines[i].strip()

                # Handle blank lines: peek ahead to see if content continues
                if not next_line:
                    # Look ahead past blank lines
                    peek = i + 1
                    while peek < len(lines) and not lines[peek].strip():
                        peek += 1
                    
                    if peek >= len(lines):
                        i = peek
                        break
                    
                    peek_line = lines[peek].strip()
                    
                    # If the next non-blank line is a sub-item, continue
                    if sub_item_pattern.match(peek_line):
                        i += 1
                        continue
                    # If next non-blank is a table row, continue
                    if table_pattern.match(peek_line):
                        i += 1
                        continue
                    # Otherwise, this blank line ends the clause
                    i += 1
                    break

                # Stop at new Part, Section, or Clause
                if part_pattern.match(next_line):
                    break
                if section_pattern.match(next_line):
                    break
                if clause_pattern.match(next_line):
                    break
                # Stop at horizontal rules
                if next_line == "---":
                    break

                # Sub-items
                sub_match = sub_item_pattern.match(next_line)
                if sub_match:
                    sub_items.append(f"({sub_match.group(1)}) {sub_match.group(2)}")
                    i += 1
                    continue

                # Table rows (include in text)
                if table_pattern.match(next_line):
                    text_parts.append(next_line)
                    i += 1
                    continue

                # Regular continuation text
                text_parts.append(next_line)
                i += 1

            line_end = i  # 1-indexed (approximately)

            full_text = " ".join(text_parts) if not any(table_pattern.match(p) for p in text_parts) else "\n".join(text_parts)

            # Clean up the text
            full_text = re.sub(r"\s+", " ", full_text).strip() if "\n" not in full_text else full_text.strip()

            if full_text or sub_items:
                clause = PolicyClause(
                    clause_id=clause_id,
                    text=full_text,
                    part=current_part,
                    section=current_section,
                    line_start=line_start,
                    line_end=line_end,
                    sub_items=sub_items,
                )
                clauses.append(clause)
            continue

        i += 1

    return clauses


def get_embedding_text(clause: PolicyClause) -> str:
    """
    Create the text representation used for embedding.
    
    Includes the section context so the embedding captures 
    the semantic meaning within the policy hierarchy.
    """
    parts = []
    parts.append(f"§{clause.clause_id}")
    parts.append(f"{clause.part}")
    parts.append(f"Section: {clause.section}")
    parts.append(clause.text)
    if clause.sub_items:
        parts.extend(clause.sub_items)
    return " | ".join(parts)


def format_clause_for_context(clause: PolicyClause) -> str:
    """Format a clause for inclusion in the LLM context window."""
    lines = [f"[§{clause.clause_id} | {clause.section} | lines {clause.line_start}-{clause.line_end}]"]
    lines.append(clause.text)
    if clause.sub_items:
        for item in clause.sub_items:
            lines.append(f"  {item}")
    return "\n".join(lines)


if __name__ == "__main__":
    # Quick test: parse the manual and print stats
    manual_path = Path(__file__).parent.parent / "data" / "policy-manual.md"
    clauses = parse_policy_manual(manual_path)

    print(f"Parsed {len(clauses)} clauses from the policy manual.\n")

    # Show structure
    current_part = ""
    for c in clauses:
        if c.part != current_part:
            current_part = c.part
            print(f"\n{current_part}")
        print(f"  §{c.clause_id} — {c.section} ({len(c.text)} chars, {len(c.sub_items)} sub-items)")

    # Show a sample clause
    print("\n--- Sample clause (§4.3.2) ---")
    for c in clauses:
        if c.clause_id == "4.3.2":
            print(format_clause_for_context(c))
            break

    print("\n--- Sample clause (§9.1.4) ---")
    for c in clauses:
        if c.clause_id == "9.1.4":
            print(format_clause_for_context(c))
            break
