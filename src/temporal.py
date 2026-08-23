"""Deterministic, source-verified applicability for dated policy questions.

The amendment is legal source text, not a replacement manual.  This module
keeps both source documents immutable, selects the applicable rule from the
question's dates, and cites every raw provision used to reach that selection.
It intentionally runs before statistical retrieval so obsolete and amended
figures are never treated as an unresolved semantic-retrieval clash.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.citations import CitationValidator
from src.models import (
    ConflictFinding,
    Decision,
    DecisionTrace,
    EvidenceAssessment,
    EvidenceLevel,
    PolicyAnswer,
    PolicyChunk,
    RetrievedClause,
    SupportType,
)
from src.refusal import load_contacts


class TemporalBasis(str, Enum):
    DETERMINATION_DATE = "determination_date"
    CHANGE_DATE = "change_date"
    CLAIM_PERIOD = "claim_period"


class TimelineRule(BaseModel):
    """A reviewed machine-readable description of one amendment operation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    topic: str
    operation: Literal["substitute", "replace_table", "insert"]
    target_clause_ids: list[str] = Field(min_length=1)
    amendment_paragraph_id: str
    transition_paragraph_id: str
    temporal_basis: TemporalBasis
    before: dict[str, int | bool]
    after: dict[str, int | bool]
    expected_replacement_count: int | None = Field(default=None, ge=1)
    source_verified: bool


class SpanningPeriodRule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    temporal_basis: Literal["claim_period"]
    transition_paragraph_id: str
    apportionment_clause_id: str
    source_verified: bool


