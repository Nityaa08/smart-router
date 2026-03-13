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
    groq_simple_model: str = "llama3-8b-8192"
    groq_medium_model: str = "llama3-70b-8192"
    groq_complex_model: str = "llama3-70b-8192"

    # OpenRouter (free models — sign up at openrouter.ai, no credit card)
    openrouter_api_key: str = ""
    openrouter_simple_model: str = "meta-llama/llama-3.2-1b-instruct:free"
    openrouter_medium_model: str = "meta-llama/llama-3.1-8b-instruct:free"
    openrouter_complex_model: str = "meta-llama/llama-3.1-8b-instruct:free"

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
    rate_limit: str = "60/minute"

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
MODEL_PRICING: dict[str, dict[str, float]] = {
    # Ollama (local — near-zero cost)
    "llama3.2:1b":       {"input": 0.01,  "output": 0.01},
    "llama3.1:8b":       {"input": 0.05,  "output": 0.05},
    "llama3.1:70b":      {"input": 0.59,  "output": 0.79},
    # Groq
    "llama3-8b-8192":    {"input": 0.05,  "output": 0.08},
    "llama3-70b-8192":   {"input": 0.59,  "output": 0.79},
    # OpenRouter free models
    "meta-llama/llama-3.2-1b-instruct:free": {"input": 0.0,  "output": 0.0},
    "meta-llama/llama-3.1-8b-instruct:free": {"input": 0.0,  "output": 0.0},
    # Baseline reference
    "gpt-4o":            {"input": 2.50,  "output": 10.00},
}

BASELINE_MODEL = "gpt-4o"


def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    pricing = MODEL_PRICING.get(model, MODEL_PRICING["gpt-4o"])
    return (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000
