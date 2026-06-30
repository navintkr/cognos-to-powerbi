"""Parser for Cognos dashboards and explorations (Cognos Analytics JSON).

A Cognos dashboard is JSON describing a canvas of widgets. Each widget renders a visualization
(column chart, list, crosstab, and so on) bound to data items from a data module or package. This
parser maps the dashboard onto Power BI report pages and visuals, and synthesizes the minimal set
of tables and columns that the visuals reference so the generated report binds cleanly.

It is tolerant of the shape variations Cognos emits: pages may be a flat list of widgets or nested
tabs, widget data may live under ``data.dataViews`` or ``datasets``, and references may be dotted or
bracketed strings or arrays.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cognos2powerbi.core.ir.models import (
    Column,
    MigrationProject,
    ReportPage,
    Severity,
    Table,
    Visual,
    VisualField,
    VisualType,
)

# Cognos visualization id / name -> Power BI visual type.
_VISUAL_MAP = {
    "column": VisualType.COLUMN_CHART,
    "clusteredcolumn": VisualType.COLUMN_CHART,
    "stackedcolumn": VisualType.COLUMN_CHART,
    "bar": VisualType.BAR_CHART,
    "clusteredbar": VisualType.BAR_CHART,
    "stackedbar": VisualType.BAR_CHART,
    "line": VisualType.LINE_CHART,
    "spline": VisualType.LINE_CHART,
    "area": VisualType.LINE_CHART,
    "pie": VisualType.PIE_CHART,
    "donut": VisualType.PIE_CHART,
    "list": VisualType.TABLE,
    "table": VisualType.TABLE,
    "datatable": VisualType.TABLE,
    "crosstab": VisualType.MATRIX,
    "pivot": VisualType.MATRIX,
    "summary": VisualType.CARD,
    "kpi": VisualType.CARD,
    "singleton": VisualType.CARD,
    "kpisparkline": VisualType.CARD,
}

# Cognos slot name -> Power BI visual field role.
_SLOT_ROLE_MAP = {
    "categories": "category",
    "category": "category",
    "ordinal": "category",
    "x": "category",
    "values": "values",
    "value": "values",
    "y": "values",
    "length": "values",
    "size": "values",
    "series": "series",
    "color": "series",
    "rows": "rows",
    "columns": "columns",
}


def _sanitize_identifier(raw: str | None) -> str:
    if not raw:
        return "Unnamed"
    return " ".join(raw.split()) or "Unnamed"


def _split_reference(reference: str) -> tuple[str, str]:
    """Split a Cognos item reference into (table, column)."""
    cleaned = reference.replace("[", "").replace("]", "")
    segments = [seg.strip() for seg in cleaned.split(".") if seg.strip()]
    if len(segments) >= 2:
        return _sanitize_identifier(segments[-2]), _sanitize_identifier(segments[-1])
    if segments:
        return "Data", _sanitize_identifier(segments[-1])
    return "Data", "Unnamed"


def _percent(value: Any, default: float) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().rstrip("%").strip()
        try:
            return float(text)
        except ValueError:
            return default
    return default


class DashboardParser:
    """Parse a Cognos dashboard into a :class:`MigrationProject`."""

    _CANVAS_WIDTH = 1280
    _CANVAS_HEIGHT = 720

    def parse_file(self, path: str | Path) -> MigrationProject:
        source = Path(path)
        if not source.is_file():
            raise FileNotFoundError(f"Dashboard not found: {source}")
        project = self.parse_bytes(source.read_bytes(), name=source.stem)
        project.source_path = str(source)
        return project

    def parse_bytes(self, payload: bytes, name: str = "MigratedDashboard") -> MigrationProject:
        try:
            document = json.loads(payload.decode("utf-8", errors="ignore"))
        except ValueError as exc:
            raise ValueError(f"Could not parse dashboard JSON: {exc}") from exc
        if not isinstance(document, dict):
            raise ValueError("Dashboard JSON must be an object.")

        project = MigrationProject(name=_sanitize_identifier(name))
        widgets = self._widget_index(document)
        self._tables: dict[str, Table] = {}

        pages = self._extract_pages(document, widgets)
        for page in pages:
            project.pages.append(page)

        for table in self._tables.values():
            project.tables.append(table)

        if not project.pages:
            project.add_flag(
                "no-pages",
                "No dashboard tabs were found; a default page was created.",
                Severity.WARNING,
            )
            project.pages.append(ReportPage(name="Page1", display_name="Page 1", visuals=[]))
        if not project.tables:
            project.add_flag(
                "dashboard-no-data",
                "No data items were found in the dashboard widgets; visuals have no bindings.",
                Severity.WARNING,
            )
        return project

    def _widget_index(self, document: dict[str, Any]) -> dict[str, dict[str, Any]]:
        widgets = document.get("widgets")
        if isinstance(widgets, dict):
            return {key: value for key, value in widgets.items() if isinstance(value, dict)}
        if isinstance(widgets, list):
            index: dict[str, dict[str, Any]] = {}
            for widget in widgets:
                if isinstance(widget, dict):
                    widget_id = str(widget.get("id") or len(index))
                    index[widget_id] = widget
            return index
        return {}

    def _extract_pages(
        self, document: dict[str, Any], widgets: dict[str, dict[str, Any]]
    ) -> list[ReportPage]:
        layout = document.get("layout")
        pages: list[ReportPage] = []
        if isinstance(layout, dict):
            items = layout.get("items")
            if isinstance(items, list) and items:
                tabs = [item for item in items if isinstance(item, dict)]
                # A layout whose top-level items are themselves containers represents tabs/pages;
                # otherwise the items are widgets on a single page.
                top_are_pages = any(isinstance(item.get("items"), list) for item in tabs)
                if top_are_pages:
                    for index, tab in enumerate(tabs, start=1):
                        pages.append(self._build_page(tab, index, widgets))
                else:
                    pages.append(self._build_page(layout, 1, widgets))
        if not pages and widgets:
            # No usable layout; place every widget on a single page.
            synthetic = {"items": [{"id": wid} for wid in widgets]}
            pages.append(self._build_page(synthetic, 1, widgets))
        return pages

    def _build_page(
        self, container: dict[str, Any], index: int, widgets: dict[str, dict[str, Any]]
    ) -> ReportPage:
        label = container.get("name") or container.get("title") or container.get("label")
        page = ReportPage(
            name=_sanitize_identifier(str(label) if label else f"Page{index}"),
            display_name=_sanitize_identifier(str(label) if label else f"Page {index}"),
        )
        widget_nodes = self._collect_widget_nodes(container)
        for node in widget_nodes:
            widget_id = str(node.get("id") or "")
            widget = widgets.get(widget_id)
            if widget is None:
                continue
            visual = self._build_visual(widget, node)
            if visual is not None:
                page.visuals.append(visual)
        return page

    def _collect_widget_nodes(self, container: dict[str, Any]) -> list[dict[str, Any]]:
        """Walk a layout subtree and return the leaf nodes that reference a widget id."""
        nodes: list[dict[str, Any]] = []
        items = container.get("items")
        if not isinstance(items, list):
            return nodes
        for item in items:
            if not isinstance(item, dict):
                continue
            child_items = item.get("items")
            if isinstance(child_items, list) and child_items:
                nodes.extend(self._collect_widget_nodes(item))
            elif item.get("id"):
                nodes.append(item)
        return nodes

    def _build_visual(self, widget: dict[str, Any], node: dict[str, Any]) -> Visual | None:
        widget_type = str(widget.get("type") or "").strip().lower()
        if widget_type in {"text", "image", "media", "shape", "webpage"}:
            # Decorative widgets carry no data; record them for awareness but skip binding.
            return Visual(visual_type=VisualType.CARD, fields=[])

        visual_type = self._resolve_visual_type(widget)
        fields = self._extract_fields(widget)
        position = node.get("style") or widget.get("style") or {}
        x = _percent(position.get("left") or position.get("x"), 0.0)
        y = _percent(position.get("top") or position.get("y"), 0.0)
        width = _percent(position.get("width"), 50.0)
        height = _percent(position.get("height"), 50.0)
        return Visual(
            visual_type=visual_type,
            fields=fields,
            x=x / 100.0 * self._CANVAS_WIDTH,
            y=y / 100.0 * self._CANVAS_HEIGHT,
            width=max(width / 100.0 * self._CANVAS_WIDTH, 160.0),
            height=max(height / 100.0 * self._CANVAS_HEIGHT, 120.0),
        )

    def _resolve_visual_type(self, widget: dict[str, Any]) -> VisualType:
        for key in ("name", "visTipId", "visId", "visualization", "subType", "type"):
            value = widget.get(key)
            if isinstance(value, str):
                token = value.replace("_", "").replace("-", "").strip().lower()
                if token in _VISUAL_MAP:
                    return _VISUAL_MAP[token]
        return VisualType.TABLE

    def _extract_fields(self, widget: dict[str, Any]) -> list[VisualField]:
        data_items = self._data_items(widget)
        slot_roles = self._slot_roles(widget)
        fields: list[VisualField] = []
        for item_id, item in data_items.items():
            reference = (
                item.get("itemId") or item.get("itemLabel") or item.get("ref") or item.get("id")
            )
            if not isinstance(reference, str) or not reference.strip():
                continue
            table_name, column_name = _split_reference(reference)
            self._ensure_column(table_name, column_name)
            role = slot_roles.get(item_id, "values")
            fields.append(VisualField(table=table_name, name=column_name, role=role))
        return fields

    def _data_items(self, widget: dict[str, Any]) -> dict[str, dict[str, Any]]:
        data = widget.get("data")
        items: dict[str, dict[str, Any]] = {}
        if not isinstance(data, dict):
            return items
        views = data.get("dataViews") or data.get("datasets") or []
        if isinstance(views, list):
            for view in views:
                if not isinstance(view, dict):
                    continue
                for item in view.get("dataItems") or view.get("modelItems") or []:
                    if isinstance(item, dict):
                        item_id = str(item.get("id") or len(items))
                        items[item_id] = item
        return items

    def _slot_roles(self, widget: dict[str, Any]) -> dict[str, str]:
        mapping = widget.get("slotmapping") or widget.get("slotMapping") or {}
        roles: dict[str, str] = {}
        if not isinstance(mapping, dict):
            return roles
        for slot in mapping.get("slots") or []:
            if not isinstance(slot, dict):
                continue
            slot_name = str(slot.get("name") or "").strip().lower()
            role = _SLOT_ROLE_MAP.get(slot_name, "values")
            for item_id in slot.get("dataItems") or slot.get("dataItemIds") or []:
                roles[str(item_id)] = role
        return roles

    def _ensure_column(self, table_name: str, column_name: str) -> None:
        table = self._tables.get(table_name)
        if table is None:
            table = Table(name=table_name, source_query=table_name)
            self._tables[table_name] = table
        if table.column(column_name) is None:
            table.columns.append(Column(name=column_name, source_column=column_name))


def parse_dashboard(path: str | Path) -> MigrationProject:
    """Convenience wrapper to parse a Cognos dashboard file."""
    return DashboardParser().parse_file(path)
