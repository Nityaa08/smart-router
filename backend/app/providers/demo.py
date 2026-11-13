"""
Demo provider: no network, no API key, no model.

Used by the public demo (PROVIDER=demo). It returns a clearly labelled
simulated answer so the rest of the gateway (classification, routing,
fallback, cost estimate, cache and analytics) runs for real without paying
for, or leaking, an LLM key. Token counts are estimates (about 4 characters a
token for the prompt, a fixed typical answer length per tier), so the cost
figures in demo mode are illustrations of the pricing logic, not measurements.
"""
import asyncio
from typing import AsyncIterator

from .base import LLMProvider, LLMResponse, LLMUsage

# Typical answer length per tier, used only to estimate output tokens.
DEMO_OUTPUT_TOKENS = {"simple": 120, "medium": 400, "complex": 900}

DEMO_LABEL = "[Simulated response - demo mode, no language model was called]"


def _estimate_tokens(messages: list[dict]) -> int:
    text = " ".join(str(m.get("content", "")) for m in messages)
    return max(1, len(text) // 4)


class DemoProvider(LLMProvider):
    def __init__(self, model: str, tier: str):
        self._model = model
        self._tier = tier

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def provider_name(self) -> str:
        return "demo"

    def _answer(self, messages: list[dict]) -> str:
        last = next(
            (str(m.get("content", "")) for m in reversed(messages) if m.get("role") == "user"),
            "",
        )
        preview = " ".join(last.split())
        if len(preview) > 140:
            preview = preview[:137] + "..."
        return (
            f"{DEMO_LABEL}\n\n"
            f"The router classified this prompt as {self._tier} and sent it to the "
            f"{self._tier} tier, which is configured as {self._model}. In a live deployment "
            f"that model would answer here.\n\n"
            f"Prompt received: \"{preview}\""
        )

    async def complete(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        output_tokens = DEMO_OUTPUT_TOKENS.get(self._tier, 400)
        if max_tokens:
            output_tokens = min(output_tokens, max_tokens)
        return LLMResponse(
            content=self._answer(messages),
            model=self._model,
            usage=LLMUsage(input_tokens=_estimate_tokens(messages), output_tokens=output_tokens),
            raw={"simulated": True},
        )

    async def stream(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        for word in self._answer(messages).split(" "):
            await asyncio.sleep(0)
            yield word + " "

    async def health_check(self) -> bool:
        return True
