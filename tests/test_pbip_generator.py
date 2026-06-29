"""Tests for the PBIP generator and the end-to-end pipeline."""

from __future__ import annotations

import json
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
