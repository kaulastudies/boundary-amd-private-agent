import asyncio

import pytest

from boundary_backend.local_model import UnconfiguredLocalModelClient


def test_unconfigured_model_fails_explicitly() -> None:
    client = UnconfiguredLocalModelClient()

    with pytest.raises(RuntimeError, match="No local model"):
        asyncio.run(client.generate("hello"))
