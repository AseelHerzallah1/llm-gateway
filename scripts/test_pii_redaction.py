"""Demonstrate PII redaction offline and via the live gateway.

Usage:
    python scripts/test_pii_redaction.py
    python scripts/test_pii_redaction.py --output pii_output.txt

For live gateway test, set PII_REDACTION_ENABLED=true in .env, restart uvicorn,
then run with your API key:

    python scripts/test_pii_redaction.py gw-sk-your-key
    python scripts/test_pii_redaction.py --output pii_output.txt
"""

from __future__ import annotations

import asyncio
import os
import sys
from contextlib import contextmanager
from io import TextIOWrapper
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.security.pii import PiiRedactionConfig, detokenize_text, redact_text

# English labels — RTL text often renders backwards in PowerShell; data is still correct.
_OFFLINE_SAMPLES: list[tuple[str, str, PiiRedactionConfig | None]] = [
    ("English email", "Contact me at user@example.com", None),
    ("Arabic + email (RTL)", "راسلني على user@example.com من فضلك", None),
    ("Hebrew + Israeli phone (RTL)", "הטלפון שלי הוא 050-1234567", None),
    ("Arabic + Arabic-Indic digits", "اتصل على ٠٥٠-١٢٣٤٥٦٧", None),
    (
        "Credit card (opt-in)",
        "Charge 4111 1111 1111 1111",
        PiiRedactionConfig(redact_credit_card=True),
    ),
    (
        "IBAN (opt-in)",
        "Wire to GB82 WEST 1234 5698 7654 32",
        PiiRedactionConfig(redact_iban=True),
    ),
]


class _AsciiOnlyWriter:
    """Wrap a text file so every character is 7-bit ASCII (Notepad-safe)."""

    def __init__(self, handle: TextIOWrapper) -> None:
        self._handle = handle

    def write(self, text: str) -> int:
        safe = text.encode("ascii", "backslashreplace").decode("ascii")
        return self._handle.write(safe)

    def flush(self) -> None:
        self._handle.flush()


