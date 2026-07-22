"""Anthropic provider — Messages API via httpx with OpenAI-compatible stream output."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator

import httpx

from app.config import settings
from app.providers.base import ChatMessage, CompletionRequest, CompletionResponse, LLMProvider
from app.providers.exceptions import AnthropicProviderError


class AnthropicProvider(LLMProvider):
    """Calls Anthropic's /v1/messages endpoint."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        api_version: str,
        *,
        connect_timeout: float,
        read_timeout: float,
        stream_idle_timeout: float,
        write_timeout: float,
        pool_timeout: float,
        default_max_tokens: int = 1024,
    ) -> None:
        if not api_key:
            raise ValueError("Anthropic API key is required")

        self._api_version = api_version
        self._default_max_tokens = default_max_tokens
        self._stream_idle_timeout = stream_idle_timeout
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={
                "x-api-key": api_key,
                "anthropic-version": api_version,
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(
                connect=connect_timeout,
                read=read_timeout,
                write=write_timeout,
                pool=pool_timeout,
            ),
        )

    @property
    def name(self) -> str:
        return "anthropic"

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        payload = _build_payload(request, stream=False, default_max_tokens=self._default_max_tokens)

        try:
            response = await self._client.post("/messages", json=payload)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise _timeout_error("Anthropic request timed out", exc) from exc
        except httpx.HTTPStatusError as exc:
            message = _extract_anthropic_error_message(exc.response)
            raise AnthropicProviderError(message, status_code=exc.response.status_code) from exc
        except httpx.RequestError as exc:
            raise AnthropicProviderError(f"Anthropic connection error: {exc}") from exc

        data = response.json()
        text = _extract_text_content(data.get("content", []))
        usage = data.get("usage", {})

        return CompletionResponse(
            id=data.get("id", f"msg_{uuid.uuid4().hex}"),
            model=data.get("model", request.model),
            content=text,
            finish_reason=data.get("stop_reason"),
            prompt_tokens=usage.get("input_tokens", 0),
            completion_tokens=usage.get("output_tokens", 0),
            total_tokens=usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
            created=int(time.time()),
        )

    async def stream(self, request: CompletionRequest) -> AsyncIterator[str]:
        """Stream Anthropic events translated to OpenAI-compatible SSE chunks."""
        payload = _build_payload(request, stream=True, default_max_tokens=self._default_max_tokens)
        stream_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
        created = int(time.time())
        model = request.model

        try:
            async with self._client.stream("POST", "/messages", json=payload) as response:
                if response.status_code >= 400:
                    await response.aread()
                    message = _extract_anthropic_error_message(response)
                    raise AnthropicProviderError(message, status_code=response.status_code)

                async for event_type, data in _iter_anthropic_events(
                    response,
                    self._stream_idle_timeout,
                ):
                    if event_type == "content_block_delta":
                        delta = data.get("delta", {})
                        text = delta.get("text")
                        if text:
                            yield _openai_sse_chunk(
                                stream_id,
                                model,
                                created,
                                content=text,
                            )
                    elif event_type == "message_delta":
                        usage = data.get("usage", {})
                        if usage:
                            yield _openai_usage_chunk(stream_id, model, created, usage)
                    elif event_type == "message_stop":
                        yield _openai_sse_chunk(
                            stream_id,
                            model,
                            created,
                            finish_reason="stop",
                        )

                yield "data: [DONE]\n\n"
        except AnthropicProviderError:
            raise
        except httpx.TimeoutException as exc:
            raise _timeout_error("Anthropic request timed out", exc) from exc
        except httpx.RequestError as exc:
            if isinstance(exc, httpx.StreamClosed):
                return
            raise AnthropicProviderError(f"Anthropic connection error: {exc}") from exc

    async def aclose(self) -> None:
        await self._client.aclose()


def _split_messages(messages: list[ChatMessage]) -> tuple[str | None, list[dict[str, str]]]:
    system_parts: list[str] = []
    anthropic_messages: list[dict[str, str]] = []

    for message in messages:
        if message.role == "system":
            system_parts.append(message.content)
        elif message.role in {"user", "assistant"}:
            anthropic_messages.append({"role": message.role, "content": message.content})
        else:
            raise AnthropicProviderError(
                f"Unsupported message role for Anthropic: {message.role}",
                status_code=400,
            )

    if not anthropic_messages:
        raise AnthropicProviderError("At least one user message is required", status_code=400)

    system = "\n".join(system_parts) if system_parts else None
    return system, anthropic_messages


def _build_payload(
    request: CompletionRequest,
    *,
    stream: bool,
    default_max_tokens: int,
) -> dict:
    system, anthropic_messages = _split_messages(request.messages)
    payload: dict = {
        "model": request.model,
        "messages": anthropic_messages,
        "max_tokens": request.max_tokens or default_max_tokens,
        "stream": stream,
    }
    if system:
        payload["system"] = system
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    return payload


def _extract_text_content(content_blocks: list) -> str:
    parts: list[str] = []
    for block in content_blocks:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return "".join(parts)


def _openai_sse_chunk(
    stream_id: str,
    model: str,
    created: int,
    *,
    content: str | None = None,
    finish_reason: str | None = None,
) -> str:
    delta: dict = {}
    if content is not None:
        delta["content"] = content
    chunk = {
        "id": stream_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    return f"data: {json.dumps(chunk)}\n\n"


def _openai_usage_chunk(stream_id: str, model: str, created: int, usage: dict) -> str:
    chunk = {
        "id": stream_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [],
        "usage": {
            "prompt_tokens": usage.get("input_tokens", 0),
            "completion_tokens": usage.get("output_tokens", 0),
            "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
        },
    }
    return f"data: {json.dumps(chunk)}\n\n"


async def _iter_anthropic_events(
    response: httpx.Response,
    idle_timeout: float,
) -> AsyncIterator[tuple[str, dict]]:
    line_source = response.aiter_lines().__aiter__()
    current_event: str | None = None

    while True:
        try:
            line = await asyncio.wait_for(line_source.__anext__(), timeout=idle_timeout)
        except TimeoutError as exc:
            raise AnthropicProviderError(
                f"Anthropic stream idle for {idle_timeout:.0f}s",
                is_timeout=True,
            ) from exc
        except StopAsyncIteration:
            break

        if not line:
            continue
        if line.startswith("event:"):
            current_event = line[len("event:") :].strip()
            continue
        if line.startswith("data:") and current_event:
            data = json.loads(line[len("data:") :].strip())
            yield current_event, data


def _timeout_error(message: str, exc: httpx.TimeoutException) -> AnthropicProviderError:
    return AnthropicProviderError(message, is_timeout=True)


def _extract_anthropic_error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
        error = body.get("error", {})
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
        if body.get("message"):
            return str(body["message"])
    except Exception:
        pass
    return f"Anthropic API error (HTTP {response.status_code})"


def create_anthropic_provider() -> AnthropicProvider:
    """Build an Anthropic provider from application settings."""
    return AnthropicProvider(
        api_key=settings.anthropic_api_key.get_secret_value(),
        base_url=settings.anthropic_base_url,
        api_version=settings.anthropic_api_version,
        connect_timeout=settings.anthropic_connect_timeout_s,
        read_timeout=settings.anthropic_read_timeout_s,
        stream_idle_timeout=settings.anthropic_stream_idle_timeout_s,
        write_timeout=settings.anthropic_write_timeout_s,
        pool_timeout=settings.anthropic_pool_timeout_s,
        default_max_tokens=settings.anthropic_default_max_tokens,
    )
