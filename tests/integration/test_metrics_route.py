"""Integration tests for metrics endpoint."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.db.session import get_db
from app.main import app
from app.observability.metrics import MetricsResult


@pytest.mark.integration
@pytest.mark.asyncio
async def test_metrics_returns_aggregates(client, monkeypatch, test_project) -> None:
    since = datetime(2026, 1, 1, tzinfo=timezone.utc)
    until = datetime(2026, 1, 2, tzinfo=timezone.utc)
    fake_metrics = MetricsResult(
        since=since,
        until=until,
        total_requests=2,
        success_rate=1.0,
        cache_hit_rate=0.5,
        latency_p50=100,
        latency_p95=200,
        latency_p99=250,
        input_tokens=10,
        output_tokens=20,
        cost_usd=0.0001,
    )

    monkeypatch.setattr("app.routes.metrics.compute_metrics", AsyncMock(return_value=fake_metrics))

    async def override_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = override_db

    try:
        response = await client.get(
            "/v1/metrics",
            headers={"Authorization": "Bearer gw-sk-test-key"},
        )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_requests"] == 2
    assert payload["latency_ms"]["p95"] == 200
    assert payload["tokens"]["input"] == 10
