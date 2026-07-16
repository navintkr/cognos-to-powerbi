"""Tests for the PBIP generator and the end-to-end pipeline."""

from __future__ import annotations

import json
import re
from pathlib import Path

from cognos2powerbi.core.pipeline import run_migration

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "sample_report.xml"


def test_generates_pbip_structure(tmp_path: Path) -> None:
    result = run_migration(EXAMPLE, tmp_path, ai="none")
    name = result.project_name

    assert (tmp_path / f"{name}.pbip").is_file()
    assert (tmp_path / f"{name}.SemanticModel" / "definition" / "model.tmdl").is_file()
    assert (tmp_path / f"{name}.SemanticModel" / "definition" / "tables" / "Sales.tmdl").is_file()
    assert (tmp_path / f"{name}.Report" / "report.json").is_file()
    assert (tmp_path / f"{name}.Report" / "definition.pbir").is_file()


def test_pbip_root_is_valid_json(tmp_path: Path) -> None:
    result = run_migration(EXAMPLE, tmp_path, ai="none")
    pbip = json.loads((tmp_path / f"{result.project_name}.pbip").read_text(encoding="utf-8"))
    assert pbip["version"] == "1.0"
    assert pbip["artifacts"][0]["report"]["path"].endswith(".Report")


def test_pbip_schema_matches_power_bi_pattern(tmp_path: Path) -> None:
    # Power BI (June 2026 and later) rejects the .pbip shortcut unless $schema matches this pattern.
    pattern = (
        r"^https://developer\.microsoft\.com/json-schemas/fabric/pbip/pbipProperties/"
        r"1\.[0-9]+\.[0-9]+/schema\.json$"
    )
    result = run_migration(EXAMPLE, tmp_path, ai="none")
    pbip = json.loads((tmp_path / f"{result.project_name}.pbip").read_text(encoding="utf-8"))
    assert re.match(pattern, pbip["$schema"]) is not None


def test_table_tmdl_contains_measure(tmp_path: Path) -> None:
    result = run_migration(EXAMPLE, tmp_path, ai="none")
    tmdl = (
        tmp_path / f"{result.project_name}.SemanticModel" / "definition" / "tables" / "Sales.tmdl"
    ).read_text(encoding="utf-8")
    assert "measure Revenue = SUM(Sales[Revenue])" in tmdl
    assert "column 'Product line'" in tmdl


def test_review_report_written_when_flags_exist(tmp_path: Path) -> None:
    result = run_migration(EXAMPLE, tmp_path, ai="none")
    assert result.review_flag_count > 0
    assert (tmp_path / "MIGRATION_REVIEW.md").is_file()


def test_sql_server_partition_and_parameters(tmp_path: Path) -> None:
    result = run_migration(EXAMPLE, tmp_path, ai="none")
    definition = tmp_path / f"{result.project_name}.SemanticModel" / "definition"
    model_tmdl = (definition / "model.tmdl").read_text(encoding="utf-8")
    assert "expression Server =" in model_tmdl
    assert "expression Database =" in model_tmdl

    table_tmdl = (definition / "tables" / "Sales.tmdl").read_text(encoding="utf-8")
    assert "Sql.Database(Server, Database)" in table_tmdl
    assert 'Item="Sales"' in table_tmdl


def test_none_source_keeps_placeholder_partition(tmp_path: Path) -> None:
    from cognos2powerbi.core.ir.models import DataSource, DataSourceKind

    data_source = DataSource(kind=DataSourceKind.NONE)
    result = run_migration(EXAMPLE, tmp_path, ai="none", data_source=data_source)
    table_tmdl = (
        tmp_path / f"{result.project_name}.SemanticModel" / "definition" / "tables" / "Sales.tmdl"
    ).read_text(encoding="utf-8")
    assert "#table(type table [], {})" in table_tmdl
