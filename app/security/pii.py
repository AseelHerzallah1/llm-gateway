"""PII detection and redaction for chat prompts."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

PiiType = Literal["EMAIL", "PHONE", "CREDIT_CARD"]

# Simplified RFC5322 — works inside RTL/LTR mixed text (Unicode).
_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
    re.UNICODE,
)

# E.164-style, US local, and Israeli mobile/landline formats.
_PHONE_RES = (
    re.compile(r"\+[1-9](?:[\s.\-()]*\d){6,14}\d"),
    re.compile(
        r"(?<!\d)(?:\([0-9]{3}\)|[0-9]{3})[\s.\-][0-9]{3}[\s.\-][0-9]{4}(?!\d)",
    ),
    re.compile(r"(?<!\d)\+972[\s.\-]?\d{1,2}[\s.\-]?\d{3}[\s.\-]?\d{4}(?!\d)"),
    re.compile(r"(?<!\d)0\d{1,2}[\s.\-]?\d{3}[\s.\-]?\d{4}(?!\d)"),
)

# Digit groups with optional separators; Luhn validation filters false positives.
_CREDIT_CARD_CANDIDATE_RE = re.compile(
    r"(?<!\d)(?:\d[\s\-]?){12,18}\d(?!\d)",
)

_ARABIC_INDIC_ZERO = ord("٠")
_EXTENDED_ARABIC_INDIC_ZERO = ord("۰")


@dataclass(frozen=True)
class PiiRedactionConfig:
    """Which PII categories to redact in a single request."""

    redact_email: bool = True
    redact_phone: bool = True
    redact_credit_card: bool = False


@dataclass
class PiiRedactionResult:
    """Redacted text plus token → original map for optional detokenization."""

    text: str
    token_map: dict[str, str] = field(default_factory=dict)


@dataclass
class _Span:
    start: int
    end: int
    pii_type: PiiType
    value: str

    @property
    def length(self) -> int:
        return self.end - self.start


class _PiiRedactor:
    """Stateful redactor — reuses tokens for identical values within one request."""

    def __init__(self, config: PiiRedactionConfig) -> None:
        self._config = config
        self._token_map: dict[str, str] = {}
        self._value_tokens: dict[tuple[PiiType, str], str] = {}
        self._counters: dict[PiiType, int] = {"EMAIL": 0, "PHONE": 0, "CREDIT_CARD": 0}

    @property
    def token_map(self) -> dict[str, str]:
        return dict(self._token_map)

    def redact(self, text: str) -> str:
        if not text:
            return text

        spans = self._find_spans(text)
        if not spans:
            return text

        parts: list[str] = []
        cursor = 0
        for span in spans:
            parts.append(text[cursor : span.start])
            parts.append(self._token_for(span.pii_type, span.value))
            cursor = span.end
        parts.append(text[cursor:])
        return "".join(parts)

    def _find_spans(self, text: str) -> list[_Span]:
        candidates: list[_Span] = []
        normalized = _normalize_unicode_digits(text)

        if self._config.redact_email:
            for match in _EMAIL_RE.finditer(text):
                candidates.append(
                    _Span(match.start(), match.end(), "EMAIL", match.group()),
                )

        if self._config.redact_credit_card:
            for match in _CREDIT_CARD_CANDIDATE_RE.finditer(normalized):
                value = text[match.start() : match.end()]
                if _luhn_valid(value):
                    candidates.append(
                        _Span(match.start(), match.end(), "CREDIT_CARD", value),
                    )

        if self._config.redact_phone:
            for pattern in _PHONE_RES:
                for match in pattern.finditer(normalized):
                    value = text[match.start() : match.end()]
                    if _digit_count(_normalize_unicode_digits(value)) < 10:
                        continue
                    candidates.append(
                        _Span(match.start(), match.end(), "PHONE", value),
                    )

        return _merge_non_overlapping(candidates)

    def _token_for(self, pii_type: PiiType, value: str) -> str:
        key = (pii_type, _normalize_value(pii_type, value))
        if key in self._value_tokens:
            return self._value_tokens[key]

        self._counters[pii_type] += 1
        token = f"[{pii_type}_{self._counters[pii_type]}]"
        self._value_tokens[key] = token
        self._token_map[token] = value
        return token


def redact_text(
    text: str,
    config: PiiRedactionConfig | None = None,
) -> PiiRedactionResult:
    """Redact PII in a single string; returns redacted text and token map."""
    redactor = _PiiRedactor(config or PiiRedactionConfig())
    return PiiRedactionResult(text=redactor.redact(text), token_map=redactor.token_map)


def redact_messages(
    messages: list[dict[str, str]],
    config: PiiRedactionConfig | None = None,
) -> tuple[list[dict[str, str]], dict[str, str]]:
    """Redact `content` on each message; shared token map across the request."""
    redactor = _PiiRedactor(config or PiiRedactionConfig())
    redacted: list[dict[str, str]] = []
    for message in messages:
        updated = dict(message)
        content = message.get("content")
        if isinstance(content, str) and content:
            updated["content"] = redactor.redact(content)
        redacted.append(updated)
    return redacted, redactor.token_map


def detokenize_text(text: str, token_map: dict[str, str]) -> str:
    """Replace redaction tokens with original values (longest tokens first)."""
    if not text or not token_map:
        return text

    result = text
    for token in sorted(token_map, key=len, reverse=True):
        result = result.replace(token, token_map[token])
    return result


def _normalize_unicode_digits(text: str) -> str:
    """Map Arabic-Indic and Extended Arabic-Indic digits to ASCII (same length)."""
    chars: list[str] = []
    for char in text:
        code = ord(char)
        if 0x0660 <= code <= 0x0669:
            chars.append(chr(code - _ARABIC_INDIC_ZERO + ord("0")))
        elif 0x06F0 <= code <= 0x06F9:
            chars.append(chr(code - _EXTENDED_ARABIC_INDIC_ZERO + ord("0")))
        else:
            chars.append(char)
    return "".join(chars)


def _normalize_value(pii_type: PiiType, value: str) -> str:
    if pii_type == "EMAIL":
        return value.lower()
    if pii_type in ("PHONE", "CREDIT_CARD"):
        return re.sub(r"\D", "", _normalize_unicode_digits(value))
    return value


def _digit_count(value: str) -> int:
    return sum(ch.isdigit() for ch in value)


def _luhn_valid(value: str) -> bool:
    digits = [int(ch) for ch in _normalize_unicode_digits(value) if ch.isdigit()]
    if len(digits) < 13 or len(digits) > 19:
        return False

    checksum = 0
    parity = len(digits) % 2
    for index, digit in enumerate(digits):
        if index % 2 == parity:
            doubled = digit * 2
            checksum += doubled - 9 if doubled > 9 else doubled
        else:
            checksum += digit
    return checksum % 10 == 0


def _merge_non_overlapping(spans: list[_Span]) -> list[_Span]:
    """Keep highest-priority, longest spans when patterns overlap."""
    if not spans:
        return []

    priority = {"EMAIL": 0, "CREDIT_CARD": 1, "PHONE": 2}
    ordered = sorted(
        spans,
        key=lambda span: (span.start, priority[span.pii_type], -span.length),
    )

    merged: list[_Span] = []
    for span in ordered:
        if merged and span.start < merged[-1].end:
            current = merged[-1]
            if priority[span.pii_type] < priority[current.pii_type]:
                merged[-1] = span
            elif priority[span.pii_type] == priority[current.pii_type] and span.length > current.length:
                merged[-1] = span
            continue
        merged.append(span)

    merged.sort(key=lambda span: span.start)
    return merged
