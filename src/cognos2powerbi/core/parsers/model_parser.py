"""Parser for Cognos Framework Manager (FM) model XML.

Framework Manager models describe the logical/physical metadata layer behind Cognos reports:
namespaces, query subjects (tables), query items (columns), and relationships (joins). This parser
is namespace-agnostic and tolerant of the two common naming styles FM emits (a ``name`` attribute
or a ``<name>`` child element).

It extracts:

- Query subjects -> semantic-model tables.
- Query items -> columns (with inferred data types).
- Relationships -> model relationships, derived from the join ``<expression>``.
"""

from __future__ import annotations

import re
from pathlib import Path

from lxml import etree

from cognos2powerbi.core.ir.models import (
    Column,
    DataType,
    MigrationProject,
    Relationship,
    Severity,
    Table,
)

_REFERENCE = re.compile(r"\[[^\[\]]+\](?:\.\[[^\[\]]+\])+")


def _strip_namespaces(tree: etree._Element) -> etree._Element:
    for element in tree.iter():
        if isinstance(element.tag, str) and "}" in element.tag:
            element.tag = element.tag.split("}", 1)[1]
    etree.cleanup_namespaces(tree)
    return tree


def _sanitize_identifier(raw: str) -> str:
    name = re.sub(r"\s+", " ", raw.strip())
    return name or "Unnamed"


def _name_of(element: etree._Element, default: str) -> str:
    """Resolve an FM object name from a ``name`` attribute or a ``<name>`` child."""
    attr = element.get("name")
    if attr:
        return _sanitize_identifier(attr)
    child = element.find("name")
    if child is not None and child.text:
        return _sanitize_identifier(child.text)
    return default


def _child_text(element: etree._Element, *tags: str) -> str | None:
    for tag in tags:
        child = element.find(tag)
        if child is not None and child.text and child.text.strip():
            return child.text.strip()
    return None


def _segments(reference: str) -> list[str]:
    return re.findall(r"\[([^\[\]]+)\]", reference)


class FrameworkManagerParser:
    """Parse a Framework Manager model into a :class:`MigrationProject`."""

    def parse_file(self, path: str | Path) -> MigrationProject:
        source = Path(path)
        if not source.is_file():
            raise FileNotFoundError(f"Framework Manager model not found: {source}")
        project = self.parse_bytes(source.read_bytes(), name=source.stem)
        project.source_path = str(source)
        return project

    def parse_bytes(self, xml_bytes: bytes, name: str = "MigratedModel") -> MigrationProject:
        parser = etree.XMLParser(remove_blank_text=True, recover=True, resolve_entities=False)
        root = etree.fromstring(xml_bytes, parser=parser)
        if root is None:
            raise ValueError("Could not parse Framework Manager model XML: empty or invalid.")
        _strip_namespaces(root)

        project = MigrationProject(name=_sanitize_identifier(name))
        self._parse_query_subjects(root, project)
        self._parse_relationships(root, project)

        if not project.tables:
            project.add_flag(
                "no-query-subjects",
                "No query subjects were found in the Framework Manager model.",
                Severity.ERROR,
            )
        return project

    def _parse_query_subjects(self, root: etree._Element, project: MigrationProject) -> None:
        for index, subject in enumerate(root.iter("querySubject"), start=1):
            table_name = _name_of(subject, f"QuerySubject{index}")
            table = Table(name=table_name, source_query=table_name)
            for item in subject.iter("queryItem"):
                column_name = _name_of(item, "Item")
                data_type_value = _child_text(item, "datatype", "dataType") or item.get("datatype")
                data_type = (
                    DataType.from_cognos(data_type_value) if data_type_value else DataType.STRING
                )
                table.columns.append(
                    Column(
                        name=column_name,
                        data_type=data_type,
                        source_column=column_name,
                    )
                )
            if table.columns:
                project.tables.append(table)

    def _parse_relationships(self, root: etree._Element, project: MigrationProject) -> None:
        table_names = {table.name for table in project.tables}
        for index, relationship in enumerate(root.iter("relationship"), start=1):
            expression = _child_text(relationship, "expression")
            if not expression:
                continue
            references = _REFERENCE.findall(expression)
            if len(references) < 2:
                project.add_flag(
                    "relationship-needs-review",
                    f"Relationship {index} could not be parsed and needs manual mapping.",
                    Severity.WARNING,
                    source_ref=expression,
                )
                continue
            left = _segments(references[0])
            right = _segments(references[1])
            if len(left) < 2 or len(right) < 2:
                continue
            from_table = _sanitize_identifier(left[-2])
            from_column = _sanitize_identifier(left[-1])
            to_table = _sanitize_identifier(right[-2])
            to_column = _sanitize_identifier(right[-1])
            if from_table not in table_names or to_table not in table_names:
                project.add_flag(
                    "relationship-unbound",
                    f"Relationship between '{from_table}' and '{to_table}' references a table "
                    "that was not found and needs manual mapping.",
                    Severity.WARNING,
                    source_ref=expression,
                )
            project.relationships.append(
                Relationship(
                    from_table=from_table,
                    from_column=from_column,
                    to_table=to_table,
                    to_column=to_column,
                )
            )


def parse_model(path: str | Path) -> MigrationProject:
    """Convenience wrapper to parse a Framework Manager model file."""
    return FrameworkManagerParser().parse_file(path)
