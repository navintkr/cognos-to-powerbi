"""Concrete AI providers.

Two families are supported:

- CLI providers (Claude, Copilot, Codex) that shell out to a vendor command-line executable.
- The Azure OpenAI provider that calls an Azure OpenAI deployment over HTTPS using the ``openai``
  SDK, authenticating with an API key or, by default, Microsoft Entra ID (Azure CLI credentials).

Each provider takes a single prompt and returns a single response. Prompt construction and response
parsing live in the refinement stage, not here.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable

from cognos2powerbi.core.ai.base import AiProvider, AiRequest, AiResult, NullProvider

_DEFAULT_TIMEOUT = int(os.environ.get("COGNOS2PBI_AI_TIMEOUT", "120"))

# Azure OpenAI target. There is no built-in endpoint or deployment: set them per environment so no
# private resource is embedded in the package. Configure COGNOS2PBI_AOAI_ENDPOINT and
# COGNOS2PBI_AOAI_DEPLOYMENT (see .env.example).
_DEFAULT_AOAI_API_VERSION = "2024-10-21"
_AOAI_SCOPE = "https://cognitiveservices.azure.com/.default"


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


class AzureOpenAiProvider(AiProvider):
    """Azure OpenAI via the ``openai`` SDK.

    Authentication order: an explicit API key (``COGNOS2PBI_AOAI_API_KEY`` or
    ``AZURE_OPENAI_API_KEY``) if set, otherwise Microsoft Entra ID via
    :class:`azure.identity.DefaultAzureCredential` (Azure CLI credentials on a developer machine).
    The endpoint, deployment, and API version are configurable through environment variables and
    default to the project's Azure OpenAI resource.
    """

    name = "azure"

    def __init__(self) -> None:
        self._endpoint = os.environ.get("COGNOS2PBI_AOAI_ENDPOINT", "").strip()
        self._deployment = os.environ.get("COGNOS2PBI_AOAI_DEPLOYMENT", "").strip()
        self._api_version = os.environ.get("COGNOS2PBI_AOAI_API_VERSION", _DEFAULT_AOAI_API_VERSION)
        self._api_key = os.environ.get("COGNOS2PBI_AOAI_API_KEY") or os.environ.get(
            "AZURE_OPENAI_API_KEY"
        )
        self._client: object | None = None

    @staticmethod
    def _sdk_present() -> bool:
        import importlib.util

        return importlib.util.find_spec("openai") is not None

    def is_available(self) -> bool:
        if not self._sdk_present():
            return False
        # An endpoint and deployment must be configured; nothing is baked into the package.
        if not self._endpoint or not self._deployment:
            return False
        if self._api_key:
            return True
        # Entra ID path: confirm we can actually obtain a token so failures are reported once.
        try:
            from azure.identity import DefaultAzureCredential

            DefaultAzureCredential().get_token(_AOAI_SCOPE)
            return True
        except Exception:
            return False

    def _get_client(self) -> object:
        if self._client is not None:
            return self._client
        from openai import AzureOpenAI

        if self._api_key:
            self._client = AzureOpenAI(
                azure_endpoint=self._endpoint,
                api_key=self._api_key,
                api_version=self._api_version,
            )
        else:
            from azure.identity import DefaultAzureCredential, get_bearer_token_provider

            token_provider = get_bearer_token_provider(DefaultAzureCredential(), _AOAI_SCOPE)
            self._client = AzureOpenAI(
                azure_endpoint=self._endpoint,
                azure_ad_token_provider=token_provider,
                api_version=self._api_version,
            )
        return self._client

    def complete(self, request: AiRequest) -> AiResult:
        prompt = request.instruction
        if request.context:
            prompt = f"{request.instruction}\n\n{request.context}"
        try:
            client = self._get_client()
            response = client.chat.completions.create(  # type: ignore[attr-defined]
                model=self._deployment,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an expert that converts IBM Cognos report expressions into "
                            "Microsoft Power BI DAX. Return only the DAX expression: no prose, no "
                            "code fences, and no measure or column name."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                max_completion_tokens=request.max_output_tokens,
            )
            text = (response.choices[0].message.content or "").strip()
        except Exception as exc:  # noqa: BLE001 - never raise; report as a failed result
            return AiResult(ok=False, error=str(exc), provider=self.name)
        if not text:
            return AiResult(
                ok=False, error="Azure OpenAI returned an empty response.", provider=self.name
            )
        return AiResult(ok=True, text=_strip_code_fence(text), provider=self.name)


def _strip_code_fence(text: str) -> str:
    """Remove a surrounding Markdown code fence if the model added one."""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return stripped


_PROVIDERS: dict[str, Callable[[], AiProvider]] = {
    "claude": ClaudeProvider,
    "copilot": CopilotProvider,
    "codex": CodexProvider,
    "azure": AzureOpenAiProvider,
    "aoai": AzureOpenAiProvider,
    "azureopenai": AzureOpenAiProvider,
    "none": NullProvider,
}


def get_provider(name: str | None) -> AiProvider:
    """Resolve a provider by name. Unknown or empty names yield the null provider."""
    key = (name or os.environ.get("COGNOS2PBI_AI_PROVIDER") or "none").strip().lower()
    factory = _PROVIDERS.get(key, NullProvider)
    return factory()
