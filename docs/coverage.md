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
| Data item with a complex expression | DAX measure (AI-assisted) | Partial |
| List | Table visual | Available |
| Crosstab | Matrix visual | Partial |
| Column / bar / line / pie chart | Corresponding Power BI visual | Partial |
| Page | Report page | Available |
| Filters / detail filters | Visual / page filters | Planned |
| Conditional formatting | Conditional formatting | Planned |
| Prompts and parameters | Slicers / parameters | Planned |

## Models

| Cognos construct | Power BI target | Status |
| --- | --- | --- |
| Framework Manager model | TMDL semantic model | Planned |
| Data Module | TMDL semantic model | Planned |
| Relationships | TMDL relationships | Planned |
| Calculations | DAX measures / columns | Planned |

## Expressions

| Category | Status |
| --- | --- |
| Simple qualified references | Available |
| Arithmetic and aggregate combinations | AI-assisted |
| Conditional logic (if/case) | AI-assisted |
| Date and time functions | Planned (translation library) |

Legend: Available = deterministic; Partial = supported with reduced fidelity; AI-assisted =
requires the AI refinement stage; Planned = not yet implemented.
