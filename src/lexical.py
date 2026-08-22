"""Small transparent BM25 implementation for exact policy terminology."""

from __future__ import annotations

import math
import re
from collections import Counter

from src.models import PolicyChunk
from src.parser import get_embedding_text

TOKEN_RE = re.compile(r"§?\d+(?:\.\d+)+|\$?\d+(?:,\d{3})*(?:\.\d+)?%?|[a-z][a-z'-]*", re.IGNORECASE)
STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "based", "by", "can", "could",
    "do", "does", "for", "from", "had", "has", "have", "how", "i", "if", "in",
    "is", "it", "me", "my", "of", "on", "or", "say", "says", "the", "their",
    "there", "they", "this", "to", "under", "was", "what", "when", "where", "which",
    "who", "will", "with", "would", "manual", "policy", "please", "tell", "about",
    "calder", "county", "program", "hsp", "assistance", "department", "may", "might",
    "must", "shall", "should",
}

SYNONYMS: dict[str, tuple[str, ...]] = {
    "qualify": ("eligible", "eligibility"),
    "qualified": ("eligible", "eligibility"),
    "eligible": ("eligibility",),
    "eligibility": ("eligible",),
    "assets": ("resources",),
    "asset": ("resource",),
    "deadline": ("period", "days", "time", "limit"),
    "time": ("period", "days"),
    "allow": ("give", "period", "days"),
    "exception": ("unless", "extended", "where"),
    "referral": ("referred", "supervisor"),
    "late": ("failed", "delay", "period"),
    "penalty": ("sanction", "reduction"),
    "punishment": ("sanction", "reduction"),
    "meeting": ("interview",),
    "homeless": ("fixed", "address"),
    "teenager": ("under", "18", "16", "17"),
    "minor": ("under", "18", "16", "17"),
    "challenge": ("review", "appeal"),
    "denial": ("refused", "determination", "review", "appeal"),
    "denied": ("refused", "determination", "review", "appeal"),
    "car": ("vehicle",),
    "cars": ("vehicles",),
    "outside": ("absent", "absence"),
    "away": ("absent", "absence"),
    "college": ("student", "education"),
    "savings": ("resource", "resources"),
    "saving": ("resource", "resources"),
    "earn": ("earnings", "income"),
    "live": ("resident", "residence"),
    "receive": ("payment", "award"),
    "benefit": ("award", "assistance"),
    "benefits": ("award", "assistance"),
    "old": ("age", "aged"),
    "age": ("aged",),
    "wage": ("earnings",),
    "wages": ("earnings",),
    "proof": ("evidence",),
    "prove": ("evidence",),
    "first": ("before",),
}

PHRASE_EXPANSIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("cut me off", ("suspend", "terminate", "termination")),
    ("hand in", ("provide", "submit")),
    ("turn in", ("provide", "submit")),
    ("no fixed address", ("connection", "county")),
    ("how long", ("period", "days", "weeks", "months")),
    ("time limit", ("period", "days", "within")),
    ("full time", ("full-time",)),
    ("how much assistance", ("award", "needs", "figure", "countable", "income")),
)


def stem(token: str) -> str:
    token = token.lower().strip("§$").replace(",", "")
    token = token.removesuffix("'s")
    if len(token) > 5 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 5 and token.endswith("ied"):
        return token[:-3] + "y"
    if len(token) > 5 and token.endswith("ing"):
        return token[:-3]
    if len(token) > 4 and token.endswith("ed"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokenize(text: str, *, expand: bool = False, keep_stop_words: bool = False) -> list[str]:
    raw = text.lower()
    raw_tokens = [token.lower().strip("§$").replace(",", "") for token in TOKEN_RE.findall(raw)]
    tokens = [stem(token) for token in raw_tokens]
    if not keep_stop_words:
        # Check both forms.  Stemming turns words such as ``does`` into ``doe``;
        # filtering only after stemming made those auxiliaries look like policy
        # concepts and could turn an unrelated modal sentence into DIRECT evidence.
        tokens = [
            token
            for raw_token, token in zip(raw_tokens, tokens, strict=True)
            if raw_token not in STOP_WORDS and token not in STOP_WORDS
        ]
    if expand:
        additions: list[str] = []
        for raw_token, token in zip(raw_tokens, [stem(item) for item in raw_tokens], strict=True):
            if not keep_stop_words and (raw_token in STOP_WORDS or token in STOP_WORDS):
                continue
            additions.extend(
                stem(item)
                for item in (
                    *SYNONYMS.get(raw_token, ()),
                    *SYNONYMS.get(token, ()),
                )
            )
        for phrase, terms in PHRASE_EXPANSIONS:
            if phrase in raw:
                additions.extend(stem(item) for item in terms)
        tokens.extend(additions)
    return tokens


class BM25Index:
    """In-memory BM25 index reconstructed from persisted trusted chunks."""

    def __init__(self, chunks: list[PolicyChunk], *, k1: float = 1.5, b: float = 0.75) -> None:
        self.chunks = chunks
        self.k1 = k1
        self.b = b
        self.documents = [tokenize(get_embedding_text(chunk), keep_stop_words=False) for chunk in chunks]
        self.term_frequencies = [Counter(document) for document in self.documents]
        self.document_frequency: Counter[str] = Counter()
        for document in self.documents:
            self.document_frequency.update(set(document))
        self.average_length = sum(map(len, self.documents)) / max(1, len(self.documents))

    def search(self, question: str, k: int = 12) -> list[tuple[PolicyChunk, float]]:
        query_terms = tokenize(question, expand=True)
        if not query_terms:
            return []
        raw_scores = [self._score(query_terms, index) for index in range(len(self.chunks))]
        ranked = sorted(enumerate(raw_scores), key=lambda item: item[1], reverse=True)
        positive = [(idx, score) for idx, score in ranked if score > 0][:k]
        if not positive:
            return []
        maximum = positive[0][1]
        return [(self.chunks[idx], score / maximum) for idx, score in positive]

    def _score(self, query_terms: list[str], doc_index: int) -> float:
        frequencies = self.term_frequencies[doc_index]
        length = len(self.documents[doc_index])
        total = 0.0
        for term in set(query_terms):
            frequency = frequencies.get(term, 0)
            if not frequency:
                continue
            document_frequency = self.document_frequency[term]
            inverse_document_frequency = math.log(
                1 + (len(self.documents) - document_frequency + 0.5) / (document_frequency + 0.5)
            )
            denominator = frequency + self.k1 * (
                1 - self.b + self.b * length / max(self.average_length, 1.0)
            )
            total += inverse_document_frequency * (frequency * (self.k1 + 1)) / denominator
        return total
