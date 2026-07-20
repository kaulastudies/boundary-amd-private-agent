"""Local model interface and OpenAI-compatible vLLM implementation."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any, Optional, Set

import httpx

from .config import validate_local_model_url


class LocalModelError(Exception):
    """Base error for local inference failures."""


class ModelTimeoutError(LocalModelError):
    """The local model did not respond within the configured timeout."""


class ModelConnectionError(LocalModelError):
    """The local model endpoint could not be reached."""


class MalformedModelResponseError(LocalModelError):
    """The local model returned an unexpected response shape."""


class ModelUnavailableError(LocalModelError):
    """The configured model is not served by the local endpoint."""


class LocalModelClient(ABC):
    """Contract implemented by a local model runtime."""

    @abstractmethod
    async def generate(self, prompt: str) -> str:
        """Generate one response using only a local model."""

    @abstractmethod
    async def stream(self, prompt: str) -> AsyncIterator[str]:
        """Stream a response using only a local model."""
        if False:
            yield ""

    @abstractmethod
    async def available_models(self) -> Set[str]:
        """Return model identifiers advertised by the local runtime."""

    async def generate_with_schema(
        self, prompt: str, json_schema: dict[str, Any], schema_name: str
    ) -> str:
        """Generate schema-constrained JSON when supported by the runtime."""
        return await self.generate(prompt)


class VLLMLocalModelClient(LocalModelClient):
    """Client for a local vLLM OpenAI-compatible HTTP server."""

    def __init__(
        self,
        base_url: str,
        model_name: str,
        timeout_seconds: float,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.base_url = validate_local_model_url(base_url)
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds
        self._http_client = http_client

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        owns_client = self._http_client is None
        client = self._http_client or httpx.AsyncClient()
        try:
            response = await client.request(
                method,
                f"{self.base_url}/{path.lstrip('/')}",
                timeout=self.timeout_seconds,
                **kwargs,
            )
            response.raise_for_status()
            return response
        except httpx.TimeoutException as exc:
            raise ModelTimeoutError("local model request timed out") from exc
        except httpx.ConnectError as exc:
            raise ModelConnectionError("local model endpoint is unreachable") from exc
        except httpx.RequestError as exc:
            raise ModelConnectionError("local model request failed") from exc
        except httpx.HTTPStatusError as exc:
            raise ModelUnavailableError(
                f"local model endpoint returned HTTP {exc.response.status_code}"
            ) from exc
        finally:
            if owns_client:
                await client.aclose()

    @staticmethod
    def _json_object(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise MalformedModelResponseError(
                "local model returned invalid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise MalformedModelResponseError(
                "local model returned a non-object JSON response"
            )
        return payload

    async def available_models(self) -> Set[str]:
        payload = self._json_object(await self._request("GET", "models"))
        data = payload.get("data")
        if not isinstance(data, list):
            raise MalformedModelResponseError("model discovery response has no data list")
        model_ids: Set[str] = set()
        for item in data:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                raise MalformedModelResponseError(
                    "model discovery response contains an invalid model entry"
                )
            model_ids.add(item["id"])
        return model_ids

    async def _generate(
        self,
        prompt: str,
        response_format: dict[str, Any],
        temperature: float,
        max_tokens: int,
    ) -> str:
        payload = self._json_object(
            await self._request(
                "POST",
                "chat/completions",
                json={
                    "model": self.model_name,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Return only the requested JSON. Do not include hidden "
                                "reasoning, chain-of-thought, or markdown fences."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": temperature,
                    "stream": False,
                    "max_tokens": max_tokens,
                    "chat_template_kwargs": {"enable_thinking": False},
                    "response_format": response_format,
                },
            )
        )
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise MalformedModelResponseError(
                "completion response is missing message content"
            ) from exc
        if not isinstance(content, str) or not content.strip():
            raise MalformedModelResponseError(
                "completion response contains no text content"
            )
        return content

    async def generate(self, prompt: str) -> str:
        """Generate generic JSON while preserving the milestone 2 interface."""
        return await self._generate(
            prompt=prompt,
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=2048,
        )

    async def generate_with_schema(
        self, prompt: str, json_schema: dict[str, Any], schema_name: str
    ) -> str:
        """Generate JSON constrained by an OpenAI-compatible JSON schema."""
        return await self._generate(
            prompt=prompt,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": json_schema,
                },
            },
            temperature=0.0,
            max_tokens=2048,
        )

    async def stream(self, prompt: str) -> AsyncIterator[str]:
        yield await self.generate(prompt)
