import asyncio

import httpx
import pytest

from boundary_backend.config import InvalidModelEndpointError
from boundary_backend.local_model import (
    MalformedModelResponseError,
    ModelConnectionError,
    ModelTimeoutError,
    VLLMLocalModelClient,
)


def make_client(handler) -> VLLMLocalModelClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    return VLLMLocalModelClient(
        "http://127.0.0.1:8000/v1",
        "boundary-qwen3-8b",
        2.0,
        http_client=http_client,
    )


def test_model_discovery_parses_ids() -> None:
    client = make_client(
        lambda request: httpx.Response(
            200, json={"data": [{"id": "boundary-qwen3-8b"}]}
        )
    )
    assert asyncio.run(client.available_models()) == {"boundary-qwen3-8b"}
    asyncio.run(client._http_client.aclose())


def test_malformed_discovery_response() -> None:
    client = make_client(lambda request: httpx.Response(200, json={"data": "bad"}))
    with pytest.raises(MalformedModelResponseError):
        asyncio.run(client.available_models())
    asyncio.run(client._http_client.aclose())


def test_timeout_is_typed() -> None:
    def timeout(request):
        raise httpx.ReadTimeout("timed out", request=request)

    client = make_client(timeout)
    with pytest.raises(ModelTimeoutError):
        asyncio.run(client.available_models())
    asyncio.run(client._http_client.aclose())


def test_connection_failure_is_typed() -> None:
    def disconnect(request):
        raise httpx.ConnectError("refused", request=request)

    client = make_client(disconnect)
    with pytest.raises(ModelConnectionError):
        asyncio.run(client.available_models())
    asyncio.run(client._http_client.aclose())


@pytest.mark.parametrize(
    "url",
    [
        "ftp://127.0.0.1:8000/v1",
        "http://example.com/v1",
        "http://8.8.8.8/v1",
        "http://user:password@127.0.0.1:8000/v1",
        "http://127.0.0.1:not-a-port/v1",
        "not-a-url",
    ],
)
def test_invalid_or_remote_endpoint_is_rejected(url: str) -> None:
    with pytest.raises(InvalidModelEndpointError):
        VLLMLocalModelClient(url, "boundary-qwen3-8b", 2.0)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8000/v1",
        "http://127.0.0.1:8000/v1",
        "http://10.0.0.5:8000/v1",
        "https://192.168.1.20/v1",
        "http://[::1]:8000/v1",
    ],
)
def test_local_endpoint_is_accepted(url: str) -> None:
    assert VLLMLocalModelClient(url, "boundary-qwen3-8b", 2.0).base_url == url
