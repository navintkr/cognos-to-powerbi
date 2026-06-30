"""Translate a parsed relational model into a Power BI star schema.

Cognos Framework Manager models (and the implicit models behind reports) are relational: a flat
list of query subjects joined by expressions, with no notion of facts, dimensions, or filter
direction. Power BI expects a star schema: fact tables surrounded by dimension tables, with
single-direction filters flowing from the one side to the many side.

:func:`analyze_model` bridges that gap. It mutates a :class:`MigrationProject` in place to:

- Classify every table as a fact, dimension, date, or bridge table.
- Orient each relationship so the many side is ``from`` and the one side is ``to``.
- Infer cardinality (defaulting to the Power BI standard many-to-one) and cross-filter direction.
- Detect and mark date dimensions so time intelligence works.
- Hide foreign-key columns and stop keys from being aggregated.
- Detect and flag the modeling edge cases that need a human decision: ambiguous filter loops,
  role-playing dimensions, self-referencing hierarchies, many-to-many joins, snowflakes, and
  disconnected tables.

The pass is conservative: it never emits metadata that would break a model refresh (for example
it does not assert key uniqueness), and every non-obvious decision is recorded as a review flag.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from cognos2powerbi.core.ir.models import (
    Cardinality,
    Column,
    CrossFilterDirection,
    DataType,
    MigrationProject,
    Relationship,
    Severity,
    Table,
    TableRole,
)

_KEY_TOKENS = {"id", "key", "code", "sk", "nk", "no", "num", "number"}
_DATE_NAME_TOKENS = {"date", "calendar", "period"}
_DATE_PART_TOKENS = {
    "year",
    "month",
    "quarter",
    "week",
    "day",
    "monthname",
    "monthno",
    "fiscalyear",
    "yearmonth",
    "weekday",
    "dayofweek",
    "semester",
}


class ModelingSummary(BaseModel):
    """Counts produced by the star-schema modeling pass."""

    fact_tables: int = 0
    dimension_tables: int = 0
    date_tables: int = 0
    bridge_tables: int = 0
    active_relationships: int = 0
    inactive_relationships: int = 0
    many_to_many_relationships: int = 0


def analyze_model(project: MigrationProject) -> ModelingSummary:
    """Classify tables and infer relationships for *project* in place."""
    tables = {table.name: table for table in project.tables}
    _seed_keys(project)
    _classify_tables(project)
    _detect_date_tables(project)
    _detect_bridges(project)
    _orient_relationships(project, tables)
    _resolve_ambiguity(project)
    if project.relationships:
        _flag_edge_cases(project, tables)
    return _summarize(project)


# --------------------------------------------------------------------- tokens


def _tokens(name: str) -> list[str]:
    """Split an identifier into lower-case word tokens, splitting camelCase too."""
    out: list[str] = []
    for part in re.split(r"[^0-9A-Za-z]+", name):
        if not part:
            continue
        pieces = re.findall(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+", part)
        out.extend(pieces or [part])
    return [token.lower() for token in out]


def _looks_like_key(name: str) -> bool:
    toks = _tokens(name)
    if not toks:
        return False
    return toks[-1] in _KEY_TOKENS or name.strip().lower() in {"id", "key"}


def _key_base_tokens(name: str) -> list[str]:
    """Key-name tokens minus the trailing key suffix (``CategoryID`` -> ``category``)."""
    toks = _tokens(name)
    if len(toks) > 1 and toks[-1] in _KEY_TOKENS:
        return toks[:-1]
    return toks


# ----------------------------------------------------------------- classification


def _seed_keys(project: MigrationProject) -> None:
    for table in project.tables:
        for column in table.columns:
            if column.is_key:
                column.summarize_by = column.summarize_by or "none"
                continue
            if _looks_like_key(column.name) and column.data_type in {
                DataType.INT64,
                DataType.STRING,
            }:
                column.is_key = True
                column.summarize_by = "none"


def _classify_tables(project: MigrationProject) -> None:
    for table in project.tables:
        if table.role in {TableRole.FACT, TableRole.DATE, TableRole.BRIDGE}:
            continue
        table.role = TableRole.FACT if table.measures else TableRole.DIMENSION


def _detect_date_tables(project: MigrationProject) -> None:
    for table in project.tables:
        if table.role == TableRole.FACT:
            continue
        datetime_cols = [c for c in table.columns if c.data_type == DataType.DATE_TIME]
        if not datetime_cols:
            continue
        name_match = any(token in table.name.lower() for token in _DATE_NAME_TOKENS)
        part_count = sum(1 for c in table.columns if set(_tokens(c.name)) & _DATE_PART_TOKENS)
        if not (name_match or part_count >= 2):
            continue
        table.role = TableRole.DATE
        table.is_date_table = True
        table.data_category = "Time"
        _preferred_date_column(datetime_cols).summarize_by = "none"


def _preferred_date_column(datetime_cols: list[Column]) -> Column:
    for column in datetime_cols:
        if "date" in _tokens(column.name):
            return column
    return datetime_cols[0]


def _detect_bridges(project: MigrationProject) -> None:
    counts = _relationship_counts(project)
    for table in project.tables:
        if table.role != TableRole.DIMENSION:
            continue
        keys = [c for c in table.columns if c.is_key]
        non_keys = [c for c in table.columns if not c.is_key]
        if len(keys) >= 2 and not non_keys and counts.get(table.name, 0) >= 2:
            table.role = TableRole.BRIDGE


# ------------------------------------------------------------------- relationships


def _orient_relationships(project: MigrationProject, tables: dict[str, Table]) -> None:
    for rel in project.relationships:
        from_table = tables.get(rel.from_table)
        to_table = tables.get(rel.to_table)
        if from_table is None or to_table is None:
            continue
        if rel.from_table == rel.to_table:
            continue
        if _from_is_one_side(from_table, to_table, rel):
            _flip(rel)
            from_table, to_table = to_table, from_table
        rel.cardinality = _infer_cardinality(from_table, to_table)
        if rel.cardinality == Cardinality.MANY_TO_MANY:
            rel.cross_filter = CrossFilterDirection.BOTH
        if TableRole.BRIDGE in {from_table.role, to_table.role}:
            rel.cross_filter = CrossFilterDirection.BOTH
        _mark_endpoint_columns(from_table, to_table, rel)


def _from_is_one_side(from_table: Table, to_table: Table, rel: Relationship) -> bool:
    """Return ``True`` when the ``from`` table is the one (parent) side and should be flipped."""
    from_fact = from_table.role == TableRole.FACT
    to_fact = to_table.role == TableRole.FACT
    if from_fact and not to_fact:
        return False
    if to_fact and not from_fact:
        return True
    from_pk = _is_probable_primary_key(from_table, rel.from_column)
    to_pk = _is_probable_primary_key(to_table, rel.to_column)
    if from_pk and not to_pk:
        return True
    return False


def _infer_cardinality(from_table: Table, to_table: Table) -> Cardinality:
    if from_table.role == TableRole.FACT and to_table.role == TableRole.FACT:
        return Cardinality.MANY_TO_MANY
    return Cardinality.MANY_TO_ONE


def _is_probable_primary_key(table: Table, column_name: str) -> bool:
    column = table.column(column_name)
    if column is None or not column.is_key:
        return False
    base = set(_key_base_tokens(column_name))
    if not base:
        return True
    return base <= set(_tokens(table.name))


def _mark_endpoint_columns(from_table: Table, to_table: Table, rel: Relationship) -> None:
    to_column = to_table.column(rel.to_column)
    if to_column is not None:
        to_column.is_key = True
        to_column.summarize_by = "none"
    from_column = from_table.column(rel.from_column)
    if from_column is not None and from_table.role == TableRole.FACT:
        from_column.is_foreign_key = True
        from_column.summarize_by = "none"
        from_column.is_hidden = True


def _flip(rel: Relationship) -> None:
    rel.from_table, rel.to_table = rel.to_table, rel.from_table
    rel.from_column, rel.to_column = rel.to_column, rel.from_column


# ----------------------------------------------------------------- ambiguity


def _resolve_ambiguity(project: MigrationProject) -> None:
    project.relationships = _deduplicate(project)

    for rel in project.relationships:
        if rel.from_table == rel.to_table:
            rel.is_active = False
            project.add_flag(
                "relationship-self-join",
                f"Table '{rel.from_table}' references itself on "
                f"'{rel.from_column}' -> '{rel.to_column}'. Power BI cannot self-relate a table; "
                "model this as a parent-child hierarchy using PATH/PATHITEM.",
                Severity.WARNING,
                source_ref=rel.from_table,
            )

    parent: dict[str, str] = {}
    active_pairs: set[frozenset[str]] = set()
    for rel in project.relationships:
        if not rel.is_active or rel.from_table == rel.to_table:
            continue
        pair = frozenset((rel.from_table, rel.to_table))
        if pair in active_pairs:
            rel.is_active = False
            project.add_flag(
                "relationship-role-playing",
                f"Multiple relationships connect '{rel.from_table}' and '{rel.to_table}'. "
                "The extra relationship was set inactive; activate it in DAX with USERELATIONSHIP "
                "(role-playing dimension).",
                Severity.INFO,
                source_ref=f"{rel.from_table} <-> {rel.to_table}",
            )
            continue
        if _find(parent, rel.from_table) == _find(parent, rel.to_table):
            rel.is_active = False
            project.add_flag(
                "relationship-ambiguous-loop",
                f"Relationship '{rel.from_table}' -> '{rel.to_table}' closes an ambiguous filter "
                "loop and was set inactive so a single active filter path remains.",
                Severity.WARNING,
                source_ref=f"{rel.from_table} -> {rel.to_table}",
            )
            continue
        _union(parent, rel.from_table, rel.to_table)
        active_pairs.add(pair)


def _deduplicate(project: MigrationProject) -> list[Relationship]:
    seen: set[tuple[str, str, str, str]] = set()
    kept: list[Relationship] = []
    for rel in project.relationships:
        forward = (rel.from_table, rel.from_column, rel.to_table, rel.to_column)
        reverse = (rel.to_table, rel.to_column, rel.from_table, rel.from_column)
        if forward in seen or reverse in seen:
            project.add_flag(
                "relationship-duplicate",
                f"Duplicate relationship between '{rel.from_table}' and '{rel.to_table}' "
                "was removed.",
                Severity.INFO,
                source_ref=f"{rel.from_table} <-> {rel.to_table}",
            )
            continue
        seen.add(forward)
        kept.append(rel)
    return kept


def _find(parent: dict[str, str], node: str) -> str:
    root = node
    while parent.get(root, root) != root:
        root = parent.get(root, root)
    while parent.get(node, node) != root:
        nxt = parent.get(node, node)
        parent[node] = root
        node = nxt
    return root


def _union(parent: dict[str, str], left: str, right: str) -> None:
    parent[_find(parent, left)] = _find(parent, right)


# ------------------------------------------------------------------ edge cases


def _flag_edge_cases(project: MigrationProject, tables: dict[str, Table]) -> None:
    counts = _relationship_counts(project)
    facts = [t for t in project.tables if t.role == TableRole.FACT]
    dimensional = {TableRole.DIMENSION, TableRole.DATE, TableRole.BRIDGE}
    dims = [t for t in project.tables if t.role in dimensional]

    if len(project.tables) > 1:
        for table in project.tables:
            if counts.get(table.name, 0) == 0:
                project.add_flag(
                    "table-orphan",
                    f"Table '{table.name}' has no relationships and is disconnected from the "
                    "model. Add a relationship or remove it.",
                    Severity.INFO,
                    source_ref=table.name,
                )

    for fact in facts:
        neighbors = _neighbors(project, fact.name)
        if not any(tables[name].role in dimensional for name in neighbors if name in tables):
            project.add_flag(
                "fact-no-dimension",
                f"Fact table '{fact.name}' is not related to any dimension. Joins to its "
                "dimensions could not be inferred.",
                Severity.WARNING,
                source_ref=fact.name,
            )

    if facts and not dims:
        project.add_flag(
            "model-no-dimensions",
            "The model has fact tables but no dimension tables; it is a flat model rather than a "
            "star schema.",
            Severity.INFO,
        )
    if project.tables and not facts:
        project.add_flag(
            "model-no-fact",
            "No fact table could be identified. Define measures so a fact table is recognized.",
            Severity.INFO,
        )

    for rel in project.relationships:
        from_table = tables.get(rel.from_table)
        to_table = tables.get(rel.to_table)
        if from_table is None or to_table is None:
            continue
        snowflake_roles = {TableRole.DIMENSION, TableRole.DATE}
        if (
            rel.from_table != rel.to_table
            and from_table.role in snowflake_roles
            and to_table.role in snowflake_roles
        ):
            project.add_flag(
                "model-snowflake",
                f"Dimension '{rel.from_table}' relates to dimension '{rel.to_table}' (snowflake). "
                "Consider flattening into a single dimension for best performance.",
                Severity.INFO,
                source_ref=f"{rel.from_table} -> {rel.to_table}",
            )
        if rel.cardinality == Cardinality.MANY_TO_MANY and rel.is_active:
            project.add_flag(
                "relationship-many-to-many",
                f"Relationship '{rel.from_table}' -> '{rel.to_table}' is many-to-many. Verify the "
                "grain and consider a bridge table; cross-filtering was set to both directions.",
                Severity.WARNING,
                source_ref=f"{rel.from_table} -> {rel.to_table}",
            )


# --------------------------------------------------------------------- helpers


def _relationship_counts(project: MigrationProject) -> dict[str, int]:
    counts: dict[str, int] = {}
    for rel in project.relationships:
        counts[rel.from_table] = counts.get(rel.from_table, 0) + 1
        if rel.to_table != rel.from_table:
            counts[rel.to_table] = counts.get(rel.to_table, 0) + 1
    return counts


def _neighbors(project: MigrationProject, table_name: str) -> set[str]:
    neighbors: set[str] = set()
    for rel in project.relationships:
        if rel.from_table == table_name:
            neighbors.add(rel.to_table)
        elif rel.to_table == table_name:
            neighbors.add(rel.from_table)
    return neighbors


def _summarize(project: MigrationProject) -> ModelingSummary:
    active = [r for r in project.relationships if r.is_active]
    return ModelingSummary(
        fact_tables=sum(1 for t in project.tables if t.role == TableRole.FACT),
        dimension_tables=sum(1 for t in project.tables if t.role == TableRole.DIMENSION),
        date_tables=sum(1 for t in project.tables if t.role == TableRole.DATE),
        bridge_tables=sum(1 for t in project.tables if t.role == TableRole.BRIDGE),
        active_relationships=len(active),
        inactive_relationships=len(project.relationships) - len(active),
        many_to_many_relationships=sum(
            1 for r in project.relationships if r.cardinality == Cardinality.MANY_TO_MANY
        ),
    )
