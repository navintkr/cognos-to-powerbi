"""Tests for the RDL (Report Builder paginated report) generator and pipeline path."""

from __future__ import annotations

from pathlib import Path

from lxml import etree

from cognos2powerbi.core.generators import generate_rdl
from cognos2powerbi.core.ir.models import (
    Column,
    DataType,
    MigrationProject,
    ReportPage,
    Style,
    Table,
    TextBlock,
    Visual,
    VisualField,
    VisualType,
)
from cognos2powerbi.core.pipeline import run_migration

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "calculated_report.xml"

_RDL_NS = "http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition"


def _ns(tag: str) -> str:
    return f"{{{_RDL_NS}}}{tag}"


def _project() -> MigrationProject:
    table = Table(
        name="Random",
        columns=[
            Column(name="Purchase Date", data_type=DataType.DATE_TIME),
            Column(name="Account Number", data_type=DataType.STRING),
            Column(name="Amount", data_type=DataType.DECIMAL),
        ],
    )
    page = ReportPage(
        name="Page1",
        display_name="Page1",
        header_blocks=[TextBlock(text="Buen dia,")],
        footer_blocks=[TextBlock(text="Cordialmente,"), TextBlock(text="GM FINANCIAL")],
        visuals=[
            Visual(
                visual_type=VisualType.TABLE,
                fields=[
                    VisualField(table="Random", name="Purchase Date", role="Values"),
                    VisualField(table="Random", name="Account Number", role="Values"),
                    VisualField(table="Random", name="Amount", role="Values"),
                ],
            )
        ],
    )
    return MigrationProject(name="QC Report", tables=[table], pages=[page])


def test_rdl_is_well_formed(tmp_path: Path) -> None:
    out = generate_rdl(_project(), tmp_path)
    assert out.suffix == ".rdl"
    tree = etree.parse(str(out))
    assert tree.getroot().tag == _ns("Report")


def test_rdl_dataset_fields_match_columns_in_order(tmp_path: Path) -> None:
    out = generate_rdl(_project(), tmp_path)
    tree = etree.parse(str(out))
    fields = tree.findall(f".//{_ns('DataSet')}/{_ns('Fields')}/{_ns('Field')}")
    names = [f.get("Name") for f in fields]
    assert names == ["PurchaseDate", "AccountNumber", "Amount"]
    type_names = [
        f.findtext(".//{http://schemas.microsoft.com/SQLServer/reporting/reportdesigner}TypeName")
        for f in fields
    ]
    assert type_names == ["System.DateTime", "System.String", "System.Decimal"]


def test_rdl_tablix_binds_fields_and_headers(tmp_path: Path) -> None:
    out = generate_rdl(_project(), tmp_path)
    text = out.read_text(encoding="utf-8")
    # Header row shows display names; data row binds =Fields!<name>.Value in order.
    for display in ("Purchase Date", "Account Number", "Amount"):
        assert f"<Value>{display}</Value>" in text
    for field in ("PurchaseDate", "AccountNumber", "Amount"):
        assert f"=Fields!{field}.Value" in text


def test_rdl_includes_letterhead_text(tmp_path: Path) -> None:
    out = generate_rdl(_project(), tmp_path)
    text = out.read_text(encoding="utf-8")
    assert "Buen dia," in text
    assert "Cordialmente," in text
    assert "GM FINANCIAL" in text


def test_rdl_header_row_is_taller_than_data_row(tmp_path: Path) -> None:
    # The Tablix header row must be taller so wrapped two-word titles are not clipped.
    out = generate_rdl(_project(), tmp_path)
    tree = etree.parse(str(out))
    rows = tree.findall(f".//{_ns('Tablix')}//{_ns('TablixRow')}")
    assert len(rows) == 2
    header_height = rows[0].findtext(_ns("Height"))
    data_height = rows[1].findtext(_ns("Height"))
    assert header_height == "0.35in"
    assert data_height == "0.25in"


def test_rdl_columns_are_auto_sized_to_content(tmp_path: Path) -> None:
    # A long-named column must be wider than a short-named one, and all columns must fit the page.
    project = MigrationProject(
        name="Widths",
        tables=[
            Table(
                name="T",
                columns=[
                    Column(name="ID", data_type=DataType.STRING),
                    Column(name="Contract Purchaser Identifier", data_type=DataType.STRING),
                ],
            )
        ],
        pages=[
            ReportPage(
                name="P",
                display_name="P",
                visuals=[
                    Visual(
                        visual_type=VisualType.TABLE,
                        fields=[
                            VisualField(table="T", name="ID", role="Values"),
                            VisualField(
                                table="T", name="Contract Purchaser Identifier", role="Values"
                            ),
                        ],
                    )
                ],
            )
        ],
    )
    out = generate_rdl(project, tmp_path)
    tree = etree.parse(str(out))
    widths = [
        float(w.text.replace("in", ""))
        for w in tree.findall(f".//{_ns('TablixColumns')}/{_ns('TablixColumn')}/{_ns('Width')}")
    ]
    assert len(widths) == 2
    assert widths[1] > widths[0]
    assert sum(widths) <= 7.5 + 0.01


def test_pipeline_rdl_format_writes_rdl(tmp_path: Path) -> None:
    result = run_migration(EXAMPLE, tmp_path, ai="none", output_format="rdl")
    assert result.pbip_path.endswith(".rdl")
    assert Path(result.pbip_path).is_file()
    etree.parse(result.pbip_path)


def test_rdl_applies_extracted_styles(tmp_path: Path) -> None:
    # A styled letterhead block and a right-aligned data cell must carry through to the RDL.
    project = _project()
    page = project.pages[0]
    page.header_blocks = [
        TextBlock(text="Buen dia,", style=Style(font_family="Times New Roman", font_size_pt=14.0))
    ]
    page.visuals[0].fields[0].cell_style = Style(text_align="Right")
    out = generate_rdl(project, tmp_path)
    text = out.read_text(encoding="utf-8")
    assert "<FontFamily>Times New Roman</FontFamily>" in text
    assert "<FontSize>14pt</FontSize>" in text
    assert "<TextAlign>Right</TextAlign>" in text
