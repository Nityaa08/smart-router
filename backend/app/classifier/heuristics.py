"""
Zero-cost heuristic classifier.
No LLM calls — pure rule-based scoring.
"""
import re
from dataclasses import dataclass
from typing import Literal

Tier = Literal["simple", "medium", "complex"]

# Signal keyword lists
SIMPLE_KEYWORDS = [
    r"\bwhat is\b", r"\bdefine\b", r"\btranslate\b", r"\bsummariz", r"\bwho is\b",
    r"\bwhen was\b", r"\bhow many\b", r"\blist the\b", r"\bname the\b",
]
MEDIUM_KEYWORDS = [
    r"\bexplain\b", r"\bcompare\b", r"\banalyze\b", r"\bwrite a\b", r"\bdescribe\b",
    r"\bhow does\b", r"\bwhy does\b", r"\bdifference between\b",
]
COMPLEX_KEYWORDS = [
    r"\bprove\b", r"\bderive\b", r"\boptimiz", r"\barchitect\b", r"\bimplement\b",
    r"\bdesign a system\b", r"\brefactor\b", r"\bdebug\b", r"\balgorithm\b",
]
CODE_PATTERNS = [r"```", r"\bdef \b", r"\bfunction ", r"\bclass \b", r"\bimport \b", r"=>"]
MULTI_STEP_PATTERNS = [
    r"\bfirst\b.{5,50}\bthen\b",
    r"\bstep \d\b",
    r"^\d+\.\s",
    r"\bmultiple\b.{0,30}\bsteps\b",
]
MATH_LOGIC_PATTERNS = [
    r"\bprove\b", r"\bderive\b", r"\boptimize algorithm\b", r"\bcomplexity\b",
    r"\bO\(n", r"\bBig-O\b", r"\brecursion\b", r"\bdynamic programming\b",
]


@dataclass
class ClassifierResult:
    tier: Tier
    score: int
    confidence: float  # 0.0–1.0


def _count_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return max(1, len(text) // 4)


def _matches_any(text: str, patterns: list[str]) -> int:
    """Return count of distinct patterns matched."""
    return sum(1 for p in patterns if re.search(p, text, re.IGNORECASE | re.MULTILINE))


def classify(messages: list[dict]) -> ClassifierResult:
    """
    Score a conversation and return its complexity tier.

    Scoring rules:
      +2  token count < 100      → simple signal
      +2  simple keywords match
      +1  medium keywords match
      +2  code patterns detected
      +2  multi-step patterns detected
      +2  math/logic patterns detected
      +2  token count > 500      → complex signal
    """
    full_text = " ".join(
        m.get("content", "") if isinstance(m, dict) else m.content
        for m in messages
        if (m.get("role") if isinstance(m, dict) else m.role) == "user"
    )

    token_count = _count_tokens(full_text)
    score = 0

    # Token-length signals
    if token_count < 100:
        score += 2
    if token_count > 500:
        score += 2

    # Keyword signals
    simple_hits = _matches_any(full_text, SIMPLE_KEYWORDS)
    medium_hits = _matches_any(full_text, MEDIUM_KEYWORDS)
    complex_keyword_hits = _matches_any(full_text, COMPLEX_KEYWORDS)

    score += min(simple_hits * 2, 4)   # cap at +4
    score += min(medium_hits * 1, 3)   # cap at +3
    score += min(complex_keyword_hits * 2, 4)

    # Code patterns
    code_hits = _matches_any(full_text, CODE_PATTERNS)
    if code_hits:
        score += 2

    # Multi-step
    multi_hits = _matches_any(full_text, MULTI_STEP_PATTERNS)
    if multi_hits:
        score += 2

    # Math/logic
    math_hits = _matches_any(full_text, MATH_LOGIC_PATTERNS)
    if math_hits:
        score += 2

    # Determine tier
    # simple: score <= 4, medium: 5–7, complex: >= 8
    if score <= 4:
        tier: Tier = "simple"
        max_score = 4
    elif score <= 7:
        tier = "medium"
        max_score = 7
    else:
        tier = "complex"
        max_score = 14

    confidence = min(1.0, score / max(max_score, 1))

    return ClassifierResult(tier=tier, score=score, confidence=round(confidence, 2))
