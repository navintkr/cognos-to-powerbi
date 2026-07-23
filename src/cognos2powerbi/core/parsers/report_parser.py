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
    Cardinality,
    Column,
    DataType,
    Measure,
    MigrationProject,
    Relationship,
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

# Cognos Report Studio RS_dataType numeric codes -> TMDL data type. Codes seen in the field:
# 3 = character/string, 4 = dateTime, 5 = time, 7 = date, 8 = interval/timestamp, others numeric.
_RS_DATATYPE_TO_TMDL = {
    "1": DataType.INT64,
    "2": DataType.INT64,
    "3": DataType.STRING,
    "4": DataType.DATE_TIME,
    "5": DataType.DATE_TIME,
    "7": DataType.DATE_TIME,
    "8": DataType.DATE_TIME,
    "9": DataType.DECIMAL,
    "10": DataType.DOUBLE,
}

# A plain qualified Cognos reference such as [Namespace].[Query Subject].[Item].
_SIMPLE_REF_RE = re.compile(r"^\[[^\[\]]+\](?:\.\[[^\[\]]+\])*$")
# cast([reference]; targetType) - a type coercion of a single reference.
_CAST_FULL_RE = re.compile(
    r"^cast\s*\(\s*(?P<inner>.+?)\s*;\s*(?P<type>[A-Za-z0-9_]+)\s*\)$",
    re.IGNORECASE | re.DOTALL,
)
# Cognos functions that imply an integer or floating result when no type hint is present.
_COUNT_FUNCS_RE = re.compile(
    r"\b(running[-_]count|running[-_]total|count|_?rowcount)\s*\(", re.IGNORECASE
)
_FLOAT_FUNCS_RE = re.compile(
    r"\b(average|avg|median|stddev|std[-_]?dev|variance|percentile|ratio)\s*\(", re.IGNORECASE
)
# A join filter of the form [A].[col] = [B].[col].
_JOIN_EQUALITY_RE = re.compile(
    r"^\s*(?P<left>\[[^\[\]]+\](?:\.\[[^\[\]]+\])*)\s*=\s*(?P<right>\[[^\[\]]+\](?:\.\[[^\[\]]+\])*)\s*$"
)


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


def _last_segment(reference: str) -> str:
    """Return the final ``[segment]`` of a qualified Cognos reference, without brackets."""
    parts = re.findall(r"\[([^\[\]]+)\]", reference)
    return _sanitize_identifier(parts[-1]) if parts else reference.strip("[]")


def _rs_data_type(data_item: etree._Element) -> DataType | None:
    """Return the TMDL type implied by an ``RS_dataType`` XML attribute, if present."""
    for attr in data_item.iter("XMLAttribute"):
        if attr.get("name") == "RS_dataType":
            code = (attr.get("value") or "").strip()
            return _RS_DATATYPE_TO_TMDL.get(code)
    return None


def _infer_data_type(data_item: etree._Element, expression: str | None) -> DataType:
    """Infer a TMDL data type from data-item attributes, RS_dataType, or the expression."""
    for attr in ("datatype", "dataType", "type"):
        value = data_item.get(attr)
        if value:
            return DataType.from_cognos(value)
    rs_type = _rs_data_type(data_item)
    if rs_type is not None:
        return rs_type
    if expression:
        cast = _CAST_FULL_RE.match(expression.strip())
        if cast:
            return DataType.from_cognos(cast.group("type"))
        if _COUNT_FUNCS_RE.search(expression):
            return DataType.INT64
        if _FLOAT_FUNCS_RE.search(expression):
            return DataType.DOUBLE
    return DataType.STRING


def _reference_source(expression: str | None, fallback: str) -> str:
    """Return the physical source column for a reference or cast-of-reference expression."""
    if not expression:
        return fallback
    expr = expression.strip()
    if _SIMPLE_REF_RE.match(expr):
        return _last_segment(expr)
    cast = _CAST_FULL_RE.match(expr)
    if cast and _SIMPLE_REF_RE.match(cast.group("inner").strip()):
        return _last_segment(cast.group("inner").strip())
    return fallback


