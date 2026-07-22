"""Provider-specific exceptions with upstream context for error mapping."""


class OpenAIProviderError(Exception):
    """Raised when the OpenAI API call fails."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        is_timeout: bool = False,
    ) -> None:
        self.message = message
        self.status_code = status_code
        self.is_timeout = is_timeout
        super().__init__(message)


class AnthropicProviderError(Exception):
    """Raised when the Anthropic API call fails."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        is_timeout: bool = False,
    ) -> None:
        self.message = message
        self.status_code = status_code
        self.is_timeout = is_timeout
        super().__init__(message)
