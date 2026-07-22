"""Pydantic schemas for request log listing."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class RequestLogItem(BaseModel):
    id: UUID
    created_at: datetime
    model: str
    status: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    cost_usd: float = Field(ge=0.0)
    cache_hit: bool


class RequestListResponse(BaseModel):
    total: int
    items: list[RequestLogItem]
