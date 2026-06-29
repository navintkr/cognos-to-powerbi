# Roadmap

The roadmap is organized by milestone. Dates are intentionally omitted; progress is driven by
contributions and adoption.

## Milestone 1 - Reliable report conversion (current)

- Namespace-agnostic Cognos report parser.
- Deterministic PBIP generation (TMDL + PBIR).
- Provider-agnostic AI refinement for measures.
- Review report for unmapped items.

## Milestone 2 - Models

- Framework Manager model parser to TMDL.
- Data Module parser to TMDL.
- Relationship detection and generation.

## Milestone 3 - Expression translation library

- Deterministic Cognos-to-DAX translations for common functions (date, string, conditional).
- Reduce reliance on AI for routine expressions.

## Milestone 4 - Visual fidelity

- Crosstab to matrix parity.
- Chart property mapping (axes, legends, series).
- Filters, prompts, and conditional formatting.

## Milestone 5 - SaaS portal

- Upload, review, and download workflow on the FastAPI backend.
- Batch and folder migration with a consolidated coverage report.
- Authentication, project history, and team workspaces.

## How to influence the roadmap

Open a feature request or comment on an existing one. Items with clear use cases and sample inputs
are prioritized.
