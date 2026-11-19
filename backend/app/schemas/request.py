from pydantic import BaseModel, Field, field_validator
from typing import Literal


class TextPart(BaseModel):
    type: Literal["text"]
    text: str


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str

    @field_validator("content", mode="before")
    @classmethod
    def join_text_parts(cls, value):
        """Accept OpenAI's list form of content and store it as one string.

        OpenAI-compatible clients may send content as
        [{"type": "text", "text": "..."}]; those requests used to get a 422. Text
        parts are joined with a newline, so the classifier, the cache key and every
        provider see the same plain string. Image and audio parts are refused with a
        message saying so, since no tier here takes them.
        """
        if not isinstance(value, list):
            return value
        if not value:
            raise ValueError("content must not be an empty list")
        texts = []
        for part in value:
            kind = part.get("type") if isinstance(part, dict) else None
            if kind != "text":
                raise ValueError(
                    f"only text content parts are supported, got type {kind!r}"
                )
            texts.append(TextPart.model_validate(part).text)
        return "\n".join(texts)


class ChatRequest(BaseModel):
    # The same bounds as the OpenAI API. Without them a request a provider will refuse
    # (no messages, temperature 5, max_tokens -1) got past validation, was tried on every
    # tier up to the most expensive model, and came back as a 503 blaming the providers.
    messages: list[Message] = Field(min_length=1)
    stream: bool = False
    force_tier: Literal["simple", "medium", "complex"] | None = None
    temperature: float = Field(0.7, ge=0, le=2)
    max_tokens: int | None = Field(None, ge=1)
