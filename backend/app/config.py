from pydantic_settings import BaseSettings
from pydantic import field_validator
from functools import lru_cache
from typing import Literal


class Settings(BaseSettings):
    # Provider: "ollama" | "groq" | "openrouter" | "openai_compat"
    provider: str = "ollama"

    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    ollama_simple_model: str = "llama3.2:1b"
    ollama_medium_model: str = "llama3.1:8b"
    ollama_complex_model: str = "llama3.1:8b"

    # Groq
    groq_api_key: str = ""
    # Groq production models, checked 2026-11-02 (console.groq.com/docs/models).
    # llama3-*-8192 were shut down 2025-08-30; llama-3.1-8b-instant and
    # llama-3.3-70b-versatile on 2026-08-16 (free/developer tiers).
    groq_simple_model: str = "openai/gpt-oss-20b"
    groq_medium_model: str = "openai/gpt-oss-120b"
    groq_complex_model: str = "openai/gpt-oss-120b"

    # OpenRouter (free models — sign up at openrouter.ai, no credit card)
    openrouter_api_key: str = ""
    # Free models listed by openrouter.ai/api/v1/models?max_price=0 on 2026-11-02.
    # OpenRouter's free list changes often; re-check it if requests return 404.
    openrouter_simple_model: str = "google/gemma-4-26b-a4b-it:free"
    openrouter_medium_model: str = "google/gemma-4-31b-it:free"
    openrouter_complex_model: str = "nvidia/nemotron-3-ultra-550b-a55b:free"

    # Generic OpenAI-compatible (Cerebras, Together AI, etc.)
    openai_compat_base_url: str = ""
    openai_compat_api_key: str = ""
    openai_compat_simple_model: str = ""
    openai_compat_medium_model: str = ""
    openai_compat_complex_model: str = ""

    # Database & Cache
    database_url: str = "postgresql+asyncpg://smartrouter:smartrouter@localhost:5432/smartrouter"
    redis_url: str = "redis://localhost:6379"

    # App
    log_level: str = "INFO"
    cors_origins: str = "*"          # comma-separated list or "*"
    rate_limit: str = "60/minute"    # per client IP, applied to every route
    # Optional shared secret. When set, /v1/* and /analytics require
    # "Authorization: Bearer <key>" (or "X-API-Key: <key>").
    router_api_key: str = ""

    class Config:
        env_file = ".env"
        case_sensitive = False

    # Railway (and most cloud hosts) inject DATABASE_URL as postgresql://
    # SQLAlchemy async requires postgresql+asyncpg://
    @field_validator("database_url", mode="before")
    @classmethod
    def fix_db_scheme(cls, v: str) -> str:
        if v and v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        if v and v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+asyncpg://", 1)
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()


# ─── Reference Pricing (USD per 1M tokens) ───────────────────────────────────
# Hard-coded list prices. Groq prices checked 2026-11-02 at
# console.groq.com/docs/models; GPT-4o is OpenAI's list price. Ollama prices are
# assumptions for local inference, not quotes.
MODEL_PRICING: dict[str, dict[str, float]] = {
    # Ollama (local — assumed near-zero cost)
    "llama3.2:1b":       {"input": 0.01,  "output": 0.01},
    "llama3.1:8b":       {"input": 0.05,  "output": 0.05},
    "llama3.1:70b":      {"input": 0.59,  "output": 0.79},
    # Groq
    "openai/gpt-oss-20b":  {"input": 0.075, "output": 0.30},
    "openai/gpt-oss-120b": {"input": 0.15,  "output": 0.60},
    # Baseline reference
    "gpt-4o":            {"input": 2.50,  "output": 10.00},
}
# Any OpenRouter model ID ending in ":free" is priced at 0 (see calculate_cost).

BASELINE_MODEL = "gpt-4o"


def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    if model.endswith(":free"):
        return 0.0
    # Unknown models are priced as the baseline, so they show no saving.
    pricing = MODEL_PRICING.get(model, MODEL_PRICING[BASELINE_MODEL])
    return (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000
