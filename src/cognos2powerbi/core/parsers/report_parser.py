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
    FilterUse,
    Measure,
    MigrationProject,
    Prompt,
    PromptControlType,
    QueryEdge,
    QueryEdgeKind,
    QueryFilter,
    QueryGraph,
    QueryNode,
    QueryRole,
    Relationship,
    ReportPage,
    Severity,
    Style,
    Table,
    TextBlock,
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

# A Cognos prompt parameter reference inside an expression, for example ``?p_From_Date?``.
_PARAM_REF_RE = re.compile(r"\?([^?]+)\?")

# Cognos set-operation source elements that combine queries into a union query.
_UNION_SOURCE_TAGS = ("queryOperation", "union", "intersect", "except", "setOperation")

# Cognos prompt-control element tags -> (control type, implied data type). Any element carrying a
# ``parameter`` attribute inside a prompt page is treated as a prompt; unknown tags fall back to a
# text/value control so the parameter is still surfaced.
_PROMPT_CONTROLS: dict[str, tuple[PromptControlType, DataType]] = {
    "selectDate": (PromptControlType.DATE, DataType.DATE_TIME),
    "selectDateTime": (PromptControlType.DATE_TIME, DataType.DATE_TIME),
    "selectTime": (PromptControlType.TIME, DataType.DATE_TIME),
    "selectInterval": (PromptControlType.INTERVAL, DataType.STRING),
    "selectValue": (PromptControlType.SELECT_VALUE, DataType.STRING),
    "selectWithList": (PromptControlType.SELECT_VALUE, DataType.STRING),
    "selectWithSearch": (PromptControlType.SELECT_VALUE, DataType.STRING),
    "selectWithTree": (PromptControlType.SELECT_VALUE, DataType.STRING),
    "selectWithRadio": (PromptControlType.SELECT_VALUE, DataType.STRING),
    "selectWithCheckbox": (PromptControlType.SELECT_VALUE, DataType.STRING),
    "textBox": (PromptControlType.TEXT, DataType.STRING),
    "numberBox": (PromptControlType.VALUE, DataType.DOUBLE),
    "generatedPrompt": (PromptControlType.GENERATED, DataType.STRING),
}

# Prompt controls that always collect more than one value.
_MULTI_SELECT_CONTROLS = {"selectWithCheckbox", "selectWithList"}


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


def _has_ancestor(element: etree._Element, tag: str) -> bool:
    """Return True if ``element`` has an ancestor with the given tag."""
    parent = element.getparent()
    while parent is not None:
        if parent.tag == tag:
            return True
        parent = parent.getparent()
    return False


# Default presentation for well-known Cognos style classes (refStyle). Their full definitions live
# in the Cognos global theme, not the report XML, so we encode the visually significant defaults for
# the classes seen in the field. Unknown classes are ignored (they fall back to generator defaults).
_REFSTYLE_DEFAULTS: dict[str, dict[str, object]] = {
    # List column title: bold, horizontally centered (the default Cognos list header treatment).
    "lt": {"bold": True, "text_align": "Center"},
}

# CSS length in points. Cognos emits pt directly; px is converted with the common 0.75pt/px ratio.
_CSS_SIZE_RE = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s*(pt|px)?\s*$", re.IGNORECASE)
_CSS_ALIGN = {"left": "Left", "center": "Center", "right": "Right", "justify": "Justify"}
_CSS_VALIGN = {"top": "Top", "middle": "Middle", "bottom": "Bottom"}


def _css_declarations(css_text: str) -> dict[str, str]:
    """Split a CSS ``value`` string into a lowercase-keyed declaration map."""
    out: dict[str, str] = {}
    for declaration in css_text.split(";"):
        if ":" not in declaration:
            continue
        prop, _, value = declaration.partition(":")
        prop = prop.strip().lower()
        value = value.strip()
        if prop and value:
            out[prop] = value
    return out


