"""Pydantic schemas for metrics endpoints."""

from datetime import datetime

from pydantic import BaseModel, Field


class MetricsWindow(BaseModel):
    since: datetime
    until: datetime


class LatencyPercentiles(BaseModel):
    p50: int
    p95: int
    p99: int


class TokenTotals(BaseModel):
    input: int
    output: int


class MetricsResponse(BaseModel):
    window: MetricsWindow
    total_requests: int
    success_rate: float = Field(ge=0.0, le=1.0)
    cache_hit_rate: float = Field(ge=0.0, le=1.0)
    latency_ms: LatencyPercentiles
    tokens: TokenTotals
    cost_usd: float = Field(ge=0.0)
