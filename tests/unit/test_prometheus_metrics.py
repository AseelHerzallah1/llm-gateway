"""Unit tests for Prometheus metrics instrumentation."""

from __future__ import annotations

import pytest
from prometheus_client import CollectorRegistry, generate_latest

from app.observability.prometheus_metrics import (
    GatewayPrometheusMetrics,
    reset_prometheus_metrics_for_tests,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def metrics() -> GatewayPrometheusMetrics:
    return reset_prometheus_metrics_for_tests(CollectorRegistry())


def _metric_value(payload: bytes, name: str, labels: str = "") -> float:
    needle = f"{name}{labels}"
    for line in payload.decode().splitlines():
        if line.startswith(needle + " "):
            return float(line.rsplit(" ", 1)[1])
    raise AssertionError(f"Metric not found: {needle}")


def test_record_request_increments_counters_and_histogram(metrics: GatewayPrometheusMetrics) -> None:
    metrics.record_request(
        status="success",
        stream=False,
        cache_result="miss",
        duration_seconds=0.25,
        input_tokens=10,
        output_tokens=5,
        cost_usd=0.001,
    )

    payload = generate_latest(metrics.registry)
    assert _metric_value(
        payload,
        "llmgateway_requests_total",
        '{cache_result="miss",status="success",stream="false"}',
    ) == 1.0
    assert _metric_value(payload, "llmgateway_tokens_total", '{direction="input"}') == 10.0
    assert _metric_value(payload, "llmgateway_tokens_total", '{direction="output"}') == 5.0
    assert _metric_value(payload, "llmgateway_estimated_cost_usd_total") == 0.001
    assert "llmgateway_request_duration_seconds_bucket" in payload.decode()


def test_cache_operations(metrics: GatewayPrometheusMetrics) -> None:
    for result in (
        "exact_hit",
        "semantic_hit",
        "semantic_reject",
        "semantic_miss",
        "semantic_skipped",
        "store",
        "lookup_skipped",
    ):
        metrics.record_cache_operation(result)

    payload = generate_latest(metrics.registry)
    for result in (
        "exact_hit",
        "semantic_hit",
        "semantic_reject",
        "semantic_miss",
        "semantic_skipped",
        "store",
        "lookup_skipped",
    ):
        assert (
            _metric_value(
                payload,
                "llmgateway_cache_operations_total",
                f'{{result="{result}"}}',
            )
            == 1.0
        )


def test_provider_attempt_retry_and_fallback(metrics: GatewayPrometheusMetrics) -> None:
    metrics.record_provider_attempt(provider="openai", status="error", duration_seconds=0.1)
    metrics.record_provider_attempt(provider="openai", status="success", duration_seconds=0.2)
    metrics.record_provider_retry("openai")
    metrics.record_provider_fallback(from_provider="groq", to_provider="openai")

    payload = generate_latest(metrics.registry)
    assert (
        _metric_value(
            payload,
            "llmgateway_provider_requests_total",
            '{provider="openai",status="error"}',
        )
        == 1.0
    )
    assert (
        _metric_value(
            payload,
            "llmgateway_provider_retries_total",
            '{provider="openai"}',
        )
        == 1.0
    )
    assert (
        _metric_value(
            payload,
            "llmgateway_provider_fallbacks_total",
            '{from_provider="groq",to_provider="openai"}',
        )
        == 1.0
    )


def test_streaming_label_is_bounded_string(metrics: GatewayPrometheusMetrics) -> None:
    metrics.record_request(
        status="success",
        stream=True,
        cache_result="none",
        duration_seconds=0.05,
    )
    payload = generate_latest(metrics.registry)
    assert (
        _metric_value(
            payload,
            "llmgateway_requests_total",
            '{cache_result="none",status="success",stream="true"}',
        )
        == 1.0
    )


@pytest.mark.parametrize(
    ("method", "args", "kwargs"),
    [
        ("record_request", (), {"status": "oops", "stream": False, "cache_result": "miss", "duration_seconds": 1}),
        ("record_cache_operation", ("unknown",), {}),
        ("record_provider_attempt", (), {"provider": "azure", "status": "success", "duration_seconds": 1}),
        ("record_provider_retry", ("bad-provider",), {}),
        (
            "record_provider_fallback",
            (),
            {"from_provider": "openai", "to_provider": "gpt-4o-mini"},
        ),
    ],
)
def test_rejects_unbounded_labels(metrics: GatewayPrometheusMetrics, method, args, kwargs) -> None:
    with pytest.raises(ValueError):
        getattr(metrics, method)(*args, **kwargs)


def test_no_model_or_project_in_exposition(metrics: GatewayPrometheusMetrics) -> None:
    metrics.record_request(
        status="success",
        stream=False,
        cache_result="miss",
        duration_seconds=0.1,
        input_tokens=1,
        output_tokens=1,
        cost_usd=0.01,
    )
    text = generate_latest(metrics.registry).decode()
    assert "model" not in text
    assert "project" not in text
    assert "api_key" not in text
