"""Tests for the Framework Manager model parser and model migration."""

from __future__ import annotations

from pathlib import Path

from cognos2powerbi.core.parsers import parse_model
from cognos2powerbi.core.pipeline import run_model_migration

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "sample_model.xml"


def test_parses_query_subjects_as_tables() -> None:
    project = parse_model(EXAMPLE)
    table_names = {t.name for t in project.tables}
    assert {"Sales", "Product"} <= table_names


def test_parses_columns_with_data_types() -> None:
    project = parse_model(EXAMPLE)
    sales = next(t for t in project.tables if t.name == "Sales")
    column_names = {c.name for c in sales.columns}
    assert {"Sales ID", "Product ID", "Order year", "Revenue"} <= column_names


def test_parses_relationship_from_expression() -> None:
    project = parse_model(EXAMPLE)
    assert len(project.relationships) == 1
    rel = project.relationships[0]
    assert rel.from_table == "Sales"
    assert rel.from_column == "Product ID"
    assert rel.to_table == "Product"
    assert rel.to_column == "Product ID"


def test_model_migration_writes_relationship(tmp_path: Path) -> None:
    result = run_model_migration(EXAMPLE, tmp_path, ai="none")
    model_tmdl = (
        tmp_path / f"{result.project_name}.SemanticModel" / "definition" / "model.tmdl"
    ).read_text(encoding="utf-8")
    assert "relationship" in model_tmdl
    assert "fromColumn: Sales.'Product ID'" in model_tmdl
    assert "toColumn: Product.'Product ID'" in model_tmdl
