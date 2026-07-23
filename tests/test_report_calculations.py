"""Tests for report fidelity: type inference, calculated columns, joins, and honest flags."""

from __future__ import annotations

from pathlib import Path

from cognos2powerbi.core.ir.models import Cardinality, DataType
from cognos2powerbi.core.parsers import parse_report
from cognos2powerbi.core.pipeline import run_migration

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "calculated_report.xml"


def _table(project, name):
    return next(t for t in project.tables if t.name == name)


def test_infers_datetime_from_cast_and_rs_datatype() -> None:
    project = parse_report(EXAMPLE)
    orders = _table(project, "Orders")
    assert orders.column("Order Date").data_type is DataType.DATE_TIME
    assert orders.column("Order ID").data_type is DataType.STRING


def test_confident_calculation_becomes_dax_column() -> None:
    project = parse_report(EXAMPLE)
    code = _table(project, "Orders").column("Customer Code")
    assert code.is_calculated is True
    assert code.dax_expression is not None
    assert "UPPER(" in code.dax_expression
    assert code.source_column is None


def test_unmappable_calculation_stays_physical_and_flagged() -> None:
    project = parse_report(EXAMPLE)
    row_number = _table(project, "Orders").column("Row Number")
    # Kept loadable as a physical column, not emitted as invalid DAX.
    assert row_number.is_calculated is False
    assert row_number.dax_expression is None
    assert row_number.needs_calculation is True
    codes = {flag.code for flag in project.review_flags}
    assert "calculation-needs-review" in codes


def test_aggregated_item_becomes_measure() -> None:
    project = parse_report(EXAMPLE)
    orders = _table(project, "Orders")
    assert any(m.name == "Revenue" for m in orders.measures)


def test_join_becomes_relationship_from_many_side() -> None:
    project = parse_report(EXAMPLE)
    assert len(project.relationships) == 1
    rel = project.relationships[0]
    assert rel.from_table == "Orders"
    assert rel.to_table == "Customers"
    assert rel.from_column == "Customer Code"
    assert rel.cardinality is Cardinality.MANY_TO_ONE


def test_honest_flags_for_filters_and_package_source() -> None:
    project = parse_report(EXAMPLE)
    codes = {flag.code for flag in project.review_flags}
    assert "detail-filter" in codes
    assert "package-source" in codes


def test_list_visual_binds_exact_columns_in_order() -> None:
    project = parse_report(EXAMPLE)
    page = project.pages[0]
    visual = page.visuals[0]
    # The list declares only Order Date then Customer Code; the visual must match that selection
    # and order, not bind every column of the query.
    names = [field.name for field in visual.fields]
    assert names == ["Order Date", "Customer Code"]


def test_calculated_column_renders_in_tmdl(tmp_path: Path) -> None:
    result = run_migration(EXAMPLE, tmp_path, ai="none", infer_model=False)
    tmdl = (
        tmp_path / f"{result.project_name}.SemanticModel" / "definition" / "tables" / "Orders.tmdl"
    ).read_text(encoding="utf-8")
    assert "column 'Customer Code' = UPPER(" in tmdl
    # The unmappable running-count stays a physical column (no invalid DAX in the model).
    assert "column 'Row Number'\n" in tmdl
    assert "running-count" not in tmdl
