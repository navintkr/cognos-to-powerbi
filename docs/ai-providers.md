# AI providers

AI refinement is optional. The deterministic conversion runs without any provider; AI only
translates Cognos expressions and layouts that have no mechanical mapping.

## Selecting a provider

Set it per command:

```bash
cognos2pbi migrate ./report.xml --out ./out/Report --ai claude
```

Or set a default with an environment variable:

```bash
export COGNOS2PBI_AI_PROVIDER=claude   # Windows: setx COGNOS2PBI_AI_PROVIDER claude
```

Copy `.env.example` to `.env` to keep configuration in one place.

## Supported providers

| Provider | Value | Backend | Notes |
| --- | --- | --- | --- |
| Azure OpenAI | `azure` | Azure OpenAI deployment (HTTPS) | Uses the `openai` SDK. Default auth is Microsoft Entra ID (Azure CLI credentials); an API key is used if set. |
| Anthropic Claude | `claude` | `claude -p` | Claude Code CLI in non-interactive mode. |
| GitHub Copilot | `copilot` | `copilot -p` | Copilot CLI in non-interactive mode. |
| OpenAI Codex | `codex` | `codex exec` | Codex CLI in non-interactive mode. |
| None | `none` | n/a | Deterministic only; gaps become review flags. |

Override a CLI executable path when it is not on `PATH`:

```bash
export COGNOS2PBI_CLAUDE_CLI=/full/path/to/claude
```

## Azure OpenAI

Install the optional dependencies and select the provider:

```bash
pip install "cognos2powerbi[azure]"
cognos2pbi migrate ./report.xml --out ./out/Report --ai azure
```

Authentication order:

1. An API key if `COGNOS2PBI_AOAI_API_KEY` (or `AZURE_OPENAI_API_KEY`) is set.
2. Otherwise Microsoft Entra ID via `DefaultAzureCredential`. On a developer machine, run
   `az login` and ensure your identity has the `Cognitive Services OpenAI User` role on the
   resource. No key is stored by this tool.

Configuration (all optional; sensible defaults are built in):

| Variable | Purpose |
| --- | --- |
| `COGNOS2PBI_AOAI_ENDPOINT` | Azure OpenAI resource endpoint URL. |
| `COGNOS2PBI_AOAI_DEPLOYMENT` | Deployment (model) name to call. |
| `COGNOS2PBI_AOAI_API_VERSION` | REST API version. |
| `COGNOS2PBI_AOAI_API_KEY` | API key, if you prefer key auth over Entra ID. |

## How it works

For each measure and each calculated column the deterministic engine could not translate, the
pipeline sends the Cognos expression and minimal context to the provider and asks for a single DAX
expression. A successful response replaces the placeholder (a calculated column is upgraded from a
placeholder physical column to a DAX column); a failure leaves the deterministic output intact and
records a review flag. The model always stays loadable: unmapped calculations remain physical
columns until a valid DAX translation is available.

## Verifying availability

```bash
cognos2pbi doctor --ai claude
```
