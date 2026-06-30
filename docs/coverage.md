# Coverage matrix

This matrix tracks which Cognos constructs are converted today. It is updated as parsers and
generators mature. Contributions that move an item from Planned to Available are especially
welcome.

## Report specification

| Cognos construct | Power BI target | Status |
| --- | --- | --- |
| Query | Semantic-model table | Available |
| Data item (no aggregate) | Column | Available |
| Data item (sum/avg/min/max/count) on a simple reference | DAX measure | Available |
| Data item with a complex expression | DAX measure (deterministic, AI fallback) | Partial |
| List | Table visual | Available |
| Crosstab | Matrix visual | Partial |
| Column / bar / line / pie chart | Corresponding Power BI visual | Partial |
| Page | Report page | Available |
| Data source partitions | Parameterized Power Query (SQL Server) | Available |
| Filters / detail filters | Visual / page filters | Planned |
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
| Data Module | TMDL semantic model | Planned |
| Calculations | DAX measures / columns | Planned |

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