def _css_size_pt(value: str) -> float | None:
    match = _CSS_SIZE_RE.match(value)
    if not match:
        return None
    number = float(match.group(1))
    unit = (match.group(2) or "pt").lower()
    return round(number * 0.75, 1) if unit == "px" else number


def _apply_css(style: Style, css_text: str) -> None:
    """Merge CSS declarations from a Cognos ``<CSS value=.../>`` string onto a Style in place."""
    decl = _css_declarations(css_text)
    if "font-family" in decl:
        # Take the first family and strip quotes; drop any generic fallback list.
        family = decl["font-family"].split(",")[0].strip().strip("'\"")
        if family:
            style.font_family = family
    if "font-size" in decl:
        size = _css_size_pt(decl["font-size"])
        if size:
            style.font_size_pt = size
    if "font-weight" in decl:
        weight = decl["font-weight"].strip().lower()
        if weight in {"bold", "bolder"} or (weight.isdigit() and int(weight) >= 600):
            style.bold = True
    if decl.get("font-style", "").lower() == "italic":
        style.italic = True
    if "underline" in decl.get("text-decoration", "").lower():
        style.underline = True
    if "color" in decl:
        style.color = decl["color"].strip()
    if "background-color" in decl:
        style.background_color = decl["background-color"].strip()
    background = decl.get("background")
    if background and style.background_color is None:
        # A shorthand background may carry only a color token; keep it if it looks like one.
        token = background.split()[0].strip() if background.split() else ""
        if token.startswith("#") or token.isalpha():
            style.background_color = token
    if "text-align" in decl:
        style.text_align = _CSS_ALIGN.get(decl["text-align"].strip().lower())
    if "vertical-align" in decl:
        style.vertical_align = _CSS_VALIGN.get(decl["vertical-align"].strip().lower())


def _extract_style(style_element: etree._Element | None) -> Style | None:
    """Build a Style from a Cognos ``<style>`` element (named ``refStyle`` classes plus inline CSS).

    Named classes are applied first (as defaults) and inline CSS overrides them, matching how Cognos
    layers a class reference under an explicit CSS override.
    """
    if style_element is None:
        return None
    style = Style()
    for ref in style_element.iter("defaultStyle"):
        defaults = _REFSTYLE_DEFAULTS.get((ref.get("refStyle") or "").strip())
        if defaults:
            for key, value in defaults.items():
                setattr(style, key, value)
    for css in style_element.iter("CSS"):
        value = css.get("value")
        if value:
            _apply_css(style, value)
    return None if style.is_empty() else style


def _child_style(element: etree._Element) -> Style | None:
    """Return the extracted Style from a direct ``<style>`` child of an element, if any."""
    return _extract_style(element.find("style"))


# Cognos date/time styles -> .NET format strings used by Report Builder.
_COGNOS_DATE_STYLE = {
    "short": "d",
    "shortdate": "d",
    "medium": "d",
    "long": "D",
    "full": "D",
}
_COGNOS_TIME_STYLE = {"short": "t", "medium": "t", "long": "T", "full": "T"}


def _number_pattern(child: etree._Element, default_digits: int) -> tuple[str, str]:
    """Return ``(integer, decimal)`` pattern parts for a Cognos numeric format element."""
    digits_attr = child.get("decimalDigits")
    try:
        digits = int(digits_attr) if digits_attr is not None else default_digits
    except ValueError:
        digits = default_digits
    grouping = (child.get("useGrouping") or "true").strip().lower() != "false"
    integer = "#,##0" if grouping else "0"
    decimal = ("." + "0" * digits) if digits > 0 else ""
    return integer, decimal


