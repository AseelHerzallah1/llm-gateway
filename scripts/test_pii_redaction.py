"""Demonstrate PII redaction offline and via the live gateway.

Usage:
    python scripts/test_pii_redaction.py

For live gateway test, set PII_REDACTION_ENABLED=true in .env, restart uvicorn,
then run with your API key:

    python scripts/test_pii_redaction.py gw-sk-your-key
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.security.pii import PiiRedactionConfig, detokenize_text, redact_text

# English labels — RTL text often renders backwards in PowerShell; data is still correct.
_OFFLINE_SAMPLES: list[tuple[str, str]] = [
    ("English email", "Contact me at aseel@example.com"),
    ("Arabic + email (RTL)", "راسلني على user@example.com من فضلك"),
    ("Hebrew + Israeli phone (RTL)", "הטלפון שלי הוא 050-1234567"),
    ("Arabic + Arabic-Indic digits", "اتصل على ٠٥٠-١٢٣٤٥٦٧"),
]


def _pii_enabled_in_env() -> bool:
    from dotenv import load_dotenv

    load_dotenv()
    return os.getenv("PII_REDACTION_ENABLED", "false").lower() in ("1", "true", "yes")


def offline_demo() -> None:
    print("=== Offline PII redaction demo ===")
    print(
        "Note: Arabic/Hebrew lines may look 'backwards' in PowerShell — "
        "that is a terminal display quirk (RTL in an LTR console), not bad data.\n"
    )

    config = PiiRedactionConfig()
    for label, sample in _OFFLINE_SAMPLES:
        result = redact_text(sample, config=config)
        print(f"[{label}]")
        print(f"  You typed:     {sample!r}")
        print(f"  Gateway sends: {result.text!r}")
        print(f"  Token map:     {result.token_map}\n")

    restored = detokenize_text(
        "We saved your email as [EMAIL_1].",
        {"[EMAIL_1]": "user@example.com"},
    )
    print(f"Detokenize example: {restored}\n")


async def live_gateway_test(api_key: str) -> None:
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
    print(f"  Token map (in memory only): {preview.token_map}\n")

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


async def main() -> None:
    offline_demo()

    api_key = sys.argv[1] if len(sys.argv) > 1 else None
    if not api_key:
        from dotenv import load_dotenv

        load_dotenv()
        api_key = os.getenv("GATEWAY_TEST_API_KEY", "")

    if api_key:
        await live_gateway_test(api_key)
    else:
        print("Skip live test — pass API key or set GATEWAY_TEST_API_KEY in .env")


if __name__ == "__main__":
    asyncio.run(main())
