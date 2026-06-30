# Data modeling (star schema)

Cognos models are relational: query subjects joined by expressions, with no notion of facts,
dimensions, or filter direction. Power BI works best with a star schema. The modeling pass
(`cognos2powerbi.core.modeling.analyze_model`) runs automatically during `migrate` and
`migrate-model` and turns the relational model into a star schema. Disable it with
`--no-infer-model`.

## What it does

- **Table classification.** Each table becomes a fact, dimension, date, or bridge table. A table
  with measures (or Framework Manager `fact` usage items) is a fact; the rest are dimensions.
- **Date tables.** A dimension with a date/time column and calendar attributes (year, month,
  quarter, and so on) is marked as a date table (`dataCategory: Time`) so time intelligence works.
- **Relationship orientation.** Every relationship is oriented from the many side to the one side,
  matching how Power BI serializes a single-column relationship.
- **Cardinality and cross-filter.** The standard fact-to-dimension join is many-to-one with a
  single-direction filter. Fact-to-fact joins become many-to-many with bidirectional cross-filter.
  Bridge tables get bidirectional cross-filter.
- **Key handling.** Foreign-key columns on fact tables are hidden, and key columns are set not to
  summarize so they are not accidentally aggregated.

## Edge cases that are detected and flagged

Every non-obvious decision is recorded in `MIGRATION_REVIEW.md`:

| Situation | Behavior |
| --- | --- |
| Role-playing dimension (two joins to the same table) | Keep one active relationship; set the others inactive for use with `USERELATIONSHIP`. |
| Ambiguous filter loop | Deactivate the relationship that closes the loop so a single filter path remains. |
| Self-referencing join (parent-child) | Deactivate and flag; model as a hierarchy with `PATH`. |
| Many-to-many join | Flag and set bidirectional cross-filter; verify the grain. |
| Snowflake (dimension to dimension) | Keep the join and flag it as a candidate to flatten. |
| Composite-key join | Use the first key pair and flag; add a composite key column if both are needed. |
| Duplicate relationship | Remove the duplicate. |
| Disconnected (orphan) table | Flag so a relationship can be added. |

## Safety

The pass never emits metadata that would break a refresh. It does not assert key uniqueness, and it
only marks a table as a date table when a real date/time column is present. When in doubt, it leaves
the model loadable and records a review flag instead of guessing.
