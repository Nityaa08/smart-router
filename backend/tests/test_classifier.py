"""
Unit tests for the zero-cost heuristic classifier.
No external services required.
"""
import pytest
from app.classifier.heuristics import (
    classify,
    ClassifierResult,
    _count_tokens,
    _matches_any,
    SIMPLE_KEYWORDS,
    COMPLEX_KEYWORDS,
    CODE_PATTERNS,
)


# ─── _count_tokens ────────────────────────────────────────────────────────────

class TestCountTokens:
    def test_empty_string_returns_one(self):
        assert _count_tokens("") == 1

    def test_short_text(self):
        # 12 chars // 4 = 3
        assert _count_tokens("What is 2+2?") == 3

    def test_longer_text(self):
        text = "a" * 400
        assert _count_tokens(text) == 100

    def test_very_long_text(self):
        text = "x" * 2000
        assert _count_tokens(text) == 500


# ─── _matches_any ─────────────────────────────────────────────────────────────

class TestMatchesAny:
    def test_no_match(self):
        assert _matches_any("hello world", SIMPLE_KEYWORDS) == 0

    def test_single_match(self):
        assert _matches_any("What is Python?", SIMPLE_KEYWORDS) >= 1

    def test_multiple_distinct_patterns(self):
        # "what is" and "define" are two distinct patterns
        hits = _matches_any("What is Python? Can you define it?", SIMPLE_KEYWORDS)
        assert hits >= 2

    def test_case_insensitive(self):
        assert _matches_any("WHAT IS Python?", SIMPLE_KEYWORDS) >= 1

    def test_code_pattern_backticks(self):
        assert _matches_any("Use ```python``` code blocks", CODE_PATTERNS) >= 1

    def test_code_pattern_def(self):
        assert _matches_any("def my_function():", CODE_PATTERNS) >= 1

    def test_code_pattern_class(self):
        assert _matches_any("class MyClass:", CODE_PATTERNS) >= 1


# ─── classify ─────────────────────────────────────────────────────────────────

class TestClassify:
    # ── Simple tier ──────────────────────────────────────────────────────────

    def test_simple_factual_question(self):
        result = classify([{"role": "user", "content": "What is Python?"}])
        assert result.tier == "simple"

    def test_simple_short_math(self):
        result = classify([{"role": "user", "content": "What is 2+2?"}])
        assert result.tier == "simple"

    def test_simple_definition(self):
        # "recursion" is a MATH_LOGIC_PATTERN, so use a neutral definition prompt
        result = classify([{"role": "user", "content": "Define what an API is"}])
        assert result.tier == "simple"

    def test_simple_translation(self):
        result = classify([{"role": "user", "content": "Translate 'hello' to Spanish"}])
        assert result.tier == "simple"

    def test_simple_who_is(self):
        result = classify([{"role": "user", "content": "Who is Ada Lovelace?"}])
        assert result.tier == "simple"

    def test_system_messages_ignored(self):
        # System messages should not affect scoring — only user messages count
        messages = [
            {"role": "system", "content": "implement algorithm debug refactor optimize prove derive"},
            {"role": "user", "content": "What is 2+2?"},
        ]
        result = classify(messages)
        assert result.tier == "simple"

    def test_assistant_messages_ignored(self):
        messages = [
            {"role": "assistant", "content": "implement algorithm debug refactor optimize prove derive"},
            {"role": "user", "content": "What is 2+2?"},
        ]
        result = classify(messages)
        assert result.tier == "simple"

    # ── Complex tier ─────────────────────────────────────────────────────────

    def test_complex_algorithm_implementation(self):
        result = classify([{
            "role": "user",
            "content": (
                "Implement a recursive algorithm to find all permutations of a list "
                "in Python. First analyze the complexity, then write the code with tests."
            ),
        }])
        assert result.tier == "complex"

    def test_complex_system_design(self):
        # Multiple complex signals: design a system + implement + algorithm + Big-O + analyze
        result = classify([{
            "role": "user",
            "content": (
                "Design a distributed caching system, then implement the consistent hashing "
                "algorithm and analyze its Big-O complexity"
            ),
        }])
        assert result.tier == "complex"

    def test_complex_code_block(self):
        result = classify([{
            "role": "user",
            "content": (
                "```python\ndef fibonacci(n):\n    pass\n```\n"
                "Implement the above function and analyze its time complexity and Big-O notation"
            ),
        }])
        assert result.tier == "complex"

    def test_complex_large_token_count(self):
        # >500 tokens (+2) plus complex keywords: debug + refactor (+4) → score ≥ 6 → medium/complex
        long_prompt = "Debug and refactor this code. " * 80  # ~2400 chars → ~600 tokens
        result = classify([{"role": "user", "content": long_prompt}])
        assert result.tier in ("medium", "complex")

    # ── Medium tier ──────────────────────────────────────────────────────────

    def test_medium_comparison(self):
        # "explain" + "optimize" (from optimiz pattern) → medium
        result = classify([{
            "role": "user",
            "content": "Explain how neural networks learn, focusing on gradient optimization techniques",
        }])
        assert result.tier == "medium"

    # ── ClassifierResult structure ────────────────────────────────────────────

    def test_result_has_score(self):
        result = classify([{"role": "user", "content": "What is Python?"}])
        assert isinstance(result.score, int)
        assert result.score >= 0

    def test_result_confidence_range(self):
        result = classify([{"role": "user", "content": "What is Python?"}])
        assert 0.0 <= result.confidence <= 1.0

    def test_result_tier_is_valid_literal(self):
        for prompt in [
            "What is 2+2?",
            "Explain machine learning",
            "Implement and debug a red-black tree with full test coverage and Big-O analysis",
        ]:
            result = classify([{"role": "user", "content": prompt}])
            assert result.tier in ("simple", "medium", "complex")

    def test_empty_messages(self):
        result = classify([])
        assert result.tier == "simple"
        assert result.score >= 0

    def test_no_user_messages(self):
        result = classify([{"role": "assistant", "content": "Hello, how can I help?"}])
        assert result.tier == "simple"

    def test_multi_turn_conversation(self):
        messages = [
            {"role": "user", "content": "What is Python?"},
            {"role": "assistant", "content": "Python is a programming language."},
            {"role": "user", "content": "What is JavaScript?"},
        ]
        result = classify(messages)
        # Both user messages are scored together
        assert result.tier == "simple"

    def test_force_tier_not_applicable(self):
        # classify() scores on content only — a huge complex prompt stays complex
        result = classify([{
            "role": "user",
            "content": (
                "Implement and debug a self-balancing AVL tree in Python. "
                "First, derive the rotation algorithm, then analyze its Big-O complexity, "
                "then write the full implementation with step 1 and step 2 clearly separated."
            ),
        }])
        assert result.tier == "complex"


