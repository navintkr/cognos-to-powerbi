"""Parser for Cognos report specification XML.

Cognos report specifications are namespaced XML produced by Report Studio / Cognos Analytics.
This parser is intentionally namespace-agnostic: it strips namespaces before traversal so a
single implementation handles the range of Cognos schema versions seen in the field.

The parser extracts:

- Queries and their data items -> semantic-model tables, columns, and measures.
- Layout pages and layout objects (list, crosstab, charts) -> report pages and visuals.

Anything that cannot be mapped deterministically is recorded as a review flag on the project
so it can be addressed manually or by the AI refinement stage.
"""

from __future__ import annotations

import re
from pathlib import Path

from lxml import etree

from cognos2powerbi.core.ir.models import (
    Column,
    DataType,
    Measure,
    MigrationProject,
    ReportPage,
    Severity,
    Table,
    Visual,
    VisualField,
    VisualType,
)
from cognos2powerbi.core.translate import translate_measure_expression

_LAYOUT_TO_VISUAL = {
    "list": VisualType.TABLE,
    "crosstab": VisualType.MATRIX,
    "vizColumn": VisualType.COLUMN_CHART,
    "vizBar": VisualType.BAR_CHART,
    "vizLine": VisualType.LINE_CHART,
    "vizPie": VisualType.PIE_CHART,
    "barChart": VisualType.BAR_CHART,
    "columnChart": VisualType.COLUMN_CHART,
    "lineChart": VisualType.LINE_CHART,
    "pieChart": VisualType.PIE_CHART,
}


def _strip_namespaces(tree: etree._Element) -> etree._Element:
    """Remove XML namespaces in place so element lookups are version-agnostic."""
    for element in tree.iter():
        if isinstance(element.tag, str) and "}" in element.tag:
            element.tag = element.tag.split("}", 1)[1]
    etree.cleanup_namespaces(tree)
    return tree


def _sanitize_identifier(raw: str) -> str:
    """Produce a safe Power BI object name from a Cognos label."""
    name = raw.strip()
    name = re.sub(r"\s+", " ", name)
    return name or "Unnamed"


def _infer_data_type(data_item: etree._Element) -> DataType:
    """Infer a TMDL data type from data-item attributes when present."""
    for attr in ("datatype", "dataType", "type"):
        value = data_item.get(attr)
        if value:
            return DataType.from_cognos(value)
    return DataType.STRING


class CognosReportParser:
    """Parse a Cognos report specification into a :class:`MigrationProject`."""

    def parse_file(self, path: str | Path) -> MigrationProject:
        source = Path(path)
        if not source.is_file():
            raise FileNotFoundError(f"Cognos report not found: {source}")
        xml_bytes = source.read_bytes()
        project = self.parse_bytes(xml_bytes, name=source.stem)
        project.source_path = str(source)
        return project

    def parse_bytes(self, xml_bytes: bytes, name: str = "MigratedReport") -> MigrationProject:
        parser = etree.XMLParser(remove_blank_text=True, recover=True, resolve_entities=False)
        root = etree.fromstring(xml_bytes, parser=parser)
        if root is None:
            raise ValueError("Could not parse Cognos report XML: empty or invalid document.")
        _strip_namespaces(root)

        project = MigrationProject(name=_sanitize_identifier(name))
        self._parse_queries(root, project)
        self._parse_layouts(root, project)

        if not project.tables:
            project.add_flag(
                "no-queries",
                "No queries were found in the report specification.",
                Severity.ERROR,
            )
        if not project.pages:
            project.add_flag(
                "no-pages",
                "No report pages were found; a default page was created.",
                Severity.WARNING,
            )
            project.pages.append(ReportPage(name="Page1", display_name="Page 1", visuals=[]))
        return project

    def _parse_queries(self, root: etree._Element, project: MigrationProject) -> None:
        for query in root.iter("query"):
            query_name = _sanitize_identifier(query.get("name") or "Query")
            table = Table(name=query_name, source_query=query_name)
            for data_item in query.iter("dataItem"):
                self._parse_data_item(data_item, table, project)
            if table.columns or table.measures:
                project.tables.append(table)

    def _parse_data_item(
        self, data_item: etree._Element, table: Table, project: MigrationProject
    ) -> None:
        item_name = _sanitize_identifier(data_item.get("name") or "Item")
        aggregate = (data_item.get("aggregate") or "none").strip().lower()
        expression_el = data_item.find("expression")
        cognos_expression = (
            expression_el.text.strip() if expression_el is not None and expression_el.text else None
        )

        if aggregate in {"none", ""}:
            table.columns.append(
                Column(
                    name=item_name,
                    data_type=_infer_data_type(data_item),
                    source_column=item_name,
                    cognos_expression=cognos_expression,
                )
            )
            return

        translation = translate_measure_expression(
            cognos_expression or f"[{item_name}]",
            table.name,
            aggregate,
        )
        needs_review = not translation.confident
        if needs_review:
            project.add_flag(
                "measure-needs-review",
                f"Measure '{item_name}' uses a Cognos expression that needs review after "
                "deterministic translation to DAX.",
                Severity.WARNING,
                source_ref=cognos_expression,
            )
        table.measures.append(
            Measure(
                name=item_name,
                dax_expression=translation.dax,
                cognos_expression=cognos_expression,
                needs_review=needs_review,
            )
        )

    def _parse_layouts(self, root: etree._Element, project: MigrationProject) -> None:
        for index, page in enumerate(root.iter("page"), start=1):
            page_label = page.get("name") or f"Page{index}"
            report_page = ReportPage(
                name=_sanitize_identifier(page_label),
                display_name=_sanitize_identifier(page_label),
            )
            for layout_tag, visual_type in _LAYOUT_TO_VISUAL.items():
                for obj in page.iter(layout_tag):
                    report_page.visuals.append(self._build_visual(obj, visual_type, project))
            project.pages.append(report_page)

    def _build_visual(
        self, obj: etree._Element, visual_type: VisualType, project: MigrationProject
    ) -> Visual:
        ref_query = obj.get("refQuery")
        fields: list[VisualField] = []
        if ref_query:
            table_name = _sanitize_identifier(ref_query)
            table = next((t for t in project.tables if t.name == table_name), None)
            if table:
                for column in table.columns:
                    fields.append(VisualField(table=table_name, name=column.name, role="rows"))
                for measure in table.measures:
                    fields.append(VisualField(table=table_name, name=measure.name, role="values"))
        else:
            project.add_flag(
                "visual-unbound",
                f"A {visual_type.value} visual has no query reference and needs manual binding.",
                Severity.WARNING,
            )
        return Visual(visual_type=visual_type, fields=fields)


def _is_simple_reference(expression: str) -> bool:
    """Return True when a Cognos expression is a plain qualified reference like [A].[B].[C]."""
    return bool(re.fullmatch(r"\[[^\[\]]+\](?:\.\[[^\[\]]+\])*", expression.strip()))


def parse_report(path: str | Path) -> MigrationProject:
    """Convenience wrapper to parse a Cognos report file into a migration project."""
    return CognosReportParser().parse_file(path)
