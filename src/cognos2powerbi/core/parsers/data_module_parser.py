"""Parser for Cognos data modules (Cognos Analytics 11+ ``.module`` JSON).

A data module is the modern successor to a Framework Manager model. It is JSON rather than XML and
describes query subjects (tables), query items (columns and facts), and relationships between them.
This parser is tolerant of the shape variations Cognos emits: references may be strings or arrays,
cardinality may be expressed with ``mincard``/``maxcard`` tokens, and items may be plain columns,
facts with an aggregate, or calculations.

It extracts:

- Query subjects -> semantic-model tables.
- Query items -> columns, with identifiers marked as keys and facts given a default aggregation.
- Relationships -> model relationships, oriented from the many side to the one side.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cognos2powerbi.core.ir.models import (
    Column,
    DataType,
    MigrationProject,
    Relationship,
    Severity,
    Table,
    TableRole,
)

# Cognos regularAggregate -> Power BI summarizeBy.
_AGGREGATE_TO_SUMMARIZE = {
    "total": "sum",
    "sum": "sum",
    "average": "average",
    "avg": "average",
    "minimum": "min",
    "min": "min",
    "maximum": "max",
    "max": "max",
    "count": "count",
    "countdistinct": "distinctCount",
    "calculated": "none",
    "automatic": "none",
    "none": "none",
}

_IDENTIFIER_USAGES = {"identifier", "_identifier", "key"}
_FACT_USAGES = {"fact", "_fact", "measure"}


def _sanitize_identifier(raw: str | None) -> str:
    if not raw:
        return "Unnamed"
    return " ".join(raw.split()) or "Unnamed"


def _label_of(node: dict[str, Any], default: str) -> str:
    for key in ("label", "identifier", "name"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return _sanitize_identifier(value)
    return default


def _ref_tail(ref: Any) -> str | None:
    """Return the last segment of a Cognos reference (string or list form)."""
    if isinstance(ref, list) and ref:
        return _sanitize_identifier(str(ref[-1]))
    if isinstance(ref, str) and ref.strip():
        # References may be dotted or bracketed: [Module].[Sales].[Product ID].
        cleaned = ref.replace("[", "").replace("]", "")
        segments = [seg for seg in cleaned.split(".") if seg.strip()]
        if segments:
            return _sanitize_identifier(segments[-1])
    return None


def _ref_subject(ref: Any) -> str | None:
    """Return the query-subject segment of a Cognos reference."""
    if isinstance(ref, list) and ref:
        return _sanitize_identifier(str(ref[0]))
    if isinstance(ref, str) and ref.strip():
        cleaned = ref.replace("[", "").replace("]", "")
        segments = [seg for seg in cleaned.split(".") if seg.strip()]
        if segments:
            return _sanitize_identifier(segments[0])
    return None


class DataModuleParser:
    """Parse a Cognos data module into a :class:`MigrationProject`."""

    def parse_file(self, path: str | Path) -> MigrationProject:
        source = Path(path)
        if not source.is_file():
            raise FileNotFoundError(f"Data module not found: {source}")
        project = self.parse_bytes(source.read_bytes(), name=source.stem)
        project.source_path = str(source)
        return project

    def parse_bytes(self, payload: bytes, name: str = "MigratedModule") -> MigrationProject:
        try:
            document = json.loads(payload.decode("utf-8", errors="ignore"))
        except ValueError as exc:
            raise ValueError(f"Could not parse data module JSON: {exc}") from exc
        if not isinstance(document, dict):
            raise ValueError("Data module JSON must be an object.")

        module_name = _label_of(document, _sanitize_identifier(name))
        project = MigrationProject(name=module_name)
        self._parse_query_subjects(document, project)
        self._parse_relationships(document, project)

        if not project.tables:
            project.add_flag(
                "no-query-subjects",
                "No query subjects were found in the data module.",
                Severity.ERROR,
            )
        return project

    def _parse_query_subjects(self, document: dict[str, Any], project: MigrationProject) -> None:
        subjects = document.get("querySubject") or document.get("querysubject") or []
        if not isinstance(subjects, list):
            return
        for index, subject in enumerate(subjects, start=1):
            if not isinstance(subject, dict):
                continue
            table_name = _label_of(subject, f"QuerySubject{index}")
            table = Table(name=table_name, source_query=table_name)
            has_fact = False
            for item in subject.get("item", []) or []:
                if not isinstance(item, dict):
                    continue
                query_item = item.get("queryItem")
                if not isinstance(query_item, dict):
                    continue
                if self._add_column(query_item, table, project):
                    has_fact = True
            if has_fact:
                table.role = TableRole.FACT
            if table.columns:
                project.tables.append(table)

    def _add_column(
        self, query_item: dict[str, Any], table: Table, project: MigrationProject
    ) -> bool:
        """Append a column for a query item. Returns True when it is a fact (measure-like)."""
        column_name = _label_of(query_item, "Item")
        data_type = DataType.from_cognos(query_item.get("datatype") or query_item.get("dataType"))
        usage = str(query_item.get("usage") or "").strip().lower()
        aggregate = str(query_item.get("regularAggregate") or query_item.get("aggregate") or "")
        expression = query_item.get("expression")
        cognos_expression = (
            expression if isinstance(expression, str) and expression.strip() else None
        )

        is_key = usage in _IDENTIFIER_USAGES
        is_fact = usage in _FACT_USAGES
        summarize_by: str | None = None
        if is_key:
            summarize_by = "none"
        elif is_fact:
            summarize_by = _AGGREGATE_TO_SUMMARIZE.get(aggregate.lower(), "sum")

        if cognos_expression and usage not in _IDENTIFIER_USAGES:
            project.add_flag(
                "calculation-needs-review",
                f"Query item '{column_name}' in '{table.name}' is a calculation; it was mapped "
                "to a physical column. Recreate it as a DAX column or measure if needed.",
                Severity.INFO,
                source_ref=cognos_expression,
            )

        table.columns.append(
            Column(
                name=column_name,
                data_type=data_type,
                source_column=column_name,
                cognos_expression=cognos_expression,
                is_key=is_key,
                summarize_by=summarize_by,
            )
        )
        return is_fact

    def _parse_relationships(self, document: dict[str, Any], project: MigrationProject) -> None:
        relationships = document.get("relationship") or document.get("relationships") or []
        if not isinstance(relationships, list):
            return
        table_names = {table.name for table in project.tables}
        for index, relationship in enumerate(relationships, start=1):
            if not isinstance(relationship, dict):
                continue
            self._parse_relationship(relationship, index, table_names, project)

    def _parse_relationship(
        self,
        relationship: dict[str, Any],
        index: int,
        table_names: set[str],
        project: MigrationProject,
    ) -> None:
        rel_name = _label_of(relationship, f"Relationship{index}")
        left = relationship.get("left") or {}
        right = relationship.get("right") or {}
        links = relationship.get("link") or relationship.get("links") or []
        if not isinstance(left, dict) or not isinstance(right, dict) or not isinstance(links, list):
            project.add_flag(
                "relationship-needs-review",
                f"Relationship '{rel_name}' could not be parsed and needs manual mapping.",
                Severity.WARNING,
            )
            return

        first_link = next((link for link in links if isinstance(link, dict)), None)
        if first_link is None:
            project.add_flag(
                "relationship-needs-review",
                f"Relationship '{rel_name}' has no column links and needs manual mapping.",
                Severity.WARNING,
            )
            return

        left_subject = _ref_subject(left.get("ref")) or _ref_subject(first_link.get("leftRef"))
        right_subject = _ref_subject(right.get("ref")) or _ref_subject(first_link.get("rightRef"))
        left_column = _ref_tail(first_link.get("leftRef")) or _ref_tail(
            first_link.get("leftItemRef")
        )
        right_column = _ref_tail(first_link.get("rightRef")) or _ref_tail(
            first_link.get("rightItemRef")
        )

        if not (left_subject and right_subject and left_column and right_column):
            project.add_flag(
                "relationship-needs-review",
                f"Relationship '{rel_name}' references columns that could not be resolved.",
                Severity.WARNING,
            )
            return

        if left_subject not in table_names or right_subject not in table_names:
            project.add_flag(
                "relationship-unbound",
                f"Relationship '{rel_name}' references a table that was not found and needs "
                "manual mapping.",
                Severity.WARNING,
            )

        if len([link for link in links if isinstance(link, dict)]) > 1:
            project.add_flag(
                "relationship-composite-key",
                f"Relationship '{rel_name}' joins on a composite key. Power BI relationships use "
                "a single column; the first key pair was used. Add a composite key column if both "
                "are required.",
                Severity.WARNING,
            )

        # Orient from the many side to the one side using the declared cardinality.
        left_is_many = str(left.get("maxcard") or "").lower() in {"many", "n", "*"}
        if left_is_many:
            from_subject, from_column = left_subject, left_column
            to_subject, to_column = right_subject, right_column
        else:
            from_subject, from_column = right_subject, right_column
            to_subject, to_column = left_subject, left_column

        project.relationships.append(
            Relationship(
                from_table=from_subject,
                from_column=from_column,
                to_table=to_subject,
                to_column=to_column,
                name=rel_name,
            )
        )


def parse_data_module(path: str | Path) -> MigrationProject:
    """Convenience wrapper to parse a Cognos data module file."""
    return DataModuleParser().parse_file(path)
