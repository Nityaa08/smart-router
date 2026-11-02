"""
Unit tests for configuration utilities.
No database or external services required.
"""
import pytest
from app.config import Settings, calculate_cost, MODEL_PRICING, BASELINE_MODEL


# ─── DATABASE_URL scheme fixer ────────────────────────────────────────────────

class TestFixDbScheme:
    def test_postgres_prefix_replaced(self):
        result = Settings.fix_db_scheme("postgres://user:pass@host:5432/db")
        assert result == "postgresql+asyncpg://user:pass@host:5432/db"

    def test_postgresql_prefix_replaced(self):
        result = Settings.fix_db_scheme("postgresql://user:pass@host:5432/db")
        assert result == "postgresql+asyncpg://user:pass@host:5432/db"

    def test_already_correct_scheme_unchanged(self):
        url = "postgresql+asyncpg://user:pass@host:5432/db"
        result = Settings.fix_db_scheme(url)
        assert result == url

    def test_empty_string_unchanged(self):
        result = Settings.fix_db_scheme("")
        assert result == ""

    def test_other_scheme_unchanged(self):
        url = "sqlite:///./test.db"
        result = Settings.fix_db_scheme(url)
        assert result == url


# ─── calculate_cost ───────────────────────────────────────────────────────────

class TestCalculateCost:
    def test_zero_tokens_is_zero_cost(self):
        cost = calculate_cost("gpt-4o", 0, 0)
        assert cost == 0.0

    def test_gpt4o_input_cost(self):
        # gpt-4o: $2.50 / 1M input tokens
        cost = calculate_cost("gpt-4o", 1_000_000, 0)
        assert abs(cost - 2.50) < 1e-9

    def test_gpt4o_output_cost(self):
        # gpt-4o: $10.00 / 1M output tokens
        cost = calculate_cost("gpt-4o", 0, 1_000_000)
        assert abs(cost - 10.00) < 1e-9

    def test_gpt4o_combined_cost(self):
        # 500k input + 500k output
        cost = calculate_cost("gpt-4o", 500_000, 500_000)
        expected = (500_000 * 2.50 + 500_000 * 10.00) / 1_000_000
        assert abs(cost - expected) < 1e-9

    def test_free_model_zero_cost(self):
        cost = calculate_cost("meta-llama/llama-3.2-1b-instruct:free", 100_000, 100_000)
        assert cost == 0.0

    def test_unknown_model_falls_back_to_gpt4o(self):
        cost_unknown = calculate_cost("unknown-model-xyz", 1_000_000, 0)
        cost_gpt4o = calculate_cost("gpt-4o", 1_000_000, 0)
        assert cost_unknown == cost_gpt4o

    def test_ollama_local_near_zero(self):
        # llama3.2:1b: $0.01 / 1M tokens (near zero for small requests)
        cost = calculate_cost("llama3.2:1b", 1000, 1000)
        assert cost < 0.001

    def test_cost_is_float(self):
        cost = calculate_cost("gpt-4o", 100, 100)
        assert isinstance(cost, float)


# ─── MODEL_PRICING coverage ───────────────────────────────────────────────────

class TestModelPricing:
    def test_baseline_model_in_pricing(self):
        assert BASELINE_MODEL in MODEL_PRICING

    def test_all_pricing_entries_have_input_output(self):
        for model, pricing in MODEL_PRICING.items():
            assert "input" in pricing, f"{model} missing 'input' key"
            assert "output" in pricing, f"{model} missing 'output' key"
            assert pricing["input"] >= 0, f"{model} input price negative"
            assert pricing["output"] >= 0, f"{model} output price negative"

    def test_ollama_models_present(self):
        assert "llama3.2:1b" in MODEL_PRICING
        assert "llama3.1:8b" in MODEL_PRICING

    def test_groq_models_present(self):
        assert "openai/gpt-oss-20b" in MODEL_PRICING
        assert "openai/gpt-oss-120b" in MODEL_PRICING


# ─── Default model IDs ────────────────────────────────────────────────────────

RETIRED_MODEL_IDS = {
    # Groq: shut down 2025-08-30
    "llama3-8b-8192", "llama3-70b-8192",
    # Groq: shut down 2026-08-16 (free/developer tiers)
    "llama-3.1-8b-instant", "llama-3.3-70b-versatile",
    # OpenRouter: no longer listed (checked 2026-10-28)
    "meta-llama/llama-3.2-1b-instruct:free", "meta-llama/llama-3.1-8b-instruct:free",
}


class TestDefaultModels:
    def _defaults(self, prefix: str) -> list[str]:
        fields = Settings.model_fields
        return [fields[f"{prefix}_{t}_model"].default for t in ("simple", "medium", "complex")]

    @pytest.mark.parametrize("prefix", ["groq", "openrouter"])
    def test_no_retired_defaults(self, prefix):
        for model in self._defaults(prefix):
            assert model not in RETIRED_MODEL_IDS, f"{model} is retired"

    def test_groq_defaults_are_priced(self):
        # Unpriced models fall back to GPT-4o pricing and show zero savings.
        for model in self._defaults("groq"):
            assert model in MODEL_PRICING

    def test_openrouter_defaults_are_free(self):
        for model in self._defaults("openrouter"):
            assert model.endswith(":free")
            assert calculate_cost(model, 1_000_000, 1_000_000) == 0.0

    def test_env_example_matches_defaults(self):
        import pathlib
        env = (pathlib.Path(__file__).resolve().parents[2] / ".env.example").read_text()
        for prefix in ("groq", "openrouter"):
            for tier, model in zip(("SIMPLE", "MEDIUM", "COMPLEX"), self._defaults(prefix)):
                assert f"{prefix.upper()}_{tier}_MODEL={model}\n" in env
