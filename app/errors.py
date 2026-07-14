"""API error responses — OpenAI-compatible error shape."""

from fastapi import Request
from fastapi.responses import JSONResponse


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


def provider_error(message: str = "Upstream provider error.") -> GatewayHTTPException:
    return GatewayHTTPException(
        status_code=502,
        message=message,
        error_type="provider_error",
        code="provider_error",
    )
