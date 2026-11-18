from pydantic import BaseModel, Field
from typing import Literal


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    # The same bounds as the OpenAI API. Without them a request a provider will refuse
    # (no messages, temperature 5, max_tokens -1) got past validation, was tried on every
    # tier up to the most expensive model, and came back as a 503 blaming the providers.
    messages: list[Message] = Field(min_length=1)
    stream: bool = False
    force_tier: Literal["simple", "medium", "complex"] | None = None
    temperature: float = Field(0.7, ge=0, le=2)
    max_tokens: int | None = Field(None, ge=1)
