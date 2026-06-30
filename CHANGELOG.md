# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Initial project scaffold.
- Cognos report specification parser (beta).
- Cognos Framework Manager model parser with the `migrate-model` command, producing TMDL tables
  and relationships.
- Star-schema data modeling: classifies fact, dimension, date, and bridge tables; orients each
  relationship from the many side to the one side; infers cardinality and cross-filter direction;
  marks date tables; hides foreign-key columns; and flags ambiguous filter loops, role-playing
  dimensions, self-referencing hierarchies, many-to-many joins, snowflakes, composite keys, and
  disconnected tables. Toggle with `--infer-model` / `--no-infer-model`.
- Broader Cognos-to-TMDL data-type mapping (width-suffixed integers, precision-qualified decimals,
  additional date and floating-point aliases).
- Deterministic Cognos-to-DAX expression translation library (references, arithmetic with
  aggregates, if/then/else, case, common string and date functions).
- Parameterized SQL Server data-source wiring: generated models include `Server` and `Database`
  parameters and `Sql.Database` partitions so the PBIP is refreshable. Configure with
  `--source-type`, `--server`, `--database`, and `--schema`.
- Single-page web frontend served by the FastAPI backend for upload, analyze, and download.
- Vendor-neutral intermediate representation (IR).
- PBIP generator producing TMDL semantic models and PBIR reports.
- Provider-agnostic AI adapter for Claude, GitHub Copilot, and Codex CLIs.
- Command-line interface (`cognos2pbi`).
- FastAPI backend for the SaaS surface.
- PyPI publishing workflow using Trusted Publishing (OIDC).

## [0.1.0] - 2026-06-29

- First public preview.
