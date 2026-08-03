"""Build an HTML report for portfolio screenshots (RTL + streaming render correctly).

Usage:
    python scripts/generate_screenshot_report.py

Requires server + GATEWAY_TEST_API_KEY for live streaming/cache sections.
PII section always works offline.

Output:
    docs/portfolio/report.html  (open in Chrome/Edge and screenshot)
"""

from __future__ import annotations

import asyncio
import html
import sys
import time
import uuid
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.security.pii import PiiRedactionConfig, redact_text

BASE_URL = "http://127.0.0.1:8001"
REPORT_PATH = Path(__file__).resolve().parent.parent / "docs" / "portfolio" / "report.html"

_PII_SAMPLES: list[tuple[str, str, str, PiiRedactionConfig | None]] = [
    ("English email", "ltr", "Contact me at user@example.com", None),
    ("Arabic + email", "rtl", "راسلني على user@example.com من فضلك", None),
    ("Hebrew + phone", "rtl", "הטלפון שלי הוא 050-1234567", None),
    ("Arabic-Indic phone", "rtl", "اتصل على ٠٥٠-١٢٣٤٥٦٧", None),
    (
        "Credit card (opt-in)",
        "ltr",
        "Charge 4111 1111 1111 1111",
        PiiRedactionConfig(redact_credit_card=True),
    ),
    (
        "IBAN (opt-in)",
        "ltr",
        "Wire to GB82 WEST 1234 5698 7654 32",
        PiiRedactionConfig(redact_iban=True),
    ),
]


def _resolve_api_key() -> str:
    from dotenv import load_dotenv

    load_dotenv()
    import os

    return os.getenv("GATEWAY_TEST_API_KEY", "")


def _pii_rows() -> str:
    rows: list[str] = []
    for label, direction, sample, sample_config in _PII_SAMPLES:
        result = redact_text(sample, config=sample_config or PiiRedactionConfig())
        rows.append(
            "<tr>"
            f"<td>{html.escape(label)}</td>"
            f'<td dir="{direction}">{html.escape(sample)}</td>'
            f'<td dir="{direction}">{html.escape(result.text)}</td>'
            f"<td><code>{html.escape(str(result.token_map))}</code></td>"
            "</tr>"
        )
    return "\n".join(rows)


async def _capture_stream(headers: dict[str, str]) -> tuple[list[str], int, bool]:
    lines: list[str] = []
    saw_done = False
    event_count = 0
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
        async with client.stream(
            "POST",
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "Count from 1 to 3."}],
                "stream": True,
                "max_tokens": 20,
            },
            headers=headers,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line:
                    continue
                event_count += 1
                if len(lines) < 6:
                    preview = line if len(line) <= 100 else line[:100] + "..."
                    lines.append(preview)
                if line.strip() == "data: [DONE]":
                    saw_done = True
                    break
    return lines, event_count, saw_done


async def _capture_cache(headers: dict[str, str]) -> tuple[str, str, int, int, bool]:
    token = uuid.uuid4().hex[:8]
    prompt = f"What is 2+2? Reply with the digit only. ({token})"
    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "max_tokens": 5,
    }
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
        started = time.perf_counter()
        first = await client.post("/v1/chat/completions", json=payload, headers=headers)
        first_ms = int((time.perf_counter() - started) * 1000)
        first.raise_for_status()
        first_text = first.json()["choices"][0]["message"]["content"]

        started = time.perf_counter()
        second = await client.post("/v1/chat/completions", json=payload, headers=headers)
        second_ms = int((time.perf_counter() - started) * 1000)
        second.raise_for_status()
        second_text = second.json()["choices"][0]["message"]["content"]

    return first_text, second_text, first_ms, second_ms, first_text == second_text


async def _capture_metrics(headers: dict[str, str]) -> dict | None:
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        response = await client.get("/v1/metrics", headers=headers)
        if response.status_code != 200:
            return None
        return response.json()


