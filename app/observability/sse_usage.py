"""Parse token usage from OpenAI SSE events."""

from __future__ import annotations

import json


def parse_sse_usage(sse_event: str) -> tuple[int, int] | None:
    """Extract (input_tokens, output_tokens) from a streaming usage chunk."""
    line = sse_event.strip()
    if not line.startswith("data: "):
        return None

    payload = line[6:]
    if payload == "[DONE]":
        return None

    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None

    usage = data.get("usage")
    if not isinstance(usage, dict):
        return None

    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    if prompt is None and completion is None:
        return None

    return int(prompt or 0), int(completion or 0)
