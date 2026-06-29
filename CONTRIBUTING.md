# Contributing to Cognos to Power BI

Thank you for helping build the most reliable open-source Cognos to Power BI migration tool. This
guide explains how to set up your environment, the conventions we follow, and how to submit changes.

## Ways to contribute

- Improve Cognos parsers (report specifications, Framework Manager, data modules).
- Improve PBIP generators (TMDL semantic models, PBIR reports).
- Add expression translations (Cognos expression -> DAX).
- Write tests, sample inputs, and documentation.
- Triage issues and review pull requests.

Look for issues labeled `good first issue` and `help wanted`.

## Development setup

```bash
git clone https://github.com/navintkr/cognos-to-powerbi.git
cd cognos-to-powerbi
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -e ".[dev,api]"
```

Run the checks before opening a pull request:

```bash
ruff check .
ruff format --check .
mypy src
pytest
```

## Architecture overview

The pipeline is parser -> intermediate representation (IR) -> generator -> optional AI refinement.
Keep parsers and generators decoupled through the IR. New Cognos inputs and new Power BI outputs
should never depend on each other directly. See [docs/architecture.md](docs/architecture.md).

## Coding conventions

- Format and lint with `ruff`.
- Type-check with `mypy`; add type hints to all public functions.
- Prefer small, pure functions in `core/`. Side effects belong in the CLI and API layers.
- Add or update tests for every behavior change.
- Do not add emojis to code, docs, or commit messages.

## Commit and pull request guidelines

- Use clear, imperative commit messages (for example, `Add crosstab parser for list reports`).
- Reference the issue number in the pull request description.
- Keep pull requests focused. Split unrelated changes.
- Ensure CI passes. Pull requests that fail CI will not be merged.

## Reporting bugs and requesting features

Open an issue using the provided templates. Include sample Cognos input (with sensitive data
removed) whenever possible so maintainers can reproduce the problem.

## Code of Conduct

Participation in this project is governed by our [Code of Conduct](CODE_OF_CONDUCT.md).
