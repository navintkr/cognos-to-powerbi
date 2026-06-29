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

| Provider | Value | CLI invoked | Notes |
| --- | --- | --- | --- |
| Anthropic Claude | `claude` | `claude -p` | Claude Code CLI in non-interactive mode. |
| GitHub Copilot | `copilot` | `copilot -p` | Copilot CLI in non-interactive mode. |
| OpenAI Codex | `codex` | `codex exec` | Codex CLI in non-interactive mode. |
| None | `none` | n/a | Deterministic only; gaps become review flags. |

Override the executable path when the CLI is not on `PATH`:

```bash
export COGNOS2PBI_CLAUDE_CLI=/full/path/to/claude
```

## How it works

For each measure the deterministic engine could not translate, the pipeline sends the Cognos
expression and minimal context to the provider and asks for a single DAX expression. A successful
response replaces the placeholder; a failure leaves the deterministic output intact and records a
review flag. Authentication is handled entirely by the provider CLI, so this tool never stores or
transmits credentials itself.

## Verifying availability

```bash
cognos2pbi doctor --ai claude
```
