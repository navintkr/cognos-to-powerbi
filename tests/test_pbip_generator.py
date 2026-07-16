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
    # PBIR report format: a definition/ folder replaces the legacy single report.json.
    report_def = tmp_path / f"{name}.Report" / "definition"
    assert (report_def / "report.json").is_file()
    assert (report_def / "version.json").is_file()
    assert (report_def / "pages" / "pages.json").is_file()
    assert (tmp_path / f"{name}.Report" / "definition.pbir").is_file()


def test_pbip_root_is_valid_json(tmp_path: Path) -> None:
    result = run_migration(EXAMPLE, tmp_path, ai="none")
    pbip = json.loads((tmp_path / f"{result.project_name}.pbip").read_text(encoding="utf-8"))
    assert pbip["version"] == "1.0"
    assert pbip["artifacts"][0]["report"]["path"].endswith(".Report")


def test_pbir_visual_has_query_projections(tmp_path: Path) -> None:
    from cognos2powerbi.core.generators.pbip_generator import PbipGenerator
    from cognos2powerbi.core.parsers import parse_report

    # Visual emission is opt-in while the exact Power BI Desktop visual format is confirmed.
    project = parse_report(EXAMPLE)
    generator = PbipGenerator()
    generator.emit_visuals = True
    generator.generate(project, tmp_path)
    pages = tmp_path / f"{project.name}.Report" / "definition" / "pages"
    visual_files = list(pages.glob("*/visuals/*/visual.json"))
    assert visual_files, "expected at least one PBIR visual.json"
    visual = json.loads(visual_files[0].read_text(encoding="utf-8"))
    assert visual["visual"]["visualType"]
    query_state = visual["visual"]["query"]["queryState"]
    role = next(iter(query_state.values()))
    projection = role["projections"][0]
    assert "queryRef" in projection
    container = projection["field"].get("Column") or projection["field"].get("Measure")
    assert container is not None
    assert container["Expression"]["SourceRef"]["Entity"]
    assert container["Property"]


def test_pbir_pages_open_without_visuals_by_default(tmp_path: Path) -> None:
    result = run_migration(EXAMPLE, tmp_path, ai="none")
    pages = tmp_path / f"{result.project_name}.Report" / "definition" / "pages"
    page_json = list(pages.glob("*/page.json"))
    assert page_json, "expected at least one PBIR page.json"
    # By default no visual.json files are emitted (report opens with an empty canvas).
    assert not list(pages.glob("*/visuals/*/visual.json"))


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


def test_escape_tmdl_name_quotes_non_identifiers() -> None:
    from cognos2powerbi.core.generators.pbip_generator import _escape_tmdl_name

    # Bare ASCII identifiers stay unquoted.
    assert _escape_tmdl_name("Sales") == "Sales"
    assert _escape_tmdl_name("Order_Year") == "Order_Year"
    # Spaces, leading digits, accented letters, and embedded quotes must be quoted.
    assert _escape_tmdl_name("Contract List") == "'Contract List'"
    assert _escape_tmdl_name("1") == "'1'"
    assert _escape_tmdl_name("Región") == "'Región'"
    assert _escape_tmdl_name("O'Brien") == "'O''Brien'"


def test_partition_name_is_quoted_for_table_with_space(tmp_path: Path) -> None:
    from cognos2powerbi.core.generators.pbip_generator import PbipGenerator
    from cognos2powerbi.core.ir.models import Column, DataType, MigrationProject, Table

    project = MigrationProject(name="SpacedTables")
    table = Table(name="Contract List", source_query="Contract List")
    table.columns.append(Column(name="1", data_type=DataType.STRING, source_column="1"))
    project.tables.append(table)

    out = tmp_path / "out"
    PbipGenerator().generate(project, out)
    tmdl = (
        out / "SpacedTables.SemanticModel" / "definition" / "tables" / "Contract List.tmdl"
    ).read_text(encoding="utf-8")
    assert "partition 'Contract List' = m" in tmdl
    assert "column '1'" in tmdl
    # The unquoted forms that break the TMDL parser must not appear.
    assert "partition Contract List = m" not in tmdl
    assert "\tcolumn 1\n" not in tmdl


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
