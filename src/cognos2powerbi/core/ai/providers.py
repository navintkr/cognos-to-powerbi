"""Concrete AI providers that shell out to vendor CLIs.

Each provider invokes its CLI in non-interactive mode and returns the model output as text.
The providers are deliberately minimal: they take a single prompt and return a single response.
Prompt construction and response parsing live in the refinement stage, not here.
"""

from __future__ import annotations

import os
import shutil
import subprocess

from cognos2powerbi.core.ai.base import AiProvider, AiRequest, AiResult, NullProvider

_DEFAULT_TIMEOUT = int(os.environ.get("COGNOS2PBI_AI_TIMEOUT", "120"))


class _CliProvider(AiProvider):
    """Base class for providers backed by a command-line executable."""

    def __init__(self, executable: str, args: list[str]):
        self._executable = executable
        self._args = args

    def is_available(self) -> bool:
        return shutil.which(self._executable) is not None

    def _run(self, prompt: str) -> AiResult:
        if not self.is_available():
            return AiResult(
                ok=False,
                error=f"Provider CLI '{self._executable}' was not found on PATH.",
                provider=self.name,
            )
        try:
            completed = subprocess.run(  # noqa: S603 - executable resolved from config
                [self._executable, *self._args],
                input=prompt,
                capture_output=True,
                text=True,
                timeout=_DEFAULT_TIMEOUT,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return AiResult(
                ok=False,
                error=f"Provider '{self.name}' timed out after {_DEFAULT_TIMEOUT}s.",
                provider=self.name,
            )
        except OSError as exc:
            return AiResult(ok=False, error=str(exc), provider=self.name)

        if completed.returncode != 0:
            return AiResult(
                ok=False,
                error=(completed.stderr or "Non-zero exit code.").strip(),
                provider=self.name,
            )
        return AiResult(ok=True, text=completed.stdout.strip(), provider=self.name)

    def complete(self, request: AiRequest) -> AiResult:
        prompt = request.instruction
        if request.context:
            prompt = f"{request.instruction}\n\nContext:\n{request.context}"
        return self._run(prompt)


class ClaudeProvider(_CliProvider):
    """Anthropic Claude via the Claude Code CLI (non-interactive `-p` mode)."""

    name = "claude"

    def __init__(self) -> None:
        executable = os.environ.get("COGNOS2PBI_CLAUDE_CLI", "claude")
        super().__init__(executable, ["-p"])


class CopilotProvider(_CliProvider):
    """GitHub Copilot via the Copilot CLI (non-interactive prompt mode)."""

    name = "copilot"

    def __init__(self) -> None:
        executable = os.environ.get("COGNOS2PBI_COPILOT_CLI", "copilot")
        super().__init__(executable, ["-p"])


class CodexProvider(_CliProvider):
    """OpenAI Codex via the Codex CLI (non-interactive exec mode)."""

    name = "codex"

    def __init__(self) -> None:
        executable = os.environ.get("COGNOS2PBI_CODEX_CLI", "codex")
        super().__init__(executable, ["exec"])


_PROVIDERS = {
    "claude": ClaudeProvider,
    "copilot": CopilotProvider,
    "codex": CodexProvider,
    "none": NullProvider,
}


def get_provider(name: str | None) -> AiProvider:
    """Resolve a provider by name. Unknown or empty names yield the null provider."""
    key = (name or os.environ.get("COGNOS2PBI_AI_PROVIDER") or "none").strip().lower()
    factory = _PROVIDERS.get(key, NullProvider)
    return factory()