def _is_reference_like(expression: str | None) -> bool:
    """Return True when the expression is a plain reference or a cast of a plain reference."""
    if not expression or not expression.strip():
        return True
    expr = expression.strip()
    if _SIMPLE_REF_RE.match(expr):
        return True
    cast = _CAST_FULL_RE.match(expr)
    return bool(cast and _SIMPLE_REF_RE.match(cast.group("inner").strip()))


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
        package_flagged = False
        for query in root.iter("query"):
            query_name = _sanitize_identifier(query.get("name") or "Query")
            table = Table(name=query_name, source_query=query_name)
            for data_item in query.iter("dataItem"):
                self._parse_data_item(data_item, table, project)
            if table.columns or table.measures:
                project.tables.append(table)
            package_flagged = self._parse_query_source(query, table, project, package_flagged)
            self._parse_detail_filters(query, table, project)

    def _parse_query_source(
        self,
        query: etree._Element,
        table: Table,
        project: MigrationProject,
        package_flagged: bool,
    ) -> bool:
        """Parse a query source: capture joins as relationships; flag derived/package sources."""
        source = query.find("source")
        if source is None:
            return package_flagged
        join_op = source.find("joinOperation")
        if join_op is not None:
            self._parse_join(join_op, table, project)
            return package_flagged
        query_ref = source.find("queryRef")
        if query_ref is not None:
            ref = _sanitize_identifier(query_ref.get("refQuery") or "source")
            project.add_flag(
                "derived-query",
                f"Query '{table.name}' is derived from query '{ref}' (a Cognos query reference). "
                "It was materialized as its own table; relate or replace it if you need a single "
                "source of truth.",
                Severity.INFO,
            )
            return package_flagged
        if source.find("model") is not None and not package_flagged:
            project.add_flag(
                "package-source",
                "The report binds to a Cognos package/model rather than a physical table. The "
                "generated tables use parameterized Server/Database placeholders; point each "
                "partition at the real table or view before refreshing.",
                Severity.WARNING,
            )
            return True
        return package_flagged

    def _parse_join(self, join_op: etree._Element, table: Table, project: MigrationProject) -> None:
        cardinalities: dict[str, str] = {}
        for operand in join_op.iter("joinOperand"):
            query_ref = operand.find("queryRef")
            if query_ref is not None:
                ref_name = _sanitize_identifier(query_ref.get("refQuery") or "")
                cardinalities[ref_name] = (operand.get("cardinality") or "").strip()
        for join_filter in join_op.iter("joinFilter"):
            expression = join_filter.find("filterExpression")
            text = expression.text.strip() if expression is not None and expression.text else ""
            self._relationship_from_join(text, cardinalities, table, project)

    def _relationship_from_join(
        self,
        filter_text: str,
        cardinalities: dict[str, str],
        table: Table,
        project: MigrationProject,
    ) -> None:
        match = _JOIN_EQUALITY_RE.match(filter_text)
        if not match:
            if filter_text:
                project.add_flag(
                    "join-needs-review",
                    f"The join for query '{table.name}' uses a condition that could not be mapped "
                    "to a Power BI relationship and needs manual modeling.",
                    Severity.WARNING,
                    source_ref=filter_text,
                )
            return
        left, right = match.group("left"), match.group("right")
        left_parts = re.findall(r"\[([^\[\]]+)\]", left)
        right_parts = re.findall(r"\[([^\[\]]+)\]", right)
        if len(left_parts) < 2 or len(right_parts) < 2:
            return
        left_table = _sanitize_identifier(left_parts[0])
        right_table = _sanitize_identifier(right_parts[0])
        left_col = _sanitize_identifier(left_parts[-1])
        right_col = _sanitize_identifier(right_parts[-1])
        left_many = _cardinality_is_many(cardinalities.get(left_table, ""))
        right_many = _cardinality_is_many(cardinalities.get(right_table, ""))
        if right_many and not left_many:
            from_table, from_col, to_table, to_col = right_table, right_col, left_table, left_col
        else:
            from_table, from_col, to_table, to_col = left_table, left_col, right_table, right_col
        cardinality = (
            Cardinality.MANY_TO_ONE if (left_many or right_many) else Cardinality.ONE_TO_ONE
        )
        project.relationships.append(
            Relationship(
                from_table=from_table,
                from_column=from_col,
                to_table=to_table,
                to_column=to_col,
                cardinality=cardinality,
                name=f"{from_table}_{to_table}",
            )
        )
        project.add_flag(
            "join-relationship",
            f"Added a relationship {from_table}[{from_col}] -> {to_table}[{to_col}] from the "
            f"Cognos join in query '{table.name}'. Verify the cardinality and cross-filter "
            "direction in Power BI.",
            Severity.INFO,
        )

    def _parse_detail_filters(
        self, query: etree._Element, table: Table, project: MigrationProject
    ) -> None:
        for detail_filters in query.findall("detailFilters"):
            for detail_filter in detail_filters.iter("detailFilter"):
                expression = detail_filter.find("filterExpression")
                text = expression.text.strip() if expression is not None and expression.text else ""
                if text:
                    project.add_flag(
                        "detail-filter",
                        f"Query '{table.name}' has a Cognos detail filter that was not applied. "
                        "Recreate it as a Power Query step, a report/page filter, or a measure "
                        "filter as appropriate.",
                        Severity.WARNING,
                        source_ref=text,
                    )

    def _parse_data_item(
        self, data_item: etree._Element, table: Table, project: MigrationProject
    ) -> None:
        item_name = _sanitize_identifier(data_item.get("name") or "Item")
        aggregate = (data_item.get("aggregate") or "none").strip().lower()
        expression_el = data_item.find("expression")
        cognos_expression = (
            expression_el.text.strip() if expression_el is not None and expression_el.text else None
        )
        data_type = _infer_data_type(data_item, cognos_expression)

        if aggregate not in {"none", ""}:
            self._add_measure(item_name, cognos_expression, aggregate, table, project)
            return

        # A plain reference (or cast of a reference) becomes a physical column.
        if _is_reference_like(cognos_expression):
            table.columns.append(
                Column(
                    name=item_name,
                    data_type=data_type,
                    source_column=_reference_source(cognos_expression, item_name),
                    cognos_expression=cognos_expression,
                )
            )
            return

        # A calculation. Emit a DAX calculated column only when the deterministic translation is
        # confident, so the model always loads. Otherwise keep a loadable physical column and flag
        # it (the AI stage may later replace it with a calculated column).
        translation = translate_measure_expression(cognos_expression, table.name, "none")
        if translation.confident and translation.dax:
            table.columns.append(
                Column(
                    name=item_name,
                    data_type=data_type,
                    cognos_expression=cognos_expression,
                    dax_expression=translation.dax,
                    is_calculated=True,
                )
            )
            return
        project.add_flag(
            "calculation-needs-review",
            f"Data item '{item_name}' in query '{table.name}' is a Cognos calculation that has no "
            "deterministic DAX mapping. It was kept as a physical column so the model loads; "
            "recreate it as a DAX calculated column or measure (or run AI refinement).",
            Severity.WARNING,
            source_ref=cognos_expression,
        )
        table.columns.append(
            Column(
                name=item_name,
                data_type=data_type,
                source_column=item_name,
                cognos_expression=cognos_expression,
                needs_calculation=True,
            )
        )

    def _add_measure(
        self,
        item_name: str,
        cognos_expression: str | None,
        aggregate: str,
        table: Table,
        project: MigrationProject,
    ) -> None:
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
                fields = self._visual_fields(obj, table)
        else:
            project.add_flag(
                "visual-unbound",
                f"A {visual_type.value} visual has no query reference and needs manual binding.",
                Severity.WARNING,
            )
        # Tables and matrices are the main content of a Cognos list report; size them to fill the
        # page so the layout resembles the source instead of a small default tile.
        if visual_type in {VisualType.TABLE, VisualType.MATRIX}:
            return Visual(
                visual_type=visual_type, fields=fields, x=24.0, y=24.0, width=1232.0, height=672.0
            )
        return Visual(visual_type=visual_type, fields=fields)

    def _visual_fields(self, obj: etree._Element, table: Table) -> list[VisualField]:
        """Bind the visual to exactly the columns the Cognos layout shows, in their shown order.

        A Cognos list declares its columns (and order) via ``listColumn`` entries. When present we
        honor that selection and order; otherwise we fall back to every column then measure.
        """
        column_names = {column.name for column in table.columns}
        measure_names = {measure.name for measure in table.measures}
        fields: list[VisualField] = []
        seen: set[str] = set()
        for ref in self._layout_column_refs(obj):
            if ref in seen or (ref not in column_names and ref not in measure_names):
                continue
            seen.add(ref)
            role = "values" if ref in measure_names else "rows"
            fields.append(VisualField(table=table.name, name=ref, role=role))
        if fields:
            return fields
        for column in table.columns:
            fields.append(VisualField(table=table.name, name=column.name, role="rows"))
        for measure in table.measures:
            fields.append(VisualField(table=table.name, name=measure.name, role="values"))
        return fields

    @staticmethod
    def _layout_column_refs(obj: etree._Element) -> list[str]:
        """Return the ordered data-item names referenced by a list's columns."""
        refs: list[str] = []
        for column in obj.iter("listColumn"):
            ref = None
            for tag in ("dataItemValue", "dataItemLabel"):
                cell = column.find(f".//{tag}")
                if cell is not None and cell.get("refDataItem"):
                    ref = _sanitize_identifier(cell.get("refDataItem"))
                    break
            if ref:
                refs.append(ref)
        return refs


def _cardinality_is_many(cardinality: str) -> bool:
    """Return True when a Cognos join cardinality string denotes a many side (n, *, or 1:n)."""
    text = cardinality.strip().lower()
    if not text:
        return False
    right = text.split(":")[-1] if ":" in text else text
    return right in {"n", "*", "many"} or right not in {"0", "1"}


def parse_report(path: str | Path) -> MigrationProject:
    """Convenience wrapper to parse a Cognos report file into a migration project."""
    return CognosReportParser().parse_file(path)
