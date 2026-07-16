# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.4.5] - 2026-07-16

### Fixed

- The generated report now registers its base theme in a `resourcePackages` block and uses the
  current theme and file schema versions, matching a real Power BI Desktop PBIP byte for byte
  (report.json 3.3.0, page 2.1.0, visualContainer 2.9.0, version.json 2.0.0, theme `CY26SU05`).
  Without the theme resource package, Power BI could not resolve the theme and failed to build the
  report exploration, which surfaced as a `visualContainers` render error even for an empty page.

## [0.4.4] - 2026-07-16

### Fixed

- Matched the PBIR report files to the exact schema versions current Power BI Desktop writes
  (validated against a real Desktop-saved project): `report.json` schema 3.1.0 with an object
  `reportVersionAtImport` and no `layoutOptimization`, `page.json` schema 2.0.0, and
  `visualContainer` schema 2.0.0. The previous 1.0.0-shaped files were rejected, so Power BI failed
  to build the report (`Cannot read properties of undefined (reading 'visualContainers')`) even for
  an empty page. Auto-placed visuals are re-enabled now that the format is confirmed.

## [0.4.3] - 2026-07-16

### Changed

- The generated PBIR report now opens with pages and an empty canvas by default (no auto-placed
  visuals). Auto-placing visuals is being matched to the exact format current Power BI Desktop
  writes; until that is confirmed, an empty-but-valid report avoids a report-render error while the
  semantic model remains complete (drag fields onto the canvas to build visuals). Visual emission
  is available opt-in via `PbipGenerator.emit_visuals = True`.

## [0.4.2] - 2026-07-16

### Fixed

- Report generation now emits the modern Power BI enhanced report format (PBIR): a `definition/`
  folder with `version.json`, `report.json`, and per-page/per-visual files, plus a proper base
  theme. The previous legacy single-file `report.json` failed to render in Power BI Desktop (July
  2026) with `Cannot read properties of undefined (reading 'customTheme')`. The semantic model was
  unaffected; only the report layer changed. `definition.pbir` now declares version 4.0 with its
  schema, and visuals carry a proper field query (`Column`/`Measure` with `SourceRef`).

## [0.4.1] - 2026-07-16

### Added

- The `migrate` commands now print a grouped review breakdown in the terminal (by severity and
  category, with counts), so the conversion gaps are visible at a glance without opening
  `MIGRATION_REVIEW.md`. The full itemized list still goes to that file.

## [0.4.0] - 2026-07-16

### Added

- Azure OpenAI provider (`--ai azure`). Calls an Azure OpenAI deployment over HTTPS using the
  `openai` SDK, authenticating with Microsoft Entra ID by default (Azure CLI credentials) or an API
  key if set. Configurable endpoint, deployment, and API version. Install with the new `[azure]`
  extra (`pip install "cognos2powerbi[azure]"`).
- AI refinement now also converts calculated columns (not just measures) into DAX.
- Report data-type inference: TMDL types are derived from the Cognos `RS_dataType` attribute,
  `cast(...; type)` expressions, and numeric functions, so dates and numbers are no longer flattened
  to text.
- Calculated data items become DAX calculated columns when the translation is deterministic and
  confident. Items that cannot be translated stay as loadable physical columns and are flagged, so
  the model never contains invalid DAX.
- Query joins (`joinOperation`) are captured as Power BI relationships, oriented from the many side.

### Changed

- Honest review reporting: derived queries (`queryRef`), unapplied detail filters, and package/model
  sources are now flagged for review instead of being silently dropped. A report that previously
  showed zero review items now surfaces every gap in `MIGRATION_REVIEW.md`.

### Fixed

- Hyphenated and underscore-prefixed Cognos functions (for example `running-count`, `_round`) are
  no longer mistaken for known DAX functions, which previously let an untranslatable expression be
  emitted as invalid DAX.
- AI-generated (or multi-line) DAX is collapsed to a single line when rendered into TMDL, avoiding a
  TMDL indentation error on open.

## [0.3.2] - 2026-07-16

### Fixed

- Quoted the TMDL partition name so tables whose names contain spaces (for example
  `Contract List`) no longer fail to open with a TMDL indentation error. The partition declaration
  now reads `partition 'Contract List' = m`.
- Hardened TMDL identifier escaping so names that start with a digit (for example a column named
  `1`), contain accented or non-ASCII letters, or contain a single quote are correctly quoted and
  escaped. Previously these produced invalid TMDL that Power BI rejected on open.

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
