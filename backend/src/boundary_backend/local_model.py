"""Interface for a future on-device model implementation."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator


class LocalModelClient(ABC):
    """Contract implemented by a future local AMD model runtime."""

    @abstractmethod
    async def generate(self, prompt: str) -> str:
        """Generate one response using only a local model."""

    @abstractmethod
    async def stream(self, prompt: str) -> AsyncIterator[str]:
        """Stream a response using only a local model."""
        if False:
            yield ""


class UnconfiguredLocalModelClient(LocalModelClient):
    """Safe placeholder used until a local runtime is selected."""

    async def generate(self, prompt: str) -> str:
        raise RuntimeError("No local model has been configured")

    async def stream(self, prompt: str) -> AsyncIterator[str]:
        raise RuntimeError("No local model has been configured")
        yield prompt  # pragma: no cover