class PolicyTimeline(BaseModel):
    """Typed companion metadata; every locator is checked against raw sources."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1]
    source_verified: bool
    manual_document_id: str
    amendment_document_id: str
    amendment_number: str
    effective_date: date
    issued_date: date
    rules: list[TimelineRule] = Field(min_length=1)
    spanning_period: SpanningPeriodRule

    @model_validator(mode="after")
    def validate_review_flags_and_unique_rules(self) -> "PolicyTimeline":
        if not self.source_verified:
            raise ValueError("Policy timeline must be explicitly source verified")
        if any(not rule.source_verified for rule in self.rules):
            raise ValueError("Every timeline rule must be explicitly source verified")
        if not self.spanning_period.source_verified:
            raise ValueError("The spanning-period rule must be explicitly source verified")
        identifiers = [rule.id for rule in self.rules]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("Policy timeline contains duplicate rule IDs")
        return self


@dataclass(frozen=True)
class DateMention:
    value: date
    start: int
    end: int
    precision: Literal["day", "month"]
    relation: Literal["before", "after", "on"] | None = None


@dataclass(frozen=True)
class TemporalContext:
    mentions: tuple[DateMention, ...]
    determination_date: date | None = None
    change_date: date | None = None
    awareness_date: date | None = None
    period_start: date | None = None
    period_end: date | None = None
    ambiguous_numeric_date: bool = False


MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}
MONTH_PATTERN = "|".join(sorted(MONTHS, key=len, reverse=True))
ISO_DATE_RE = re.compile(r"\b(?P<year>20\d{2})-(?P<month>\d{1,2})-(?P<day>\d{1,2})\b")
DAY_MONTH_RE = re.compile(
    rf"\b(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s+"
    rf"(?P<month>{MONTH_PATTERN})\.?[,]?\s+(?P<year>20\d{{2}})\b",
    re.IGNORECASE,
)
MONTH_DAY_RE = re.compile(
    rf"\b(?P<month>{MONTH_PATTERN})\.?\s+"
    rf"(?P<day>\d{{1,2}})(?:st|nd|rd|th)?[,]?\s+(?P<year>20\d{{2}})\b",
    re.IGNORECASE,
)
MONTH_YEAR_RE = re.compile(
    rf"\b(?P<month>{MONTH_PATTERN})\.?\s+(?P<year>20\d{{2}})\b",
    re.IGNORECASE,
)
NUMERIC_DATE_RE = re.compile(r"\b(?P<first>\d{1,2})/(?P<second>\d{1,2})/(?P<year>20\d{2})\b")

DETERMINATION_CUES = re.compile(
    r"\b(determination|determined|decision(?:\s+was)?\s+made|claim\s+(?:date|dated))\b",
    re.IGNORECASE,
)
CHANGE_CUES = re.compile(
    r"\b(change\s+(?:occurred|happened|took place|date|dated)|"
    r"circumstances\s+changed|changed\s+on)\b",
    re.IGNORECASE,
)
AWARENESS_CUES = re.compile(
    r"\b(became aware|was aware|learned|found out|knew|knowledge)\b",
    re.IGNORECASE,
)
PERIOD_CUES = re.compile(
    r"\b(period|from|through|until|between|spanning|spans|crosses|covering)\b",
    re.IGNORECASE,
)

EARNINGS_TOPIC_RE = re.compile(
    r"\b(earnings?\s+disregard|income\s+disregards?|standard\s+disregards?|"
    r"countable\s+earnings?|earnings?\s+(?:is|are|was|were)?\s*counted|"
    r"first\s+\$?\d[\d,]*\s+(?:of\s+)?(?:monthly\s+)?earnings?)\b",
    re.IGNORECASE,
)
THRESHOLD_TOPIC_RE = re.compile(
    r"\b(income\s+threshold|monthly\s+threshold|income\s+limit|"
    r"threshold\s+for\s+(?:a\s+)?household|household\s+income\s+limit)\b",
    re.IGNORECASE,
)
REPORTING_TOPIC_RE = re.compile(
    r"\b(report(?:ing|ed)?\b.{0,35}\bchange|change\b.{0,35}\breport|"
    r"failure\s+to\s+report|reporting\s+(?:period|deadline))\b",
    re.IGNORECASE,
)
SANCTION_RATE_RE = re.compile(
    r"\b(sanction\b.{0,30}\b(?:rate|percent|percentage|amount|how much|reduction)|"
    r"(?:percent|percentage)\b.{0,20}\bsanction)\b",
    re.IGNORECASE,
)
SANCTION_EFFECT_RE = re.compile(
    r"\b(sanction\b.{0,40}\b(?:ineligible|eligibility|excluded|effect|consequence|reduce)|"
    r"(?:ineligible|excluded|reduce)\b.{0,30}\bsanction|"
    r"miss(?:ed|ing)?\b.{0,30}\binterview\b.{0,30}\bsanction)\b",
    re.IGNORECASE,
)
INCREASE_PROTECTION_RE = re.compile(
    r"\b(?:failure\s+to\s+report|late\s+report|sanction)\b.{0,80}"
    r"\b(?:increase|increased|higher|raise)\b.{0,30}\baward\b|"
    r"\bchange\b.{0,50}\b(?:increase|increased|higher|raise)\b.{0,30}"
    r"\baward\b.{0,50}\bsanction\b",
    re.IGNORECASE,
)
SPANNING_TOPIC_RE = re.compile(
    r"\b(spanning|spans|crosses|straddles|before\s+and\s+after)\b.{0,50}"
    r"\b(?:1\s+march|march\s+1|effective\s+date|2026)\b",
    re.IGNORECASE,
)


def _relation(question: str, start: int) -> Literal["before", "after", "on"] | None:
    prefix = question[max(0, start - 18) : start].lower()
    match = re.search(r"\b(before|after|on|from)\s*$", prefix)
    if not match:
        return None
    return "on" if match.group(1) == "from" else match.group(1)  # type: ignore[return-value]


def _make_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _date_mentions(question: str) -> tuple[tuple[DateMention, ...], bool]:
    """Extract unambiguous ISO/text dates while flagging ambiguous slash dates."""

    mentions: list[DateMention] = []
    occupied: list[tuple[int, int]] = []

    def available(start: int, end: int) -> bool:
        return all(end <= left or start >= right for left, right in occupied)

    def append(match: re.Match[str], value: date, precision: Literal["day", "month"]) -> None:
        if available(match.start(), match.end()):
            mentions.append(
                DateMention(
                    value=value,
                    start=match.start(),
                    end=match.end(),
                    precision=precision,
                    relation=_relation(question, match.start()),
                )
            )
            occupied.append((match.start(), match.end()))

    for pattern, order in (
        (ISO_DATE_RE, "iso"),
        (DAY_MONTH_RE, "day-month"),
        (MONTH_DAY_RE, "month-day"),
    ):
        for match in pattern.finditer(question):
            if order == "iso":
                value = _make_date(
                    int(match.group("year")),
                    int(match.group("month")),
                    int(match.group("day")),
                )
            else:
                value = _make_date(
                    int(match.group("year")),
                    MONTHS[match.group("month").lower().rstrip(".")],
                    int(match.group("day")),
                )
            if value is not None:
                append(match, value, "day")

    for match in MONTH_YEAR_RE.finditer(question):
        value = _make_date(
            int(match.group("year")),
            MONTHS[match.group("month").lower().rstrip(".")],
            1,
        )
        if value is not None:
            append(match, value, "month")

    ambiguous = False
    for match in NUMERIC_DATE_RE.finditer(question):
        if not available(match.start(), match.end()):
            continue
        first = int(match.group("first"))
        second = int(match.group("second"))
        year = int(match.group("year"))
        if first <= 12 and second <= 12:
            ambiguous = True
            continue
        if first > 12:
            value = _make_date(year, second, first)
        else:
            value = _make_date(year, first, second)
        if value is not None:
            append(match, value, "day")

    return tuple(sorted(mentions, key=lambda item: item.start)), ambiguous


def _nearby_mentions(
    question: str,
    mentions: tuple[DateMention, ...],
    cue: re.Pattern[str],
    *,
    radius: int = 55,
) -> list[DateMention]:
    matches: list[DateMention] = []
    for mention in mentions:
        window = question[max(0, mention.start - radius) : min(len(question), mention.end + radius)]
        if cue.search(window):
            matches.append(mention)
    return matches


def _single(items: list[DateMention]) -> date | None:
    unique = {item.value for item in items}
    return next(iter(unique)) if len(unique) == 1 else None


def extract_temporal_context(question: str) -> TemporalContext:
    mentions, ambiguous = _date_mentions(question)
    determination = _single(_nearby_mentions(question, mentions, DETERMINATION_CUES))
    change = _single(_nearby_mentions(question, mentions, CHANGE_CUES))
    awareness = _single(_nearby_mentions(question, mentions, AWARENESS_CUES, radius=40))

    # A single dated policy question is commonly expressed as "for a claim dated
    # ...".  For changed reporting rules it is used as the occurrence date only
    # when no competing date role was expressed.
    if len(mentions) == 1:
        only = mentions[0].value
        if determination is None and DETERMINATION_CUES.search(question):
            determination = only
        if change is None and CHANGE_CUES.search(question):
            change = only

    period_mentions = _nearby_mentions(question, mentions, PERIOD_CUES, radius=28)
    period_values = sorted({item.value for item in period_mentions})
    period_start = period_values[0] if len(period_values) >= 2 else None
    period_end = period_values[-1] if len(period_values) >= 2 else None

    return TemporalContext(
        mentions=mentions,
        determination_date=determination,
        change_date=change,
        awareness_date=awareness,
        period_start=period_start,
        period_end=period_end,
        ambiguous_numeric_date=ambiguous,
    )


def _effective_reference(mention: DateMention, effective: date) -> date:
    if mention.relation == "before" and mention.value == effective:
        return effective - timedelta(days=1)
    return mention.value


def _format_date(value: date) -> str:
    return f"{value.day} {value.strftime('%B %Y')}"


def _money(value: int | float) -> str:
    if isinstance(value, float) and not value.is_integer():
        return f"${value:,.2f}"
    return f"${int(value):,}"


class TemporalPolicyResolver:
    """Answer only amendment-sensitive questions whose applicability is known."""

    def __init__(
        self,
        chunks: list[PolicyChunk],
        *,
        timeline_path: str | Path,
        contacts_path: str | Path | None = None,
    ) -> None:
        self.chunks = list(chunks)
        self.contacts = load_contacts(contacts_path)
        try:
            payload = json.loads(Path(timeline_path).read_text(encoding="utf-8"))
            self.timeline = PolicyTimeline.model_validate(payload)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"Policy timeline is unreadable or invalid: {timeline_path}") from exc

        self.manual = {
            chunk.clause_id: chunk
            for chunk in self.chunks
            if chunk.document_id == self.timeline.manual_document_id and chunk.clause_id
        }
        self.amendment_chunks = [
            chunk
            for chunk in self.chunks
            if chunk.document_id == self.timeline.amendment_document_id
        ]
        self.amendment = {
            paragraph: chunk
            for chunk in self.amendment_chunks
            if (paragraph := self._amendment_paragraph(chunk)) is not None
        }
        self.inserted = {
            inserted_id: chunk
            for chunk in self.amendment_chunks
            for inserted_id in getattr(chunk, "inserts_clause_ids", [])
        }
        self.enabled = bool(self.amendment_chunks)
        if self.enabled:
            self._validate_against_sources()

    @staticmethod
    def _amendment_paragraph(chunk: PolicyChunk) -> str | None:
        value = getattr(chunk, "amendment_paragraph_id", None)
        if value:
            return str(value)
        locator = str(getattr(chunk, "source_locator", "") or "")
        if locator.startswith("amendment-") and ":" in locator:
            return locator.split(":")[-1]
        label = str(getattr(chunk, "source_locator_label", "") or "")
        match = re.search(r"¶\s*(\d+\.\d+)\b", label)
        if match:
            return match.group(1)
        match = re.search(r"¶\s*(\d+\.\d+)\b", locator)
        return match.group(1) if match else None

    def _validate_against_sources(self) -> None:
        effective_dates = {chunk.effective_date for chunk in self.amendment_chunks}
        if self.timeline.effective_date.isoformat() not in effective_dates:
            raise ValueError("Policy timeline effective date does not match the amendment source")

        for rule in self.timeline.rules:
            if rule.amendment_paragraph_id not in self.amendment:
                raise ValueError(
                    f"Timeline rule {rule.id!r} cites unknown amendment paragraph "
                    f"{rule.amendment_paragraph_id}"
                )
            if rule.transition_paragraph_id not in self.amendment:
                raise ValueError(
                    f"Timeline rule {rule.id!r} cites unknown transition paragraph "
                    f"{rule.transition_paragraph_id}"
                )
            for clause_id in rule.target_clause_ids:
                if clause_id not in self.manual and clause_id not in self.inserted:
                    raise ValueError(
                        f"Timeline rule {rule.id!r} cites unknown target clause §{clause_id}"
                    )
            amendment_text = self.amendment[rule.amendment_paragraph_id].text
            if not any(clause_id in amendment_text for clause_id in rule.target_clause_ids):
                raise ValueError(
                    f"Amendment paragraph {rule.amendment_paragraph_id} does not name "
                    f"the target for timeline rule {rule.id!r}"
                )

        reporting = self._rule("reporting-deadline")
        reporting_text = self.manual["4.3.2"].text.lower()
        if reporting_text.count("10 calendar days") != reporting.expected_replacement_count:
            raise ValueError("The reviewed §4.3.2 replacement count no longer matches the source")

        required = (
            self.timeline.spanning_period.transition_paragraph_id,
            self.timeline.spanning_period.apportionment_clause_id,
        )
        if required[0] not in self.amendment or required[1] not in self.manual:
            raise ValueError("The reviewed spanning-period source locators are unavailable")

    def _rule(self, identifier: str) -> TimelineRule:
        return next(rule for rule in self.timeline.rules if rule.id == identifier)

    def _topic(self, question: str) -> str | None:
        lowered = question.lower()
        if SPANNING_TOPIC_RE.search(question):
            return "spanning_period"
        if INCREASE_PROTECTION_RE.search(question) or "10.5.3a" in lowered:
            return "increased_award_reporting_sanction"
        if REPORTING_TOPIC_RE.search(question) or "4.3.2" in lowered or "9.1.4" in lowered:
            return "reporting_deadline"
        if EARNINGS_TOPIC_RE.search(question) or "6.4.1" in lowered:
            return "earnings_disregard"
        if THRESHOLD_TOPIC_RE.search(question) or "6.6.1" in lowered:
            return "income_threshold"
        if SANCTION_EFFECT_RE.search(question):
            return "sanction_effect"
        if SANCTION_RATE_RE.search(question) or "10.5.2" in lowered:
            return "sanction_rate"
        return None

    def resolve(
        self,
        question: str,
        *,
        include_trace: bool = False,
    ) -> PolicyAnswer | None:
        if not self.enabled:
            return None
        topic = self._topic(question)
        if topic is None:
            return None

        context = extract_temporal_context(question)
        if topic == "spanning_period" or self._crosses_effective_date(context):
            return self._spanning_answer(question, context, include_trace=include_trace)
        if topic == "earnings_disregard":
            return self._earnings_answer(question, context, include_trace=include_trace)
        if topic == "income_threshold":
            return self._threshold_answer(question, context, include_trace=include_trace)
        if topic == "reporting_deadline":
            return self._reporting_answer(question, context, include_trace=include_trace)
        if topic == "increased_award_reporting_sanction":
            return self._increase_protection_answer(
                question, context, include_trace=include_trace
            )
        if topic == "sanction_effect":
            return self._sanction_effect_answer(
                question, context, include_trace=include_trace
            )
        if topic == "sanction_rate":
            return self._sanction_rate_answer(
                question, context, include_trace=include_trace
            )
        return None

    def _crosses_effective_date(self, context: TemporalContext) -> bool:
        if context.period_start is None or context.period_end is None:
            return False
        return context.period_start < self.timeline.effective_date <= context.period_end

    def _date_for_basis(
        self,
        question: str,
        context: TemporalContext,
        basis: TemporalBasis,
    ) -> date | None:
        if context.ambiguous_numeric_date:
            return None
        selected = (
            context.determination_date
            if basis == TemporalBasis.DETERMINATION_DATE
            else context.change_date
        )
        if selected is not None:
            return selected
        if len(context.mentions) == 1:
            mention = context.mentions[0]
            # Day-2 asks are commonly phrased as "for February 2026" or "as of
            # April 2026".  A sole unambiguous date is accepted as the date the
            # question is about, while the response names the legal date basis.
            return _effective_reference(mention, self.timeline.effective_date)
        if re.search(r"\b(today|currently|current\s+rule|as\s+of\s+now)\b", question, re.IGNORECASE):
            return date.today()
        return None

    def _raw_sources(
        self,
        *,
        manual_ids: tuple[str, ...] = (),
        amendment_ids: tuple[str, ...] = (),
        inserted_ids: tuple[str, ...] = (),
    ) -> list[PolicyChunk]:
        ordered: list[PolicyChunk] = []
        for clause_id in manual_ids:
            if clause_id in self.manual:
                ordered.append(self.manual[clause_id])
        for clause_id in inserted_ids:
            if clause_id in self.inserted:
                ordered.append(self.inserted[clause_id])
        for paragraph_id in amendment_ids:
            if paragraph_id in self.amendment:
                ordered.append(self.amendment[paragraph_id])
        seen: set[str] = set()
        return [
            chunk
            for chunk in ordered
            if not (chunk.chunk_id in seen or seen.add(chunk.chunk_id))
        ]

    @staticmethod
    def _retrieved(chunks: list[PolicyChunk]) -> list[RetrievedClause]:
        return [
            RetrievedClause(
                chunk=chunk,
                lexical_score=1.0,
                fused_score=1.0,
                lexical_rank=index + 1,
            )
            for index, chunk in enumerate(chunks)
        ]

    def _answer(
        self,
        *,
        question: str,
        decision: Decision,
        answer: str,
        reason: str,
        chunks: list[PolicyChunk],
        next_step: str | None = None,
        include_trace: bool = False,
        conflicts: list[ConflictFinding] | None = None,
    ) -> PolicyAnswer:
        retrieved = self._retrieved(chunks)
        support = SupportType.CONTRADICTORY if decision == Decision.CONFLICT else (
            SupportType.PARTIAL if decision == Decision.REFUSE else SupportType.DIRECT
        )
        evidence = [
            EvidenceAssessment(
                chunk_id=item.chunk.chunk_id,
                support_type=support,
                explanation="Selected by the source-verified temporal applicability rule.",
                score=1.0 if decision != Decision.REFUSE else 0.5,
                topic_coverage=1.0,
                answer_alignment=1.0 if decision != Decision.REFUSE else 0.5,
            )
            for item in retrieved
        ]
        trace = DecisionTrace(
            question=question,
            retrieved=retrieved,
            evidence=evidence,
            conflicts=conflicts or [],
            decision=decision,
            decision_reason=reason,
            refusal_threshold=1.0,
        )
        citations = CitationValidator(retrieved).build(
            [item.chunk.chunk_id for item in retrieved],
            require_any=False,
        )
        return PolicyAnswer(
            decision=decision,
            answer=answer,
            citations=citations,
            evidence_level=EvidenceLevel.LOW if decision != Decision.ANSWER else EvidenceLevel.HIGH,
            reason=reason,
            next_step=next_step,
            trace=trace if include_trace else None,
        )

    def _missing_date(
        self,
        *,
        question: str,
        basis: TemporalBasis,
        chunks: list[PolicyChunk],
        include_trace: bool,
    ) -> PolicyAnswer:
        names = {
            TemporalBasis.DETERMINATION_DATE: "the date the determination was made",
            TemporalBasis.CHANGE_DATE: "the date the change of circumstances occurred",
            TemporalBasis.CLAIM_PERIOD: "the start and end dates of the claim period",
        }
        needed = names[basis]
        return self._answer(
            question=question,
            decision=Decision.REFUSE,
            answer=(
                "I don't know which version of the rule applies from the question alone. "
                f"Please provide {needed}; the amendment makes that date legally controlling."
            ),
            reason=(
                "The question concerns a rule changed on 1 March 2026 but does not "
                f"unambiguously provide {needed}."
            ),
            chunks=chunks,
            next_step=(
                f"Provide {needed}. If that date is unavailable or disputed, ask a "
                "Department caseworker or supervisor before acting."
            ),
            include_trace=include_trace,
        )

    def _earnings_answer(
        self,
        question: str,
        context: TemporalContext,
        *,
        include_trace: bool,
    ) -> PolicyAnswer:
        rule = self._rule("earnings-disregard")
        sources = self._raw_sources(
            manual_ids=("6.4.1", "6.4.2", "1.2.3"),
            amendment_ids=("1.1", "5.1"),
        )
        relevant_date = self._date_for_basis(
            question, context, TemporalBasis.DETERMINATION_DATE
        )
        if relevant_date is None:
            return self._missing_date(
                question=question,
                basis=TemporalBasis.DETERMINATION_DATE,
                chunks=sources,
                include_trace=include_trace,
            )
        amended = relevant_date >= self.timeline.effective_date
        amount = int((rule.after if amended else rule.before)["monthly_amount"])
        timing = (
            "on or after 1 March 2026"
            if amended
            else "before 1 March 2026"
        )

        broad_list = bool(
            re.search(
                r"\b(which|what|list|standard)\b.{0,25}\bdisregards?\b|"
                r"\bper\s+(?:earner|household)\b",
                question,
                re.IGNORECASE,
            )
        )
        currency_values = [
            float(raw.replace(",", ""))
            for raw in re.findall(r"\$([\d,]+(?:\.\d{1,2})?)", question)
        ]
        earnings_value = next(
            (value for value in currency_values if value not in {120.0, 175.0, 200.0}),
            None,
        )
        if earnings_value is not None and re.search(
            r"\b(countable|counted|after\s+the\s+disregard)\b", question, re.IGNORECASE
        ):
            countable = max(0.0, earnings_value - amount)
            answer = (
                f"For a determination made {_format_date(relevant_date)}, the first "
                f"{_money(amount)} of monthly household earnings is disregarded. "
                f"On {_money(earnings_value)} of monthly earnings, that leaves "
                f"{_money(countable)} countable before any other applicable disregard. "
                "The earnings disregard applies once per household, not once per earner."
            )
        elif broad_list:
            answer = (
                f"For a determination made {_format_date(relevant_date)}, the standard "
                f"disregards are: the first {_money(amount)} of monthly household earnings; "
                "child support for a dependent child; a qualifying training allowance; "
                "disability payments intended for additional disability costs; irregular "
                "charitable payments not intended for ordinary living costs; care allowance "
                "payments up to $200 per month; and a dependent child's income. The earnings "
                "disregard applies once per household, not once per earner."
            )
        else:
            answer = (
                f"For a determination made {_format_date(relevant_date)}, the earnings "
                f"disregard is {_money(amount)} per month, applied once per household rather "
                f"than once per earner. This is the rule for determinations made {timing}."
            )
        return self._answer(
            question=question,
            decision=Decision.ANSWER,
            answer=answer,
            reason=(
                f"The amendment uses the determination date; {_format_date(relevant_date)} "
                f"falls {timing}."
            ),
            chunks=sources,
            include_trace=include_trace,
        )

    @staticmethod
    def _household_size(question: str) -> int | None:
        patterns = (
            r"\bhousehold\s+(?:of|size(?:\s+of)?)\s+(\d{1,2})\b",
            r"\b(\d{1,2})[- ](?:person|member)\s+household\b",
        )
        for pattern in patterns:
            if match := re.search(pattern, question, re.IGNORECASE):
                value = int(match.group(1))
                return value if value >= 1 else None
        words = {
            "one": 1,
            "two": 2,
            "three": 3,
            "four": 4,
            "five": 5,
            "six": 6,
            "seven": 7,
            "eight": 8,
            "nine": 9,
            "ten": 10,
        }
        match = re.search(
            r"\bhousehold\s+of\s+(one|two|three|four|five|six|seven|eight|nine|ten)\b",
            question,
            re.IGNORECASE,
        )
        return words[match.group(1).lower()] if match else None

    def _threshold_answer(
        self,
        question: str,
        context: TemporalContext,
        *,
        include_trace: bool,
    ) -> PolicyAnswer:
        rule = self._rule("income-thresholds")
        sources = self._raw_sources(
            manual_ids=("6.6.1", "1.2.3", "1.3.3"),
            amendment_ids=("3.1", "5.1"),
        )
        relevant_date = self._date_for_basis(
            question, context, TemporalBasis.DETERMINATION_DATE
        )
        if relevant_date is None:
            return self._missing_date(
                question=question,
                basis=TemporalBasis.DETERMINATION_DATE,
                chunks=sources,
                include_trace=include_trace,
            )
        amended = relevant_date >= self.timeline.effective_date
        table = rule.after if amended else rule.before
        size = self._household_size(question)
        if size is not None:
            amount = (
                int(table[str(size)])
                if size <= 5
                else int(table["5"]) + (size - 5) * int(table["additional"])
            )
            answer = (
                f"For a determination made {_format_date(relevant_date)}, the monthly "
                f"countable-income threshold for a household of {size} is {_money(amount)}. "
                "The threshold rule makes a household ineligible only when countable income "
                "exceeds that amount."
            )
        else:
            answer = (
                f"For a determination made {_format_date(relevant_date)}, the monthly "
                "countable-income thresholds are "
                f"1 person {_money(int(table['1']))}; 2 people {_money(int(table['2']))}; "
                f"3 people {_money(int(table['3']))}; 4 people {_money(int(table['4']))}; "
                f"5 people {_money(int(table['5']))}; plus "
                f"{_money(int(table['additional']))} for each additional member."
            )
        return self._answer(
            question=question,
            decision=Decision.ANSWER,
            answer=answer,
            reason=(
                "The amendment makes the threshold table depend on the determination "
                f"date; the supplied date is {_format_date(relevant_date)}."
            ),
            chunks=sources,
            include_trace=include_trace,
        )

    def _reporting_answer(
        self,
        question: str,
        context: TemporalContext,
        *,
        include_trace: bool,
    ) -> PolicyAnswer:
        sources = self._raw_sources(
            manual_ids=("4.3.2", "9.1.4", "1.3.2"),
            amendment_ids=("2.1", "2.2", "5.2"),
        )
        change_date = self._date_for_basis(
            question, context, TemporalBasis.CHANGE_DATE
        )
        if change_date is None:
            return self._missing_date(
                question=question,
                basis=TemporalBasis.CHANGE_DATE,
                chunks=sources,
                include_trace=include_trace,
            )
        if change_date < self.timeline.effective_date:
            left = self.manual["4.3.2"]
            right = self.manual["9.1.4"]
            finding = ConflictFinding(
                finding_id="CONFLICT-001-PRE-AMENDMENT",
                chunk_ids=[left.chunk_id, right.chunk_id],
                clause_ids=["4.3.2", "9.1.4"],
                explanation=(
                    "For a pre-1-March change, §4.3.2 requires reporting within "
                    "10 calendar days while §9.1.4 calls 30 calendar days the period "
                    "required under §4.3. Amendment paragraph 5.2 preserves that old regime."
                ),
                basis="CURATED",
                confidence=1.0,
            )
            return self._answer(
                question=question,
                decision=Decision.CONFLICT,
                answer=(
                    f"The change occurred on {_format_date(change_date)}, so the pre-amendment "
                    "wording remains applicable. Section 4.3.2 says the change must be reported "
                    "within 10 calendar days of the change or awareness, whichever is later. "
                    "Section 9.1.4 instead describes 30 calendar days as the period required "
                    "under §4.3 for its overpayment protection. The amendment does not "
                    "retroactively align those provisions, so I cannot give one conflict-free "
                    "deadline for this pre-March change."
                ),
                reason=finding.explanation,
                chunks=sources,
                next_step=str(self.contacts["conflict"]["next_step"]),
                include_trace=include_trace,
                conflicts=[finding],
            )

        anchor = context.awareness_date if (
            context.awareness_date is not None and context.awareness_date > change_date
        ) else change_date
        answer = (
            f"Because the change occurred on {_format_date(change_date)}, it is subject to "
            "the amended 14-calendar-day rule. The 14 days run from the later of the date "
            f"the change occurred and the date the recipient became aware of it"
        )
        if context.awareness_date is not None:
            answer += f"; on the dates supplied, that starting point is {_format_date(anchor)}"
        answer += (
            ". The aligned overpayment provision also uses 14 calendar days for changes "
            "on or after 1 March 2026."
        )
        return self._answer(
            question=question,
            decision=Decision.ANSWER,
            answer=answer,
            reason=(
                "Amendment paragraph 5.2 uses the date the change occurred, and the "
                f"supplied change date is {_format_date(change_date)}."
            ),
            chunks=sources,
            include_trace=include_trace,
        )

    def _sanction_rate_answer(
        self,
        question: str,
        context: TemporalContext,
        *,
        include_trace: bool,
    ) -> PolicyAnswer:
        rule = self._rule("sanction-rate")
        sources = self._raw_sources(
            manual_ids=("10.5.2", "1.2.3"),
            amendment_ids=("4.1", "5.1"),
        )
        relevant_date = self._date_for_basis(
            question, context, TemporalBasis.DETERMINATION_DATE
        )
        if relevant_date is None:
            return self._missing_date(
                question=question,
                basis=TemporalBasis.DETERMINATION_DATE,
                chunks=sources,
                include_trace=include_trace,
            )
        amended = relevant_date >= self.timeline.effective_date
        percent = int((rule.after if amended else rule.before)["percent"])
        return self._answer(
            question=question,
            decision=Decision.ANSWER,
            answer=(
                f"For a determination made {_format_date(relevant_date)}, a sanction is a "
                f"{percent}% reduction of the monthly award for 4 weeks for a first sanction, "
                "or 8 weeks for a subsequent sanction within 12 months."
            ),
            reason=(
                "The sanction percentage uses the determination date under amendment "
                f"paragraph 5.1; the supplied date is {_format_date(relevant_date)}."
            ),
            chunks=sources,
            include_trace=include_trace,
        )

    def _increase_protection_answer(
        self,
        question: str,
        context: TemporalContext,
        *,
        include_trace: bool,
    ) -> PolicyAnswer:
        sources = self._raw_sources(
            manual_ids=("4.3.4", "10.5.1", "1.2.3"),
            inserted_ids=("10.5.3A",),
            amendment_ids=("4.2", "5.1"),
        )
        relevant_date = self._date_for_basis(
            question, context, TemporalBasis.DETERMINATION_DATE
        )
        if relevant_date is None:
            return self._missing_date(
                question=question,
                basis=TemporalBasis.DETERMINATION_DATE,
                chunks=sources,
                include_trace=include_trace,
            )
        if relevant_date < self.timeline.effective_date:
            return self._answer(
                question=question,
                decision=Decision.REFUSE,
                answer=(
                    "I don't know of a pre-amendment rule that specifically protects a late "
                    "report when the change would have increased the award. The general manual "
                    "allows a failure-to-report sanction, but the new specific prohibition was "
                    f"not yet in force for a determination made {_format_date(relevant_date)}."
                ),
                reason=(
                    "The inserted §10.5.3A applies only to determinations on or after "
                    "1 March 2026, and the earlier manual does not settle this narrower case."
                ),
                chunks=sources,
                next_step=str(self.contacts["conflict"]["next_step"]),
                include_trace=include_trace,
            )
        return self._answer(
            question=question,
            decision=Decision.ANSWER,
            answer=(
                f"For a determination made {_format_date(relevant_date)}, no sanction may be "
                "imposed for failure to report if the change would have increased the award. "
                "That protection does not remove the separate duty to report the change."
            ),
            reason=(
                "Amendment paragraph 4.2 inserted §10.5.3A, and paragraph 5.1 makes "
                "it applicable to this post-effective determination."
            ),
            chunks=sources,
            include_trace=include_trace,
        )

    def _sanction_effect_answer(
        self,
        question: str,
        context: TemporalContext,
        *,
        include_trace: bool,
    ) -> PolicyAnswer:
        sources = self._raw_sources(
            manual_ids=("4.1.1", "10.5.2"),
            amendment_ids=("4.1", "5.1"),
        )
        relevant_date = self._date_for_basis(
            question, context, TemporalBasis.DETERMINATION_DATE
        )
        rate_text = "20% before 1 March 2026 and 15% on or after that date"
        if relevant_date is not None:
            rate_text = (
                "15%" if relevant_date >= self.timeline.effective_date else "20%"
            )
            rate_text += f" for the determination made {_format_date(relevant_date)}"
        left = self.manual["4.1.1"]
        right = self.manual["10.5.2"]
        finding = ConflictFinding(
            finding_id="CONFLICT-002-TEMPORAL",
            chunk_ids=[left.chunk_id, right.chunk_id],
            clause_ids=["4.1.1", "10.5.2"],
            explanation=(
                "Section 4.1.1 excludes a person with an unexpired §10.5 sanction "
                "from eligibility, while §10.5.2 defines a sanction as an award reduction. "
                "The amendment changes the percentage but does not resolve those effects."
            ),
            basis="CURATED",
            confidence=1.0,
        )
        return self._answer(
            question=question,
            decision=Decision.CONFLICT,
            answer=(
                "The manual still gives incompatible consequences. Section 4.1.1 says a "
                "person with an unexpired §10.5 sanction is excluded from eligibility, while "
                f"§10.5.2 defines the sanction as an award reduction ({rate_text}) for 4 or "
                "8 weeks. The amendment changes the reduction percentage but does not say "
                "whether exclusion, reduction, or both controls, so I cannot choose one."
            ),
            reason=finding.explanation,
            chunks=sources,
            next_step=str(self.contacts["conflict"]["next_step"]),
            include_trace=include_trace,
            conflicts=[finding],
        )

    def _spanning_answer(
        self,
        question: str,
        context: TemporalContext,
        *,
        include_trace: bool,
    ) -> PolicyAnswer:
        topic = self._topic(question)
        extra_manual: tuple[str, ...] = ()
        extra_amendment: tuple[str, ...] = ()
        if topic == "earnings_disregard" or EARNINGS_TOPIC_RE.search(question):
            extra_manual = ("6.4.1",)
            extra_amendment = ("1.1",)
        elif topic == "income_threshold" or THRESHOLD_TOPIC_RE.search(question):
            extra_manual = ("6.6.1",)
            extra_amendment = ("3.1",)
        sources = self._raw_sources(
            manual_ids=("7.4.3",) + extra_manual,
            amendment_ids=("5.3",) + extra_amendment,
        )
        return self._answer(
            question=question,
            decision=Decision.ANSWER,
            answer=(
                "For a claim period spanning 1 March 2026, do not use one blended or "
                "latest figure for the whole period. Use the figures in force on each day: "
                "the pre-amendment figures before 1 March and the amended figures from "
                "1 March onward, then apportion the award by the number of days. An exact "
                "award still requires the period dates and the other calculation facts."
            ),
            reason=(
                "Amendment paragraph 5.3 is the specific transition for a spanning "
                "claim and requires day-by-day figures with §7.4.3 apportionment."
            ),
            chunks=sources,
            include_trace=include_trace,
        )
