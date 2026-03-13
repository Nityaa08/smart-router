from pydantic import BaseModel
from typing import Literal


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    messages: list[Message]
    stream: bool = False
    force_tier: Literal["simple", "medium", "complex"] | None = None
    temperature: float = 0.7
    max_tokens: int | None = None
