"""Tests for the Cognos data module parser and module migration."""

from __future__ import annotations

from pathlib import Path

from cognos2powerbi.core.ir.models import TableRole
from cognos2powerbi.core.parsers import parse_data_module
from cognos2powerbi.core.pipeline import run_module_migration

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "sample_data_module.json"


def test_parses_query_subjects_as_tables() -> None:
    project = parse_data_module(EXAMPLE)
    table_names = {t.name for t in project.tables}
    assert {"Sales", "Product"} <= table_names


def test_marks_fact_table_and_summarize_by() -> None:
    project = parse_data_module(EXAMPLE)
    sales = next(t for t in project.tables if t.name == "Sales")
    assert sales.role is TableRole.FACT
    revenue = sales.column("Revenue")
    assert revenue is not None
    assert revenue.summarize_by == "sum"
    avg_price = sales.column("Average Price")
    assert avg_price is not None
    assert avg_price.summarize_by == "average"


def test_identifier_columns_are_keys() -> None:
    project = parse_data_module(EXAMPLE)
    product = next(t for t in project.tables if t.name == "Product")
    key = product.column("Product ID")
    assert key is not None
    assert key.is_key is True
    assert key.summarize_by == "none"


def test_calculation_raises_review_flag() -> None:
    project = parse_data_module(EXAMPLE)
    codes = {flag.code for flag in project.review_flags}
    assert "calculation-needs-review" in codes


def test_relationship_oriented_from_many_side() -> None:
    project = parse_data_module(EXAMPLE)
    assert len(project.relationships) == 1
    rel = project.relationships[0]
    assert rel.from_table == "Sales"
    assert rel.from_column == "Product ID"
    assert rel.to_table == "Product"
    assert rel.to_column == "Product ID"


def test_module_migration_writes_model(tmp_path: Path) -> None:
    result = run_module_migration(EXAMPLE, tmp_path, ai="none")
    assert result.source_kind == "module"
    model_tmdl = (
        tmp_path / f"{result.project_name}.SemanticModel" / "definition" / "model.tmdl"
    ).read_text(encoding="utf-8")
    assert "relationship" in model_tmdl
    assert "isKey" not in model_tmdl
