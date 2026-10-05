"""Chat model over any OpenAI-compatible endpoint.

One adapter covers OpenAI, Groq and a local Ollama, because all three speak the same
`/chat/completions` protocol. The only differences that matter are the base URL, whether a key is
required, and which model names exist.

httpx directly rather than the openai SDK: the surface used here is one POST, and keeping the
dependency out means the adapter cannot drag vendor types into the rest of the application.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

import httpx
import structlog
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.domain.errors import ExternalServiceError
from app.domain.models import ChatMessage, ChatResult, TokenUsage, ToolCallRequest

logger = structlog.get_logger(__name__)

# Retrying a 400 is pointless and a 401 is a configuration problem, so only transport failures
# and the explicitly transient status codes are retried.
RETRYABLE_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504})

HTTP_BAD_REQUEST = 400
HTTP_UNAUTHORIZED = 401
HTTP_NOT_FOUND = 404


class RetryableUpstreamError(Exception):
    """Internal marker so tenacity retries transient failures and nothing else."""


class OpenAiChatAdapter:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        model: str,
        temperature: float = 0.0,
        timeout_seconds: float = 60.0,
        max_retries: int = 3,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._temperature = temperature
        self._timeout = timeout_seconds
        self._max_retries = max_retries

    @property
    def model_name(self) -> str:
        return self._model

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[Mapping[str, Any]] | None = None,
        response_format: Mapping[str, Any] | None = None,
        temperature: float | None = None,
    ) -> ChatResult:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [self._encode(message) for message in messages],
            "temperature": self._temperature if temperature is None else temperature,
        }
        if tools:
            payload["tools"] = list(tools)
        if response_format:
            payload["response_format"] = dict(response_format)

        data = await self._post(payload)
        return self._decode(data)

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        attempt = retry(
            stop=stop_after_attempt(self._max_retries + 1),
            wait=wait_exponential(multiplier=0.6, max=8),
            retry=retry_if_exception_type(RetryableUpstreamError),
            reraise=True,
        )

        @attempt
        async def _send() -> dict[str, Any]:
            headers = {"Content-Type": "application/json"}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.post(
                        f"{self._base_url}/chat/completions", json=payload, headers=headers
                    )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                raise RetryableUpstreamError(str(exc)) from exc

            if response.status_code in RETRYABLE_STATUS:
                raise RetryableUpstreamError(f"status {response.status_code}")
            if response.status_code >= HTTP_BAD_REQUEST:
                raise ExternalServiceError(
                    self._describe_failure(response),
                    service="chat_model",
                    retryable=False,
                )
            result: dict[str, Any] = response.json()
            return result

        try:
            return await _send()
        except RetryableUpstreamError as exc:
            raise ExternalServiceError(
                f"The language model provider is unavailable: {exc}",
                service="chat_model",
                retryable=True,
            ) from exc

    def _describe_failure(self, response: httpx.Response) -> str:
        """Turn a provider error into something a user can act on."""
        try:
            message = response.json().get("error", {}).get("message", "")
        except (ValueError, AttributeError):
            message = response.text[:200]
        if response.status_code == HTTP_UNAUTHORIZED:
            return "The model provider rejected the API key. Check OPENAI_API_KEY."
        if response.status_code == HTTP_NOT_FOUND:
            return (
                f"The model '{self._model}' is not available on this account. "
                f"Set OPENAI_MODEL to one the provider lists. Provider said: {message}"
            )
        return f"The model provider refused the request ({response.status_code}): {message}"

    @staticmethod
    def _encode(message: ChatMessage) -> dict[str, Any]:
        encoded: dict[str, Any] = {"role": message.role, "content": message.content}
        if message.tool_call_id:
            encoded["tool_call_id"] = message.tool_call_id
        if message.tool_calls:
            encoded["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.tool_name,
                        "arguments": json.dumps(call.arguments),
                    },
                }
                for call in message.tool_calls
            ]
        return encoded

    def _decode(self, data: dict[str, Any]) -> ChatResult:
        choices = data.get("choices") or []
        if not choices:
            raise ExternalServiceError(
                "The model returned no choices.", service="chat_model", retryable=True
            )
        message = choices[0].get("message", {})
        usage = data.get("usage") or {}

        calls: list[ToolCallRequest] = []
        for raw in message.get("tool_calls") or []:
            function = raw.get("function", {})
            try:
                arguments = json.loads(function.get("arguments") or "{}")
            except json.JSONDecodeError:
                # A model that emits malformed arguments is a tool failure the agent can reason
                # about, not a crash: the empty dict fails validation downstream with a message.
                arguments = {}
            calls.append(
                ToolCallRequest(
                    id=raw.get("id", ""),
                    tool_name=function.get("name", ""),
                    arguments=arguments,
                )
            )

        return ChatResult(
            content=message.get("content") or "",
            tool_calls=tuple(calls),
            usage=TokenUsage(
                prompt_tokens=int(usage.get("prompt_tokens", 0)),
                completion_tokens=int(usage.get("completion_tokens", 0)),
            ),
            model_name=data.get("model", self._model),
            finish_reason=choices[0].get("finish_reason", "stop"),
        )
