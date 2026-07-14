"""Pydantic schemas for chat completions — OpenAI-compatible."""

from pydantic import BaseModel, Field


class ChatMessageSchema(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessageSchema]
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = Field(default=None, ge=1)


class ChatMessageResponse(BaseModel):
    role: str = "assistant"
    content: str


class ChatChoice(BaseModel):
    index: int
    message: ChatMessageResponse
    finish_reason: str | None


class Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[ChatChoice]
    usage: Usage
