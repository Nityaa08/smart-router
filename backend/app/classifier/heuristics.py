"""
Zero-cost heuristic classifier.
No LLM calls — pure rule-based scoring.

The score measures complexity: signals of a harder prompt add points, and
"simple" keywords ("what is", "define", ...) take points away, so a prompt
made of several simple questions stays simple instead of climbing a tier.
"""
import re
from dataclasses import dataclass, field
from typing import Literal

Tier = Literal["simple", "medium", "complex"]

# Tier thresholds on the final score (which is never below 0).
SIMPLE_MAX = 1   # score 0-1  -> simple
COMPLEX_MIN = 4  # score 2-3  -> medium, 4 or more -> complex

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
CODE_PATTERNS = [r"```", r"\bdef \b", r"\bfunction\s*\w*\s*\(", r"\bclass \b", r"\bimport \b", r"=>"]
MULTI_STEP_PATTERNS = [
    r"\bfirst\b.{5,50}\bthen\b",
    r"\bstep \d\b",
    r"^\d+\.\s",
    r"\bmultiple\b.{0,30}\bsteps\b",
]
MATH_LOGIC_PATTERNS = [
    r"\bprove\b", r"\bderive\b", r"\boptimize algorithm\b", r"\bcomplexity\b",
    r"\bO\((?:1|n|log)", r"\bBig-O\b", r"\brecursion\b", r"\bdynamic programming\b",
]


@dataclass
class Signal:
    """One scoring rule that fired, for explaining a routing decision."""
    name: str
    points: int
    detail: str


@dataclass
class ClassifierResult:
    tier: Tier
    score: int
    confidence: float  # 0.0–1.0
    token_estimate: int = 0
    signals: list[Signal] = field(default_factory=list)


def _count_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return max(1, len(text) // 4)


def _matches_any(text: str, patterns: list[str]) -> int:
    """Return count of distinct patterns matched."""
    return sum(1 for p in patterns if re.search(p, text, re.IGNORECASE | re.MULTILINE))


def _confidence(tier: Tier, score: int) -> float:
    """How far the score sits from the nearest tier boundary: 1 point = 0.5, 2 or more = 1.0."""
    if tier == "simple":
        margin = SIMPLE_MAX + 1 - score
    elif tier == "medium":
        margin = min(score - SIMPLE_MAX, COMPLEX_MIN - score)
    else:
        margin = score - COMPLEX_MIN + 1
    return round(min(1.0, margin / 2), 2)


def classify(messages: list[dict]) -> ClassifierResult:
    """
    Score a conversation and return its complexity tier.

    Scoring rules:
      -1  each simple keyword ("what is", "define", ...), at most -2
      +1  each medium keyword ("explain", "compare", ...), at most +3
      +2  each complex keyword ("implement", "debug", ...), at most +4
      +2  code patterns detected
      +2  multi-step patterns detected
      +2  math/logic patterns detected
      +2  token count > 500
    The score is the sum, floored at 0: 0-1 simple, 2-3 medium, 4+ complex.
    """
    full_text = " ".join(
        m.get("content", "") if isinstance(m, dict) else m.content
        for m in messages
        if (m.get("role") if isinstance(m, dict) else m.role) == "user"
    )

    token_count = _count_tokens(full_text)
    signals: list[Signal] = []

    def add(name: str, points: int, detail: str) -> None:
        if points:
            signals.append(Signal(name, points, detail))

    # Length: only a long prompt is a signal; being short adds nothing.
    if token_count > 500:
        add("long prompt", 2, f"about {token_count} tokens (> 500)")

    # Keyword signals
    simple_hits = _matches_any(full_text, SIMPLE_KEYWORDS)
    medium_hits = _matches_any(full_text, MEDIUM_KEYWORDS)
    complex_keyword_hits = _matches_any(full_text, COMPLEX_KEYWORDS)

    add("simple keywords", -min(simple_hits, 2), f"{simple_hits} matched, e.g. 'what is', 'define' (-1 each, max -2)")
    add("medium keywords", min(medium_hits * 1, 3), f"{medium_hits} matched, e.g. 'explain', 'compare' (+1 each, max 3)")
    add("complex keywords", min(complex_keyword_hits * 2, 4),
        f"{complex_keyword_hits} matched, e.g. 'implement', 'debug' (+2 each, max 4)")

    # Code patterns
    if _matches_any(full_text, CODE_PATTERNS):
        add("code", 2, "code fences or code keywords")

    # Multi-step
    if _matches_any(full_text, MULTI_STEP_PATTERNS):
        add("multi-step", 2, "'first ... then', 'step 1' or a numbered list")

    # Math/logic
    if _matches_any(full_text, MATH_LOGIC_PATTERNS):
        add("math / logic", 2, "'prove', 'complexity', 'Big-O', 'recursion' ...")

    score = max(0, sum(s.points for s in signals))

    tier: Tier
    if score <= SIMPLE_MAX:
        tier = "simple"
    elif score < COMPLEX_MIN:
        tier = "medium"
    else:
        tier = "complex"

    return ClassifierResult(
        tier=tier,
        score=score,
        confidence=_confidence(tier, score),
        token_estimate=token_count,
        signals=signals,
    )