def _ensure_utf8_stdio() -> None:
    """Avoid UnicodeEncodeError when PowerShell redirects stdout to a file."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, TextIOWrapper) and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _parse_args(argv: list[str]) -> tuple[str | None, str | None]:
    output_path: str | None = None
    api_key: str | None = None
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--output":
            if index + 1 >= len(argv):
                raise SystemExit("Usage: --output requires a file path")
            output_path = argv[index + 1]
            index += 2
            continue
        if not arg.startswith("-") and api_key is None:
            api_key = arg
        index += 1
    return api_key, output_path


@contextmanager
def _capture_output(output_path: str | None):
    if not output_path:
        _ensure_utf8_stdio()
        yield False
        return

    destination = Path(output_path)
    real_stdout = sys.stdout
    with destination.open("w", encoding="ascii", newline="\n") as handle:
        sys.stdout = _AsciiOnlyWriter(handle)
        try:
            yield True
        finally:
            sys.stdout = real_stdout
    print(f"Saved report: {destination.resolve()}", file=real_stdout)
    print("Open in Notepad or any editor - file is plain ASCII.", file=real_stdout)


def _show(text: str, *, ascii_safe: bool) -> str:
    """repr() for terminal; ascii() for files (Notepad-safe Unicode escapes)."""
    return ascii(text) if ascii_safe else repr(text)


def _show_map(token_map: dict[str, str], *, ascii_safe: bool) -> str:
    if not ascii_safe:
        return str(token_map)
    inner = ", ".join(f"{ascii(key)}: {ascii(value)}" for key, value in token_map.items())
    return "{" + inner + "}"


def _pii_enabled_in_env() -> bool:
    from dotenv import load_dotenv

    load_dotenv()
    return os.getenv("PII_REDACTION_ENABLED", "false").lower() in ("1", "true", "yes")


def offline_demo(*, ascii_safe: bool = False) -> None:
    print("=== Offline PII redaction demo ===")
    if ascii_safe:
        print(
            "File mode: Arabic/Hebrew shown as \\uXXXX escapes (readable in Notepad).\n"
            "Run without --output in terminal to see real RTL text.\n"
        )
    else:
        print(
            "Note: Arabic/Hebrew may look 'backwards' in some terminals — "
            "that is an RTL display quirk, not bad data.\n"
        )

    for label, sample, sample_config in _OFFLINE_SAMPLES:
        result = redact_text(sample, config=sample_config or PiiRedactionConfig())
        print(f"[{label}]")
        print(f"  You typed:     {_show(sample, ascii_safe=ascii_safe)}")
        print(f"  Gateway sends: {_show(result.text, ascii_safe=ascii_safe)}")
        print(f"  Token map:     {_show_map(result.token_map, ascii_safe=ascii_safe)}\n")

    restored = detokenize_text(
        "We saved your email as [EMAIL_1].",
        {"[EMAIL_1]": "user@example.com"},
    )
    print(f"Detokenize example: {restored}\n")


async def live_gateway_test(api_key: str, *, ascii_safe: bool = False) -> None:
    print("=== Live gateway test ===\n")

    pii_on = _pii_enabled_in_env()
    if pii_on:
        print("PII_REDACTION_ENABLED=true in .env (uvicorn must be restarted after changing .env).")
    else:
        print("WARNING: PII_REDACTION_ENABLED is not true in .env.")
        print("  The provider will receive the RAW email until you enable it and restart uvicorn.\n")

    user_message = "Repeat this sentence exactly: My email is test.user@example.com"
    preview = redact_text(user_message)
    print("Your prompt (client → gateway):")
    print(f"  {user_message!r}")
    print("What the gateway WOULD send to OpenAI if redaction is ON:")
    print(f"  {preview.text!r}")
    print(f"  Token map (in memory only): {_show_map(preview.token_map, ascii_safe=ascii_safe)}\n")

    headers = {"Authorization": f"Bearer {api_key}"}
    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": user_message}],
        "stream": False,
        "max_tokens": 30,
    }

    async with httpx.AsyncClient(base_url="http://127.0.0.1:8001", timeout=60.0) as client:
        try:
            response = await client.post(
                "/v1/chat/completions",
                json=payload,
                headers=headers,
            )
        except httpx.ConnectError:
            print("Gateway not reachable at http://127.0.0.1:8001")
            print("Start uvicorn in Terminal 1, then re-run this script.")
            return

    if response.status_code != 200:
        print(f"Request failed: HTTP {response.status_code}")
        print(response.text)
        return

    content = response.json()["choices"][0]["message"]["content"]
    print(f"Response you see (gateway → client): {content!r}\n")

    print("--- How to read this ---")
    if not pii_on:
        print("• Redaction is OFF → OpenAI saw the real email test.user@example.com")
        print("• Fix: add PII_REDACTION_ENABLED=true to .env and restart uvicorn")
    elif "[EMAIL_1]" in content:
        print("• Redaction is ON, detokenize likely OFF → provider echoed the token")
        print("• OpenAI never received the raw email address")
    elif "test.user@example.com" in content:
        print("• Redaction is ON → OpenAI saw [EMAIL_1], not the raw email")
        print("• You still see the real email because PII_DETOKENIZE_RESPONSES=true")
        print("  restores tokens in the reply before returning to you")
    else:
        print("• Check uvicorn logs; model may have paraphrased instead of repeating")


async def _run(api_key: str | None, *, ascii_safe: bool = False) -> None:
    offline_demo(ascii_safe=ascii_safe)

    if not api_key:
        from dotenv import load_dotenv

        load_dotenv()
        api_key = os.getenv("GATEWAY_TEST_API_KEY", "")

    if api_key:
        await live_gateway_test(api_key, ascii_safe=ascii_safe)
    else:
        print("Skip live test — pass API key or set GATEWAY_TEST_API_KEY in .env")


def main() -> None:
    api_key, output_path = _parse_args(sys.argv[1:])
    with _capture_output(output_path) as ascii_safe:
        asyncio.run(_run(api_key, ascii_safe=ascii_safe))


if __name__ == "__main__":
    main()
