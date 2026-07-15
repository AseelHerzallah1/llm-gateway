"""Offline checks for SSE usage parsing."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.observability.sse_usage import parse_sse_usage


def main() -> None:
    chunk = (
        'data: {"usage":{"prompt_tokens":10,"completion_tokens":4,"total_tokens":14}}\n\n'
    )
    usage = parse_sse_usage(chunk)
    assert usage == (10, 4), usage
    assert parse_sse_usage("data: [DONE]") is None
    print("SSE usage parsing OK")


if __name__ == "__main__":
    main()