# ─── Simple keywords pull the score down ─────────────────────────────────────

class TestSimpleSignalsDoNotEscalate:
    """'What is', 'who is', 'define' ... used to add +2 each, so a prompt with two
    simple questions scored 6 and went to the medium tier."""

    @pytest.mark.parametrize("prompt", [
        "What is DNS? How many root servers are there?",
        "Who is Alan Turing and when was he born?",
        "Define latency and list the main causes",
        "What is the capital of France? Who is its president? When was the Eiffel Tower built?",
    ])
    def test_several_simple_questions_stay_simple(self, prompt):
        result = classify([{"role": "user", "content": prompt}])
        assert result.tier == "simple"

    def test_simple_keywords_subtract_points(self):
        result = classify([{"role": "user", "content": "What is DNS? How many root servers are there?"}])
        simple = [s for s in result.signals if s.name == "simple keywords"]
        assert simple[0].points == -2

    def test_score_never_goes_below_zero(self):
        result = classify([{"role": "user", "content": "Who is Ada Lovelace? When was she born?"}])
        assert result.score == 0
        assert result.confidence == 1.0

    def test_short_length_alone_adds_nothing(self):
        result = classify([{"role": "user", "content": "hi"}])
        assert result.score == 0 and result.signals == []

    def test_explanation_requests_reach_medium(self):
        # Two medium keywords used to score 2 + 2 (short prompt) = 4, i.e. simple.
        result = classify([{"role": "user", "content": "Explain the difference between TCP and UDP"}])
        assert result.tier == "medium"

    def test_big_o_with_constant_or_log_counts_as_math(self):
        for prompt in ("Implement an LRU cache with O(1) get and put", "Search in O(log n)"):
            result = classify([{"role": "user", "content": prompt}])
            assert any(s.name == "math / logic" for s in result.signals), prompt

    def test_function_in_prose_is_not_code(self):
        prose = classify([{"role": "user", "content": "Write a function to reverse a string"}])
        code = classify([{"role": "user", "content": "Fix this: function add(a, b) { return a - b }"}])
        assert not any(s.name == "code" for s in prose.signals)
        assert any(s.name == "code" for s in code.signals)


# ─── Hand-labelled prompts ───────────────────────────────────────────────────
from app.evals.labelled import LABELLED as _LABELLED, KNOWN_MISSES  # noqa: E402
# A small regression set with labels written by hand: 8 prompts per tier. It is
# not a validation of the classifier, only a check that obvious cases route as
# expected. Before the scoring change 10 of 24 matched; now 23 of 24 do.

LABELLED = [
    pytest.param(exp, prompt, marks=pytest.mark.xfail(strict=True, reason=KNOWN_MISSES[i]))
    if i in KNOWN_MISSES else (exp, prompt)
    for i, (exp, prompt) in enumerate(_LABELLED)
]


@pytest.mark.parametrize("expected,prompt", LABELLED)
def test_labelled_prompt_routes_to_expected_tier(expected, prompt):
    assert classify([{"role": "user", "content": prompt}]).tier == expected
