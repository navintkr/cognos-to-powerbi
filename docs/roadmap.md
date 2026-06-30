# Roadmap

The roadmap is organized by milestone. Dates are intentionally omitted; progress is driven by
contributions and adoption.

## Shipped

- Namespace-agnostic Cognos report parser.
- Framework Manager model parser to TMDL with relationship detection.
- Data module parser to TMDL (query subjects, facts, identifiers, relationships).
- Dashboard and exploration parser to PBIR report pages.
- Star-schema modeling (fact and dimension roles, date tables, summarize-by).
- Deterministic PBIP generation (TMDL + PBIR).
- Provider-agnostic AI refinement for measures.
- Review report for unmapped items.
- SaaS portal: upload, analyze, review flags, and download on the FastAPI backend.
- Batch and folder migration with a consolidated coverage report (Markdown and JSON).

## Milestone 3 - Expression translation library

- Deterministic Cognos-to-DAX translations for common functions (date, string, conditional).
- Reduce reliance on AI for routine expressions.

## Milestone 4 - Visual fidelity

- Crosstab to matrix parity.
- Chart property mapping (axes, legends, series).
- Filters, prompts, and conditional formatting.

## Milestone 5 - Team features

- Authentication, project history, and team workspaces.

## How to influence the roadmap

Open a feature request or comment on an existing one. Items with clear use cases and sample inputs
are prioritized.
