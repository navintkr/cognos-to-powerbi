"""Abstractions shared by all AI providers."""

from __future__ import annotations

import abc

from pydantic import BaseModel


class AiRequest(BaseModel):
    """A single refinement request sent to an AI provider."""

    instruction: str
    context: str = ""
    max_output_tokens: int = 2048


class AiResult(BaseModel):
    """The result of an AI refinement request."""

    ok: bool
    text: str = ""
    error: str | None = None
    provider: str = ""


class AiProvider(abc.ABC):
    """Interface every AI provider must implement.

    Implementations should be thin wrappers over a provider CLI. They must never raise on a
    provider failure; instead return an :class:`AiResult` with ``ok=False`` so the pipeline can
    fall back to the deterministic output and flag the item for manual review.
    """

    name: str = "base"

    @abc.abstractmethod
    def is_available(self) -> bool:
        """Return True when the provider CLI is installed and usable."""

    @abc.abstractmethod
    def complete(self, request: AiRequest) -> AiResult:
        """Run a single refinement request."""


class NullProvider(AiProvider):
    """A no-op provider used when AI refinement is disabled."""

    name = "none"

    def is_available(self) -> bool:
        return True

    def complete(self, request: AiRequest) -> AiResult:
        return AiResult(ok=False, error="AI refinement is disabled.", provider=self.name)