def _parse_data_format(data_item: etree._Element) -> str | None:
    """Translate a Cognos ``<dataFormat>`` into a .NET format string, or None when absent.

    Handles the common Cognos format groups: date, time, dateTime, number, currency, and percent.
    Only the first format element in the group is used (Cognos applies one per data item).
    """
    data_format = data_item.find("dataFormat")
    if data_format is None:
        return None
    group = data_format.find("formatGroup")
    if group is None:
        return None
    child = next(iter(group), None)
    if child is None:
        return None
    tag = child.tag if isinstance(child.tag, str) else ""
    if tag == "dateFormat":
        return _COGNOS_DATE_STYLE.get((child.get("dateStyle") or "short").strip().lower(), "d")
    if tag == "timeFormat":
        return _COGNOS_TIME_STYLE.get((child.get("timeStyle") or "short").strip().lower(), "t")
    if tag == "dateTimeFormat":
        return "g"
    if tag == "currencyFormat":
        integer, decimal = _number_pattern(child, 2)
        symbol = child.get("currencySymbol") or "$"
        return f"{symbol}{integer}{decimal}"
    if tag == "percentFormat":
        integer, decimal = _number_pattern(child, 2)
        return f"{integer}{decimal}%"
    if tag == "numberFormat":
        integer, decimal = _number_pattern(child, 0)
        return f"{integer}{decimal}"
    return None


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
        output_queries = self._collect_output_queries(root)
        self._parse_queries(root, project, output_queries)
        self._parse_prompts(root, project)
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

    def _collect_output_queries(self, root: etree._Element) -> set[str]:
        """Return the names of queries bound to a layout object (list, crosstab, or chart).

        These are the report's *output* queries. Every ``refQuery`` under a report page marks the
        query it references as user-facing output; queries referenced only by other queries (join
        operands, union operands, ``queryRef`` sources) or by prompt pages are detail queries
        instead.
        """
        output: set[str] = set()
        for report_pages in root.iter("reportPages"):
            for element in report_pages.iter():
                if not isinstance(element.tag, str):
                    continue
                ref = element.get("refQuery")
                if ref:
                    output.add(_sanitize_identifier(ref))
        return output

    def _parse_queries(
        self, root: etree._Element, project: MigrationProject, output_queries: set[str]
    ) -> None:
        package_flagged = False
        for query in root.iter("query"):
            query_name = _sanitize_identifier(query.get("name") or "Query")
            table = Table(name=query_name, source_query=query_name)
            for data_item in query.iter("dataItem"):
                self._parse_data_item(data_item, table, project)
            if table.columns or table.measures:
                project.tables.append(table)
            self._classify_query(query, query_name, output_queries, project)
            package_flagged = self._parse_query_source(query, table, project, package_flagged)
            self._parse_detail_filters(query, table, project)

    def _classify_query(
        self,
        query: etree._Element,
        query_name: str,
        output_queries: set[str],
        project: MigrationProject,
    ) -> None:
        """Add this query to the project's query graph as a node plus any join/union/ref edges."""
        graph = project.query_graph
        is_output = query_name in output_queries
        role = QueryRole.UNKNOWN
        source = query.find("source")
        if source is not None:
            if source.find("joinOperation") is not None:
                role = QueryRole.JOIN
                self._add_join_edges(source.find("joinOperation"), query_name, graph)
            elif self._union_source(source) is not None:
                role = QueryRole.UNION
                self._add_union_edges(self._union_source(source), query_name, graph)
            elif source.find("queryRef") is not None:
                role = QueryRole.REFERENCE
                ref = _sanitize_identifier(source.find("queryRef").get("refQuery") or "")
                if ref:
                    graph.edges.append(
                        QueryEdge(from_query=query_name, to_query=ref, kind=QueryEdgeKind.REFERENCE)
                    )
        if role == QueryRole.UNKNOWN:
            role = QueryRole.OUTPUT if is_output else QueryRole.DETAIL
        graph.nodes.append(QueryNode(name=query_name, role=role, is_output=is_output))

    @staticmethod
    def _union_source(source: etree._Element) -> etree._Element | None:
        """Return the set-operation element of a source, if the query is a union query."""
        for tag in _UNION_SOURCE_TAGS:
            element = source.find(tag)
            if element is not None:
                return element
        return None

    def _add_join_edges(self, join_op: etree._Element, query_name: str, graph: QueryGraph) -> None:
        """Record a graph edge from the join query to each query it joins, plus the condition."""
        operands: list[str] = []
        for operand in join_op.iter("joinOperand"):
            query_ref = operand.find("queryRef")
            if query_ref is not None and query_ref.get("refQuery"):
                operands.append(_sanitize_identifier(query_ref.get("refQuery")))
        conditions: list[str] = []
        for join_filter in join_op.iter("joinFilter"):
            expression = join_filter.find("filterExpression")
            if expression is not None and expression.text and expression.text.strip():
                conditions.append(expression.text.strip())
        condition = "; ".join(conditions) or None
        for operand in operands:
            graph.edges.append(
                QueryEdge(
                    from_query=query_name,
                    to_query=operand,
                    kind=QueryEdgeKind.JOIN,
                    condition=condition,
                )
            )

    def _add_union_edges(
        self, union_op: etree._Element, query_name: str, graph: QueryGraph
    ) -> None:
        """Record a graph edge from the union query to each operand query it combines."""
        seen: set[str] = set()
        for element in union_op.iter():
            if not isinstance(element.tag, str):
                continue
            ref = element.get("refQuery")
            if ref:
                operand = _sanitize_identifier(ref)
                if operand not in seen:
                    seen.add(operand)
                    graph.edges.append(
                        QueryEdge(from_query=query_name, to_query=operand, kind=QueryEdgeKind.UNION)
                    )

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
        union_op = self._union_source(source)
        if union_op is not None:
            operands = [
                edge.to_query
                for edge in project.query_graph.edges
                if edge.from_query == table.name and edge.kind == QueryEdgeKind.UNION
            ]
            joined = ", ".join(operands) if operands else "its operand queries"
            project.add_flag(
                "union-query",
                f"Query '{table.name}' is a Cognos union/set operation over {joined}. It was "
                "materialized as its own table; recreate the union with Power Query "
                "Table.Combine (append) or a DAX UNION, keeping column order and types aligned.",
                Severity.WARNING,
            )
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
        """Extract each Cognos detail filter with its ``use`` semantics into a structured record.

        The ``use`` attribute drives how Cognos applies a filter:

        - no ``use`` attribute -> mandatory (always applied),
        - ``use="optional"`` -> applied only when its prompt value is supplied,
        - ``use="prohibited"`` -> defined but disabled.

        Each filter becomes a :class:`QueryFilter` on the project (with any referenced prompt
        parameters) and a matching review flag whose wording reflects the ``use`` semantics.
        """
        for detail_filters in query.findall("detailFilters"):
            for detail_filter in detail_filters.iter("detailFilter"):
                expression = detail_filter.find("filterExpression")
                text = expression.text.strip() if expression is not None and expression.text else ""
                if not text:
                    continue
                use = FilterUse.from_attribute(detail_filter.get("use"))
                parameters = self._filter_parameters(text)
                project.filters.append(
                    QueryFilter(
                        query=table.name,
                        expression=text,
                        use=use,
                        parameters=parameters,
                    )
                )
                self._flag_detail_filter(table.name, text, use, project)

    @staticmethod
    def _filter_parameters(expression: str) -> list[str]:
        """Return the distinct prompt parameter names (``?p_x?``) referenced by an expression."""
        seen: list[str] = []
        for match in _PARAM_REF_RE.findall(expression):
            name = match.strip()
            if name and name not in seen:
                seen.append(name)
        return seen

    @staticmethod
    def _flag_detail_filter(
        query_name: str, text: str, use: FilterUse, project: MigrationProject
    ) -> None:
        if use is FilterUse.PROHIBITED:
            project.add_flag(
                "detail-filter-prohibited",
                f"Query '{query_name}' has a Cognos detail filter marked use=\"prohibited\" "
                "(disabled in the source). It was captured but not applied; leave it out unless "
                "you intend to re-enable it.",
                Severity.INFO,
                source_ref=text,
            )
            return
        if use is FilterUse.OPTIONAL:
            project.add_flag(
                "detail-filter-optional",
                f"Query '{query_name}' has an optional Cognos detail filter (applied only when "
                "its prompt value is supplied). Recreate it as a parameter-driven Power Query step "
                "or a report/page filter tied to the corresponding parameter.",
                Severity.WARNING,
                source_ref=text,
            )
            return
        project.add_flag(
            "detail-filter",
            f"Query '{query_name}' has a mandatory Cognos detail filter that was not applied. "
            "Recreate it as a Power Query step, a report/page filter, or a measure filter as "
            "appropriate.",
            Severity.WARNING,
            source_ref=text,
        )

    def _parse_prompts(self, root: etree._Element, project: MigrationProject) -> None:
        """Extract Cognos prompt metadata from ``<promptPages>`` into structured :class:`Prompt`s.

        Any element inside a prompt page that carries a ``parameter`` attribute is treated as a
        prompt control. The control tag classifies the control/prompt type and implied data type;
        attributes and child elements supply the caption, required/multi-select flags, the query
        that supplies selectable values, and default selections. The parameter name is linked back
        to the detail filters that reference it so downstream generators can wire them together.
        """
        seen: set[str] = set()
        for prompt_pages in root.iter("promptPages"):
            for element in prompt_pages.iter():
                if not isinstance(element.tag, str):
                    continue
                param = element.get("parameter")
                if not param:
                    continue
                tag = element.tag
                if tag not in _PROMPT_CONTROLS and not tag.startswith("select"):
                    continue
                param_name = param.strip()
                if not param_name or param_name in seen:
                    continue
                seen.add(param_name)
                project.prompts.append(self._build_prompt(element, param_name, tag, project))
        if project.prompts:
            project.add_flag(
                "prompt-parameters",
                f"Extracted {len(project.prompts)} Cognos prompt parameter(s) from the prompt "
                "pages. Recreate them as RDL ReportParameters or Power BI parameters/slicers; see "
                "the migration metadata for control type, source query, and defaults.",
                Severity.INFO,
            )

    def _build_prompt(
        self,
        element: etree._Element,
        param_name: str,
        tag: str,
        project: MigrationProject,
    ) -> Prompt:
        control_type, data_type = _PROMPT_CONTROLS.get(
            tag, (PromptControlType.SELECT_VALUE, DataType.STRING)
        )
        required = (element.get("required") or "true").strip().lower() != "false"
        multi_select = (
            element.get("multiSelect") or ""
        ).strip().lower() == "true" or tag in _MULTI_SELECT_CONTROLS
        range_prompt = (element.get("range") or "").strip().lower() == "true"
        caption = element.get("caption") or None

        values_query: str | None = None
        value_column: str | None = None
        display_column: str | None = None
        default_values: list[str] = []
        for desc in element.iter():
            if not isinstance(desc.tag, str):
                continue
            ref = desc.get("refQuery")
            if ref and values_query is None:
                values_query = _sanitize_identifier(ref)
            if desc.tag == "useItem" and desc.get("refDataItem") and value_column is None:
                value_column = _sanitize_identifier(desc.get("refDataItem"))
            if desc.tag == "displayItem" and desc.get("refDataItem") and display_column is None:
                display_column = _sanitize_identifier(desc.get("refDataItem"))
            if desc.tag in {"defaultValue", "useValue"}:
                default = (desc.get("useValue") or desc.text or "").strip()
                if default and default not in default_values:
                    default_values.append(default)

        source_query = next((f.query for f in project.filters if param_name in f.parameters), None)
        return Prompt(
            parameter_name=param_name,
            control_type=control_type,
            data_type=data_type,
            caption=caption,
            required=required,
            multi_select=multi_select,
            source_query=source_query,
            values_query=values_query,
            value_column=value_column,
            display_column=display_column,
            default_values=default_values,
            range_prompt=range_prompt,
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
        data_format = _parse_data_format(data_item)

        if aggregate not in {"none", ""}:
            self._add_measure(item_name, cognos_expression, aggregate, table, project, data_format)
            return

        # A plain reference (or cast of a reference) becomes a physical column.
        if _is_reference_like(cognos_expression):
            table.columns.append(
                Column(
                    name=item_name,
                    data_type=data_type,
                    source_column=_reference_source(cognos_expression, item_name),
                    cognos_expression=cognos_expression,
                    format_string=data_format,
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
                    format_string=data_format,
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
                format_string=data_format,
            )
        )

    def _add_measure(
        self,
        item_name: str,
        cognos_expression: str | None,
        aggregate: str,
        table: Table,
        project: MigrationProject,
        format_string: str | None = None,
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
                format_string=format_string,
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
            self._collect_static_text(page, report_page)
            project.pages.append(report_page)

    @staticmethod
    def _collect_static_text(page: etree._Element, report_page: ReportPage) -> None:
        """Capture layout static text (letterhead/signature) split into before/after the data list.

        Static text that appears before the first list becomes header text; text after it becomes
        footer text. Text inside a list (for example a no-data message) is ignored. Each block keeps
        the font/size/color style Cognos set on its ``textItem``.
        """
        seen_list = False
        for element in page.iter():
            tag = element.tag if isinstance(element.tag, str) else ""
            if tag == "list":
                seen_list = True
                continue
            if tag != "staticValue":
                continue
            text = (element.text or "").strip()
            if not text:
                continue
            if _has_ancestor(element, "list"):
                continue
            style = None
            text_item = element.getparent()
            while text_item is not None and text_item.tag != "textItem":
                text_item = text_item.getparent()
            if text_item is not None:
                style = _child_style(text_item)
            block = TextBlock(text=text, style=style)
            if seen_list:
                report_page.footer_blocks.append(block)
            else:
                report_page.header_blocks.append(block)

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
        honor that selection and order, and carry each column's title/body style through so the
        generated report matches the source alignment, font, and weight; otherwise we fall back to
        every column then measure.
        """
        column_names = {column.name for column in table.columns}
        measure_names = {measure.name for measure in table.measures}
        fields: list[VisualField] = []
        seen: set[str] = set()
        for ref, header_style, cell_style in self._layout_columns(obj):
            if ref in seen or (ref not in column_names and ref not in measure_names):
                continue
            seen.add(ref)
            role = "values" if ref in measure_names else "rows"
            fields.append(
                VisualField(
                    table=table.name,
                    name=ref,
                    role=role,
                    header_style=header_style,
                    cell_style=cell_style,
                )
            )
        if fields:
            return fields
        for column in table.columns:
            fields.append(VisualField(table=table.name, name=column.name, role="rows"))
        for measure in table.measures:
            fields.append(VisualField(table=table.name, name=measure.name, role="values"))
        return fields

    @staticmethod
    def _layout_columns(obj: etree._Element) -> list[tuple[str, Style | None, Style | None]]:
        """Return ordered ``(dataItem, titleStyle, bodyStyle)`` tuples for a list's columns."""
        out: list[tuple[str, Style | None, Style | None]] = []
        for column in obj.iter("listColumn"):
            ref = None
            for tag in ("dataItemValue", "dataItemLabel"):
                cell = column.find(f".//{tag}")
                if cell is not None and cell.get("refDataItem"):
                    ref = _sanitize_identifier(cell.get("refDataItem"))
                    break
            if not ref:
                continue
            title = column.find("listColumnTitle")
            body = column.find("listColumnBody")
            title_style = _child_style(title) if title is not None else None
            body_style = _child_style(body) if body is not None else None
            out.append((ref, title_style, body_style))
        return out


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
