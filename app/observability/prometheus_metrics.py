"""Prometheus operational metrics — additive to PostgreSQL request logging."""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Iterator

from prometheus_client import REGISTRY, CollectorRegistry, Counter, Histogram

REQUEST_DURATION_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)
PROVIDER_DURATION_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)

VALID_REQUEST_STATUS = frozenset({"success", "error"})
VALID_STREAM = frozenset({"true", "false"})
VALID_CACHE_RESULT = frozenset({"exact_hit", "semantic_hit", "miss", "bypass", "none"})
VALID_CACHE_OPERATION = frozenset({
    "exact_hit",
    "semantic_hit",
    "semantic_reject",
    "semantic_miss",
    "semantic_skipped",
    "store",
    "lookup_skipped",
})
VALID_PROVIDER = frozenset({"openai", "groq", "anthropic"})
VALID_TOKEN_DIRECTION = frozenset({"input", "output"})


def _validate(label: str, value: str, allowed: frozenset[str]) -> str:
    if value not in allowed:
        raise ValueError(f"Invalid Prometheus label {label}={value!r}")
    return value


class GatewayPrometheusMetrics:
    """Registry-backed Prometheus metrics with bounded label enums."""

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry or REGISTRY
        self.requests_total = Counter(
            "llmgateway_requests_total",
            "Completed gateway chat completion requests",
            ["status", "stream", "cache_result"],
            registry=self.registry,
        )
        self.request_duration_seconds = Histogram(
            "llmgateway_request_duration_seconds",
            "Gateway chat completion request duration in seconds",
            ["status", "stream", "cache_result"],
            buckets=REQUEST_DURATION_BUCKETS,
            registry=self.registry,
        )
        self.cache_operations_total = Counter(
            "llmgateway_cache_operations_total",
            "Semantic cache operations",
            ["result"],
            registry=self.registry,
        )
        self.provider_requests_total = Counter(
            "llmgateway_provider_requests_total",
            "Provider HTTP attempts (includes retries)",
            ["provider", "status"],
            registry=self.registry,
        )
        self.provider_request_duration_seconds = Histogram(
            "llmgateway_provider_request_duration_seconds",
            "Provider attempt duration in seconds",
            ["provider", "status"],
            buckets=PROVIDER_DURATION_BUCKETS,
            registry=self.registry,
        )
        self.provider_retries_total = Counter(
            "llmgateway_provider_retries_total",
            "Provider retry attempts after transient failures",
            ["provider"],
            registry=self.registry,
        )
        self.provider_fallbacks_total = Counter(
            "llmgateway_provider_fallbacks_total",
            "Provider fallback activations",
            ["from_provider", "to_provider"],
            registry=self.registry,
        )
        self.tokens_total = Counter(
            "llmgateway_tokens_total",
            "Token usage observed by the gateway",
            ["direction"],
            registry=self.registry,
        )
        self.estimated_cost_usd_total = Counter(
            "llmgateway_estimated_cost_usd_total",
            "Estimated provider spend (operational counter; PostgreSQL is authoritative for history)",
            registry=self.registry,
        )

    def record_request(
        self,
        *,
        status: str,
        stream: bool,
        cache_result: str,
        duration_seconds: float,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
    ) -> None:
        status_label = _validate("status", status, VALID_REQUEST_STATUS)
        stream_label = _validate("stream", str(stream).lower(), VALID_STREAM)
        cache_label = _validate("cache_result", cache_result, VALID_CACHE_RESULT)
        labels = {
            "status": status_label,
            "stream": stream_label,
            "cache_result": cache_label,
        }
        self.requests_total.labels(**labels).inc()
        self.request_duration_seconds.labels(**labels).observe(duration_seconds)
        if input_tokens:
            self.tokens_total.labels(direction="input").inc(input_tokens)
        if output_tokens:
            self.tokens_total.labels(direction="output").inc(output_tokens)
        if cost_usd > 0:
            self.estimated_cost_usd_total.inc(cost_usd)

    def record_cache_operation(self, result: str) -> None:
        label = _validate("result", result, VALID_CACHE_OPERATION)
        self.cache_operations_total.labels(result=label).inc()

    def record_provider_attempt(
        self,
        *,
        provider: str,
        status: str,
        duration_seconds: float,
    ) -> None:
        provider_label = _validate("provider", provider, VALID_PROVIDER)
        status_label = _validate("status", status, VALID_REQUEST_STATUS)
        self.provider_requests_total.labels(
            provider=provider_label,
            status=status_label,
        ).inc()
        self.provider_request_duration_seconds.labels(
            provider=provider_label,
            status=status_label,
        ).observe(duration_seconds)

    def record_provider_retry(self, provider: str) -> None:
        provider_label = _validate("provider", provider, VALID_PROVIDER)
        self.provider_retries_total.labels(provider=provider_label).inc()

    def record_provider_fallback(self, *, from_provider: str, to_provider: str) -> None:
        from_label = _validate("from_provider", from_provider, VALID_PROVIDER)
        to_label = _validate("to_provider", to_provider, VALID_PROVIDER)
        self.provider_fallbacks_total.labels(
            from_provider=from_label,
            to_provider=to_label,
        ).inc()


_metrics: GatewayPrometheusMetrics | None = None


def get_prometheus_metrics() -> GatewayPrometheusMetrics:
    """Return the process-wide metrics instance."""
    global _metrics
    if _metrics is None:
        _metrics = GatewayPrometheusMetrics()
    return _metrics


def reset_prometheus_metrics_for_tests(registry: CollectorRegistry | None = None) -> GatewayPrometheusMetrics:
    """Install an isolated registry for tests."""
    global _metrics
    _metrics = GatewayPrometheusMetrics(registry=registry or CollectorRegistry())
    return _metrics


@contextmanager
def observe_provider_attempt(provider: str) -> Iterator[None]:
    """Time one provider attempt and record success/error on exit."""
    metrics = get_prometheus_metrics()
    started = time.perf_counter()
    status = "success"
    try:
        yield
    except Exception:
        status = "error"
        raise
    finally:
        metrics.record_provider_attempt(
            provider=provider,
            status=status,
            duration_seconds=time.perf_counter() - started,
        )
