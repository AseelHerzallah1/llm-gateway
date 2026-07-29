"""Demonstrate PII redaction offline and via the live gateway.

Usage:
    python scripts/test_pii_redaction.py

For live gateway test, set PII_REDACTION_ENABLED=true in .env, restart uvicorn,
then run with your API key:

    python scripts/test_pii_redaction.py gw-sk-your-key
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.security.pii import PiiRedactionConfig, detokenize_text, redact_text


def offline_demo() -> None:
    print("=== Offline PII redaction demo ===\n")

    samples = [
        "Contact me at aseel@example.com",
        "راسلني على user@example.com من فضلك",
        "הטלפון שלי הוא 050-1234567",
        "اتصل على ٠٥٠-١٢٣٤٥٦٧",
    ]

    config = PiiRedactionConfig()
    for sample in samples:
        result = redact_text(sample, config=config)
        print(f"Input:    {sample}")
        print(f"Redacted: {result.text}")
        print(f"Tokens:   {result.token_map}\n")

    restored = detokenize_text(
        "We saved your email as [EMAIL_1].",
        {"[EMAIL_1]": "user@example.com"},
    )
    print(f"Detokenize example: {restored}\n")


async def live_gateway_test(api_key: str) -> None:
    print("=== Live gateway test (PII_REDACTION_ENABLED must be true) ===\n")

    headers = {"Authorization": f"Bearer {api_key}"}
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {
                "role": "user",
                "content": (
                    "Repeat this sentence exactly: My email is test.user@example.com"
                ),
            }
        ],
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
    print(f"Gateway response: {content}")
    print(
        "\nIf redaction is enabled, the provider saw [EMAIL_1] instead of the raw email."
    )
    print("The client may still see the real email if detokenization is enabled.")


async def main() -> None:
    offline_demo()

    api_key = sys.argv[1] if len(sys.argv) > 1 else None
    if not api_key:
        from dotenv import load_dotenv

        load_dotenv()
        import os

        api_key = os.getenv("GATEWAY_TEST_API_KEY", "")

    if api_key:
        await live_gateway_test(api_key)
    else:
        print("Skip live test — pass API key or set GATEWAY_TEST_API_KEY in .env")


if __name__ == "__main__":
    asyncio.run(main())