def _render_html(
    *,
    pii_rows: str,
    live_ok: bool,
    stream_lines: list[str],
    stream_events: int,
    stream_done: bool,
    cache_first: str,
    cache_second: str,
    cache_first_ms: int,
    cache_second_ms: int,
    cache_same: bool,
    metrics: dict | None,
) -> str:
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    stream_block = (
        "<pre>" + html.escape("\n".join(stream_lines)) + "</pre>"
        if stream_lines
        else "<p class='muted'>Start uvicorn and re-run to capture live SSE chunks.</p>"
    )
    stream_meta = (
        f"events={stream_events}, saw_done={stream_done}"
        if stream_lines
        else "offline"
    )

    if cache_first:
        cache_block = (
            f"<p><strong>First request (miss):</strong> {html.escape(cache_first)!s} "
            f"— <code>{cache_first_ms} ms</code></p>"
            f"<p><strong>Second request (hit):</strong> {html.escape(cache_second)!s} "
            f"— <code>{cache_second_ms} ms</code></p>"
            f"<p>Same content: <strong>{cache_same}</strong></p>"
        )
    else:
        cache_block = "<p class='muted'>Start uvicorn and re-run to capture cache timings.</p>"

    if metrics:
        latency = metrics.get("latency_ms", {})
        metrics_block = (
            "<ul>"
            f"<li>Total requests: <strong>{metrics.get('total_requests')}</strong></li>"
            f"<li>Success rate: <strong>{metrics.get('success_rate')}</strong></li>"
            f"<li>Cache hit rate: <strong>{metrics.get('cache_hit_rate')}</strong></li>"
            f"<li>P50 / P95 / P99: "
            f"<strong>{latency.get('p50')}</strong> / "
            f"<strong>{latency.get('p95')}</strong> / "
            f"<strong>{latency.get('p99')}</strong> ms</li>"
            "</ul>"
            "<p class='muted'>Full UI: http://127.0.0.1:8001/dashboard</p>"
        )
    else:
        metrics_block = "<p class='muted'>Metrics unavailable — run with server up.</p>"

    live_note = (
        "<p class='ok'>Live gateway data captured.</p>"
        if live_ok
        else "<p class='warn'>PII section is offline. Start server for streaming/cache/metrics.</p>"
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>LLM Gateway — Portfolio Report</title>
  <style>
    :root {{
      --bg: #0f1419; --panel: #1a2332; --text: #e7ecf3; --muted: #8b98a8;
      --accent: #3b82f6; --border: #2a3544; --ok: #22c55e; --warn: #f59e0b;
    }}
    body {{ margin: 0; font-family: ui-sans-serif, system-ui, sans-serif;
      background: var(--bg); color: var(--text); line-height: 1.5; }}
    main {{ max-width: 960px; margin: 0 auto; padding: 2rem 1.25rem 3rem; }}
    h1 {{ margin: 0 0 0.25rem; font-size: 1.75rem; }}
    h2 {{ margin: 2rem 0 0.75rem; font-size: 1.15rem; color: var(--accent); }}
    .subtitle {{ color: var(--muted); margin-bottom: 1.5rem; }}
    .panel {{ background: var(--panel); border: 1px solid var(--border);
      border-radius: 10px; padding: 1rem 1.25rem; margin-bottom: 1rem; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.95rem; }}
    th, td {{ border: 1px solid var(--border); padding: 0.55rem 0.65rem; vertical-align: top; }}
    th {{ text-align: left; background: #121a26; }}
    pre {{ background: #121a26; border: 1px solid var(--border); border-radius: 8px;
      padding: 0.75rem; overflow-x: auto; font-size: 0.82rem; white-space: pre-wrap; }}
    code {{ font-family: ui-monospace, monospace; font-size: 0.85em; }}
    .muted {{ color: var(--muted); }}
    .ok {{ color: var(--ok); }}
    .warn {{ color: var(--warn); }}
    .rtl {{ direction: rtl; text-align: right; }}
  </style>
</head>
<body>
  <main>
    <h1>LLM Gateway — Portfolio Report</h1>
    <p class="subtitle">Generated {generated} · Sample demo report — metrics reflect one local run</p>
    {live_note}

    <h2>Phase 9 — PII redaction (Arabic / Hebrew / Latin)</h2>
    <div class="panel">
      <p>When <code>PII_REDACTION_ENABLED=true</code> (non-streaming), supported patterns become tokens like <code>[EMAIL_1]</code> before the provider and cache. Streaming is not redacted; optional detokenize restores values to the client.</p>
      <table>
        <thead>
          <tr><th>Case</th><th>Client sends</th><th>Gateway forwards</th><th>Token map</th></tr>
        </thead>
        <tbody>
          {pii_rows}
        </tbody>
      </table>
    </div>

    <h2>Streaming proxy (SSE chunks)</h2>
    <div class="panel">
      <p class="muted">{stream_meta}</p>
      {stream_block}
    </div>

    <h2>Semantic cache (same prompt twice)</h2>
    <div class="panel">
      {cache_block}
    </div>

    <h2>Observability snapshot</h2>
    <div class="panel">
      {metrics_block}
    </div>
  </main>
</body>
</html>
"""


async def main() -> None:
    pii_rows = _pii_rows()
    api_key = _resolve_api_key()
    live_ok = False
    stream_lines: list[str] = []
    stream_events = 0
    stream_done = False
    cache_first = cache_second = ""
    cache_first_ms = cache_second_ms = 0
    cache_same = False
    metrics: dict | None = None

    if api_key:
        headers = {"Authorization": f"Bearer {api_key}"}
        try:
            async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as client:
                health = await client.get("/health")
                health.raise_for_status()
            stream_lines, stream_events, stream_done = await _capture_stream(headers)
            cache_first, cache_second, cache_first_ms, cache_second_ms, cache_same = (
                await _capture_cache(headers)
            )
            metrics = await _capture_metrics(headers)
            live_ok = True
        except (httpx.ConnectError, httpx.HTTPError):
            pass

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        _render_html(
            pii_rows=pii_rows,
            live_ok=live_ok,
            stream_lines=stream_lines,
            stream_events=stream_events,
            stream_done=stream_done,
            cache_first=cache_first,
            cache_second=cache_second,
            cache_first_ms=cache_first_ms,
            cache_second_ms=cache_second_ms,
            cache_same=cache_same,
            metrics=metrics,
        ),
        encoding="utf-8",
    )

    uri = REPORT_PATH.resolve().as_uri()
    print(f"Report saved: {REPORT_PATH.resolve()}")
    print(f"Opening in browser: {uri}")
    webbrowser.open(uri)


if __name__ == "__main__":
    asyncio.run(main())
