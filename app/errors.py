"""API error responses — OpenAI-compatible error shape."""

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.providers.exceptions import OpenAIProviderError


class GatewayHTTPException(Exception):
    """Application error with a structured JSON body."""

    def __init__(self, status_code: int, message: str, error_type: str, code: str) -> None:
        self.status_code = status_code
        self.body = {
            "error": {
                "message": message,
                "type": error_type,
                "code": code,
            }
        }


async def gateway_exception_handler(_request: Request, exc: GatewayHTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=exc.body)


async def validation_exception_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Map FastAPI validation errors to gateway error format."""
    first_error = exc.errors()[0] if exc.errors() else {}
    field = ".".join(str(part) for part in first_error.get("loc", ("body",)))
    message = first_error.get("msg", "Invalid request body")
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "message": f"Validation error on '{field}': {message}",
                "type": "invalid_request_error",
                "code": "validation_error",
            }
        },
    )


def invalid_api_key_error() -> GatewayHTTPException:
    return GatewayHTTPException(
        status_code=401,
        message="Invalid API key provided.",
        error_type="authentication_error",
        code="invalid_api_key",
    )


def inactive_project_error() -> GatewayHTTPException:
    return GatewayHTTPException(
        status_code=401,
        message="Project is inactive.",
        error_type="authentication_error",
        code="inactive_project",
    )


def streaming_not_supported_error() -> GatewayHTTPException:
    return GatewayHTTPException(
        status_code=400,
        message="Streaming is not supported yet. Set stream to false.",
        error_type="invalid_request_error",
        code="streaming_not_supported",
    )


def rate_limit_error() -> GatewayHTTPException:
    return GatewayHTTPException(
        status_code=429,
        message="Rate limit exceeded.",
        error_type="rate_limit_error",
        code="rate_limit_exceeded",
    )


def gateway_timeout_error() -> GatewayHTTPException:
    return GatewayHTTPException(
        status_code=504,
        message="Gateway timeout waiting for provider.",
        error_type="timeout_error",
        code="gateway_timeout",
    )


def provider_error(message: str = "Upstream provider error.") -> GatewayHTTPException:
    return GatewayHTTPException(
        status_code=502,
        message=message,
        error_type="provider_error",
        code="provider_error",
    )


def invalid_request_error(message: str) -> GatewayHTTPException:
    return GatewayHTTPException(
        status_code=400,
        message=message,
        error_type="invalid_request_error",
        code="invalid_request",
    )


def map_openai_provider_error(exc: OpenAIProviderError) -> GatewayHTTPException:
    """Translate OpenAI failures into gateway HTTP errors."""
    if exc.is_timeout:
        return gateway_timeout_error()

    status = exc.status_code

    if status == 429:
        return rate_limit_error()

    if status == 400:
        return invalid_request_error(exc.message)

    if status in {401, 403}:
        # Misconfigured server OpenAI key — do not expose details to clients
        return provider_error("Upstream provider authentication failed.")

    if status is not None and status >= 500:
        return provider_error("Upstream provider is temporarily unavailable.")

    if status is not None and 400 < status < 500:
        return provider_error(exc.message)

    return provider_error(exc.message or "Upstream provider error.")
