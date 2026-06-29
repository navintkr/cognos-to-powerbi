"""Tests for the Cognos report parser."""

from __future__ import annotations

from pathlib import Path

from cognos2powerbi.core.ir.models import DataType
from cognos2powerbi.core.parsers import parse_report

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "sample_report.xml"


def test_parses_tables_and_columns() -> None:
    project = parse_report(EXAMPLE)
    assert project.name == "sample_report"
    assert len(project.tables) == 1

    table = project.tables[0]
    assert table.name == "Sales"
    column_names = {c.name for c in table.columns}
    assert {"Product line", "Order year"} <= column_names


def test_simple_aggregate_becomes_dax_measure() -> None:
    project = parse_report(EXAMPLE)
    table = project.tables[0]
    revenue = next(m for m in table.measures if m.name == "Revenue")
    assert revenue.dax_expression == "SUM(Sales[Revenue])"


def test_arithmetic_expression_translates_deterministically() -> None:
    project = parse_report(EXAMPLE)
    table = project.tables[0]
    gross = next(m for m in table.measures if m.name == "Gross profit")
    assert gross.dax_expression == "SUM(Sales[Revenue]) - SUM(Sales[Cost])"
    assert gross.needs_review is False


def test_unknown_function_flags_for_review() -> None:
    project = parse_report(EXAMPLE)
    table = project.tables[0]
    ranked = next(m for m in table.measures if m.name == "Revenue rank")
    assert ranked.needs_review is True
    assert any(f.code == "measure-needs-review" for f in project.review_flags)


def test_pages_and_visuals_are_parsed() -> None:
    project = parse_report(EXAMPLE)
    assert len(project.pages) == 1
    page = project.pages[0]
    assert page.display_name == "Sales Overview"
    assert len(page.visuals) == 2


def test_data_type_mapping() -> None:
    assert DataType.from_cognos("integer") == DataType.INT64
    assert DataType.from_cognos("timestamp") == DataType.DATE_TIME
    assert DataType.from_cognos(None) == DataType.STRING
