"""
intent_router.py — Classifies a user prompt into Phase I / II / III / general.
Uses keyword heuristics first; falls back to Groq classification when ambiguous.
"""
from __future__ import annotations

import re
from typing import Literal

PhaseType = Literal["phase1", "phase2", "phase3", "general"]

# ── Phase III — chart/visualisation (highest priority) ────────────────────────
_PHASE3_KEYWORDS = re.compile(
    r"\b(chart|plot|graph|visuali[sz]|bar chart|pie chart|line chart|"
    r"scatter|histogram|dashboard|trend)\b",
    re.IGNORECASE,
)

# ── Phase I — strong creation / extraction verbs ──────────────────────────────
# These are unambiguous Phase 1 signals.
_PHASE1_STRONG = re.compile(
    r"\b(extract|import|scrape|create table|new table|add data|upload|paste|"
    r"from url|from pdf|from image|populate|load data|copy from|pull from|"
    r"fetch|ingest)\b",
    re.IGNORECASE,
)

# Creation verbs that are Phase 1 UNLESS a strong Phase 2 verb also appears.
# "add" is intentionally excluded — it's ambiguous ("add a column" = Phase 2,
# "add data" = Phase 1) so it falls through to Groq.
_PHASE1_CREATION = re.compile(
    r"\b(create|make|generate|build|produce|give me|show me)\b",
    re.IGNORECASE,
)

# ── Phase II — unambiguous operation-on-existing-data verbs ───────────────────
# Only words that are *impossible* to misread as "I want to create a table
# whose column is called <X>". Generic column-name words (revenue, total, etc.)
# are intentionally excluded — they are too ambiguous.
_PHASE2_STRONG = re.compile(
    r"\b(formula|calculat|sort by|sort the|"
    r"add a column|add column|add a row|add row|derive|compute|"
    r"delete row|delete column|remove row|remove column|"
    r"edit cell|change cell|update cell|clear cell|"
    r"set value|rename column|find and replace|"
    r"vlookup|index.?match|profit margin|growth rate|"
    r"running total|cumulative|rank|"
    r"multiply|divide|ratio|"
    r"sum of|average of|total of|count of|max of|min of|"
    r"autosum|auto-sum|avg of|"
    r"summ|total row|sum row|add.*formula|"
    r"\bsum\b|\bavg\b|\bsum\s+all\b)\b",
    re.IGNORECASE,
)

# Weak Phase 2 — these can appear in Phase 1 "create a table with X" contexts,
# so they only trigger Phase 2 if no creation verb is also present.
_PHASE2_WEAK = re.compile(
    r"\b(sum|total|average|avg|percent|count|max|min|"
    r"filter|merge|join|lookup|replace|"
    r"edit|change|update|rename|delete|remove)\b",
    re.IGNORECASE,
)


def _keyword_classify(message: str) -> tuple[PhaseType | None, float]:
    """Returns (phase, confidence) or (None, 0.0) if ambiguous."""
    has_p3     = bool(_PHASE3_KEYWORDS.search(message))
    has_p1s    = bool(_PHASE1_STRONG.search(message))
    has_p1c    = bool(_PHASE1_CREATION.search(message))
    has_p2s    = bool(_PHASE2_STRONG.search(message))
    has_p2w    = bool(_PHASE2_WEAK.search(message))

    # Chart beats everything when explicitly named
    if has_p3 and not has_p2s and not has_p1s:
        return "phase3", 0.95
    if has_p3:
        return "phase3", 0.80

    # Strong Phase 1 signal — unambiguous extraction/import verbs
    if has_p1s and not has_p3:
        return "phase1", 0.92

    # Strong Phase 2 signal — operation verbs on existing data
    if has_p2s and not has_p1s and not has_p1c:
        return "phase2", 0.90

    # Creation verbs (create/make/generate) with NO strong Phase 2 operation →
    # user wants to CREATE a table, not operate on one.
    if has_p1c and not has_p2s:
        return "phase1", 0.85

    # Creation verb + strong Phase 2 verb → ambiguous, fall back to Groq
    # e.g. "create a formula to sum revenue" — Groq decides
    if has_p1c and has_p2s:
        return None, 0.0

    # Weak Phase 2 only, no creation verb → likely Phase 2
    if has_p2w and not has_p1c and not has_p1s:
        return "phase2", 0.75

    return None, 0.0


def classify(message: str) -> PhaseType:
    """
    Classify a user message into phase1 | phase2 | phase3 | general.
    Fast keyword check first, Groq fallback only when ambiguous.
    """
    phase, conf = _keyword_classify(message)
    if phase is not None:
        return phase

    try:
        from app.services.groq_client import classify_intent
        result = classify_intent(message)
        return result.get("phase", "general")  # type: ignore[return-value]
    except Exception:
        return "general"
