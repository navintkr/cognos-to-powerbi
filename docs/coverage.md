# Coverage matrix

This matrix tracks which Cognos constructs are converted today. It is updated as parsers and
generators mature. Contributions that move an item from Planned to Available are especially
welcome.

## Report specification

| Cognos construct | Power BI target | Status |
| --- | --- | --- |
| Query | Semantic-model table | Available |
| Data item (no aggregate) | Column | Available |
| Data item data type | TMDL type from RS_dataType, `cast(...)`, and numeric functions | Available |
| Data item (sum/avg/min/max/count) on a simple reference | DAX measure | Available |
| Calculated data item (deterministic) | DAX calculated column | Available |
| Calculated data item (AI-assisted) | DAX calculated column (verify) | AI-assisted |
| Calculated data item (unmapped) | Physical column, flagged for review | Partial |
| Query join (`joinOperation`) | Relationship (oriented from the many side) | Available |
| Derived query (`queryRef`) | Table, flagged to relate or replace | Partial |
| Detail filters | Flagged for review (manual Power Query / report filter) | Planned |
| List | Table visual (exact columns, in list order, page-sized) | Available |
| Crosstab | Matrix visual | Partial |
| Column / bar / line / pie chart | Corresponding Power BI visual | Partial |
| Page | Report page | Available |
| Data source partitions | Parameterized Power Query (SQL Server) | Available |
| Package / model source | Flagged (partitions are placeholders to repoint) | Partial |
| Conditional formatting | Conditional formatting | Planned |
| Prompts and parameters | Slicers / parameters | Planned |

## Models

| Cognos construct | Power BI target | Status |
| --- | --- | --- |
| Framework Manager model | TMDL semantic model | Available |
| Query subject | Semantic-model table | Available |
| Query item | Column | Available |
| Relationships | TMDL relationships | Available |
| Fact / dimension classification | Table roles (star schema) | Available |
| Relationship cardinality and cross-filter | TMDL cardinality / crossFilteringBehavior | Available |
| Date dimension | Date table (dataCategory Time) | Available |
| Role-playing dimensions | Inactive relationship + USERELATIONSHIP guidance | Available |
| Ambiguous loops / many-to-many / snowflake / self-join | Detected and flagged for review | Available |
| Composite-key joins | First key pair used, flagged for review | Partial |
| Data module (.module JSON) | TMDL semantic model | Available |
| Data module facts | Columns with summarizeBy (sum/avg/min/max/count) | Available |
| Data module identifiers | Key columns | Available |
| Data module calculations | Physical column, flagged for review | Partial |

## Dashboards

| Cognos construct | Power BI target | Status |
| --- | --- | --- |
| Dashboard / exploration | PBIR report | Available |
| Tabs | Report pages | Available |
| Column / bar / line / pie / list / crosstab widget | Corresponding Power BI visual | Available |
| Widget data items | Visual fields with synthesized tables | Available |
| Slot mapping (categories, values, series) | Visual field roles | Available |
| Text / image / media widgets | Skipped (no data binding) | Partial |

## Batch and portal

| Capability | Status |
| --- | --- |
| Auto-detect source kind (report, model, module, dashboard) | Available |
| Batch / folder migration | Available |
| Coverage report (Markdown and JSON) | Available |
| SaaS portal upload, analyze, review flags, download | Available |
| SaaS portal batch upload (zip download) | Available |

## Expressions

| Category | Status |
| --- | --- |
| Simple qualified references | Available |
| Arithmetic and aggregate combinations | Available |
| Conditional logic (if/case) | Available |
| String functions (substring, length, upper/lower, trim) | Available |
| Date and time functions (extract year/month/day) | Available |
| Unsupported or vendor-specific functions | AI-assisted |

Legend: Available = deterministic; Partial = supported with reduced fidelity; AI-assisted =
requires the AI refinement stage; Planned = not yet implemented.
