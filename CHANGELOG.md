# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.9.0] - 2026-09-20

### Added

- Query graph, filter, and prompt extraction for report specifications. The report parser now
  builds a structured query graph (every ``<query>`` classified by role - output, join, union,
  reference, or detail - with join/union/reference edges and raw join conditions), extracts each
  Cognos detail filter with its ``use`` semantics (mandatory / optional / prohibited) and referenced
  prompt parameters, and reads ``<promptPages>`` into structured prompt metadata (control type, data
  type, caption, required/multi-select flags, source query, selectable-values query and columns, and
  defaults). New IR models (``QueryGraph``, ``QueryNode``, ``QueryEdge``, ``QueryFilter``,
  ``Prompt``, and their enums) carry this on ``MigrationProject``.
- ``MIGRATION_METADATA.json`` sidecar. Both the PBIP and RDL generators now write the extracted
  query graph, filters, and prompts next to the Power BI output so the hidden business logic is
  reviewable and can drive later generation.
- RDL ``ReportParameters`` from prompts. The RDL generator turns extracted Cognos prompts into
  native ``ReportParameter`` elements (mapped data type, prompt caption, nullability, multi-value
  flag, and default values) and sizes the parameter grid layout to the migrated prompts.

## [0.8.0] - 2026-07-24

### Added

- Format masks for RDL data cells. The report parser now reads Cognos ``<dataFormat>`` specs
  (date, time, dateTime, number, currency, and percent format groups) and translates them to .NET
  format strings, captured on ``Column.format_string`` and ``Measure.format_string``. The RDL
  generator writes them as ``<Format>`` on each data cell. When a data item has no explicit format,
  a type-based default is applied (dates render as a short date, decimals and doubles get thousands
  grouping with two decimals, integers get grouping), so numbers and dates are formatted instead of
  shown raw. Explicit Cognos formats always win over the default.

## [0.7.0] - 2026-07-24

### Added

- Cognos style extraction with RDL style mapping. The report parser now reads the presentation
  styles Cognos sets on letterhead text and list columns, from inline ``<CSS>`` declarations
  (font-family, font-size, font-weight, font-style, color, background-color, text-align,
  vertical-align, text-decoration) and from well-known named style classes (``refStyle``, for
  example ``lt`` for list titles). These are captured on a new ``Style`` model and carried through
  ``ReportPage.header_blocks``/``footer_blocks`` and ``VisualField.header_style``/``cell_style``.
  The RDL generator applies them to the Textbox, TextRun, and Paragraph styles, so the generated
  report matches the source fonts, sizes, colors, and alignment instead of a single templated
  font. Generator defaults (Arial, the branded blue header) still fill in anything the source does
  not specify.

### Changed

- ``ReportPage.header_texts``/``footer_texts`` (list of strings) are replaced by
  ``header_blocks``/``footer_blocks`` (list of ``TextBlock`` with text plus style).

## [0.6.2] - 2026-07-24

### Fixed

- RDL Tablix columns are now auto-sized to their content instead of a fixed 1.2in width, so longer
  fields (for example "Contract Purchaser ID" and "Underwriter Username") are no longer clipped
  horizontally in the data cells. Each column is sized to the longer of its header word and its
  field-name placeholder, then the whole Tablix is scaled to fit the printable page width.

## [0.6.1] - 2026-07-24

### Fixed

- RDL Tablix header row is now taller than a data row (0.35in vs 0.25in) so two-word column titles
  that wrap onto a second line (for example "Contract Purchaser ID" or "Underwriter Username") are
  no longer clipped in the Report Builder design and print views.

## [0.6.0] - 2026-07-23

### Added

- RDL output format for reports: `cognos2pbi migrate --format rdl` emits a Power BI Report Builder
  paginated report (`.rdl`, RDL 2016 schema) instead of a PBIP semantic model. This is the required
  deliverable for the GM Financial engagement. The generator maps the Cognos list to a `Tablix`
  bound to a SQL `DataSet` (columns and order taken from the list), reproduces letterhead and
  signature text as native `Textbox` items (greeting above the table, closing below), and records
  the physical source query and untranslated detail filters as SQL comments in the dataset
  `CommandText` for a human to complete. `--format pbip` (default) is unchanged.
- Report parser now captures layout static text (letterhead/signature) per page, split into header
  text (before the data list) and footer text (after it), on `ReportPage.header_texts` and
  `ReportPage.footer_texts`.

### Added

- Report layout fidelity for lists: the generated table visual now binds exactly the columns the
  Cognos list shows, in the same order (read from the list's `listColumn` definitions), and is
  sized to fill the page instead of a small default tile. Previously every query column was bound in
  arbitrary order.

## [0.4.6] - 2026-07-16

### Changed

- Removed the built-in Azure OpenAI endpoint and deployment defaults from the package. The `azure`
  provider now requires `COGNOS2PBI_AOAI_ENDPOINT` and `COGNOS2PBI_AOAI_DEPLOYMENT` to be set (see
  `.env.example`), so no specific resource is embedded in the published code.

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
