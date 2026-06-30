"""Tests for the Cognos dashboard parser and dashboard migration."""

from __future__ import annotations

from pathlib import Path

from cognos2powerbi.core.ir.models import VisualType
from cognos2powerbi.core.parsers import parse_dashboard
from cognos2powerbi.core.pipeline import run_dashboard_migration

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "sample_dashboard.json"


def test_builds_a_single_page() -> None:
    project = parse_dashboard(EXAMPLE)
    assert len(project.pages) == 1
    assert project.pages[0].display_name == "Overview"


def test_maps_widgets_to_visuals() -> None:
    project = parse_dashboard(EXAMPLE)
    visuals = project.pages[0].visuals
    types = [visual.visual_type for visual in visuals]
    assert VisualType.COLUMN_CHART in types
    assert VisualType.TABLE in types


def test_synthesizes_tables_from_references() -> None:
    project = parse_dashboard(EXAMPLE)
    table_names = {t.name for t in project.tables}
    assert {"Sales", "Product"} <= table_names
    sales = next(t for t in project.tables if t.name == "Sales")
    assert sales.column("Revenue") is not None


def test_category_and_value_roles() -> None:
    project = parse_dashboard(EXAMPLE)
    column_chart = next(
        v for v in project.pages[0].visuals if v.visual_type is VisualType.COLUMN_CHART
    )
    roles = {field.role for field in column_chart.fields}
    assert "category" in roles
    assert "values" in roles


def test_dashboard_migration_writes_report(tmp_path: Path) -> None:
    result = run_dashboard_migration(EXAMPLE, tmp_path, ai="none")
    assert result.source_kind == "dashboard"
    assert result.page_count == 1
