# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.1] - 2026-07-16

### Fixed

- Corrected the `.pbip` shortcut file `$schema` so Power BI Desktop (June 2026 and later) can open
  the generated project. The value now matches the required pattern
  `fabric/pbip/pbipProperties/1.0.0/schema.json`; the previous `fabric/item/pbip/1.0.0` value was
  rejected with an `UnrecognizedSchemaVersion` error on open.

## [0.3.0] - 2026-06-30

### Added

- Data module conversion: parses Cognos Analytics `.module` JSON into a TMDL semantic model, with
  identifier columns marked as keys, fact items given a summarize-by aggregation, calculations
  flagged for review, and relationships oriented from the many side. New `migrate-module` command.
- Dashboard conversion: parses Cognos dashboards and explorations into PBIR report pages, mapping
  column, bar, line, pie, list, and crosstab widgets to Power BI visuals, synthesizing the tables
  and columns the visuals reference, and translating slot mappings into field roles. New
  `migrate-dashboard` command.
- Source-kind auto-detection (report, model, data module, dashboard) by content with a filename
  extension fallback.
- Batch and folder migration: converts many mixed sources in one pass, each into its own project
  subfolder, and writes a consolidated coverage report (`COVERAGE_REPORT.md` and `coverage.json`).
  New `migrate-batch` command.
- SaaS portal updates: auto-detect and a source-kind selector on the web UI; review items rendered
  as a table; `/api/v1/migrate` and `/api/v1/analyze` accept a `kind` field; new `/api/v1/batch`
  endpoint returns a zip of all projects plus the coverage report.
- Example sources: `examples/sample_data_module.json` and `examples/sample_dashboard.json`.

## [0.2.0] - 2026-06-30

### Added

- Star-schema data modeling: classifies fact, dimension, date, and bridge tables; orients each
  relationship from the many side to the one side; infers cardinality and cross-filter direction;
  marks date tables; hides foreign-key columns; and flags ambiguous filter loops, role-playing
  dimensions, self-referencing hierarchies, many-to-many joins, snowflakes, composite keys, and
  disconnected tables. Toggle with `--infer-model` / `--no-infer-model`.
- Broader Cognos-to-TMDL data-type mapping (width-suffixed integers, precision-qualified decimals,
  additional date and floating-point aliases).

## [0.1.0] - 2026-06-29

First public preview.

### Added

- Initial project scaffold.
- Cognos report specification parser (beta).
- Cognos Framework Manager model parser with the `migrate-model` command, producing TMDL tables
  and relationships.
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
