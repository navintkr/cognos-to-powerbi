"""Tests for the query-graph, filter, and prompt extraction enhancements."""

from __future__ import annotations

import json
from pathlib import Path

from lxml import etree

from cognos2powerbi.core.generators import build_metadata, generate_pbip, generate_rdl
from cognos2powerbi.core.generators.metadata import METADATA_FILENAME
from cognos2powerbi.core.ir.models import (
    FilterUse,
    PromptControlType,
    QueryEdgeKind,
    QueryRole,
)
from cognos2powerbi.core.parsers import parse_report

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "prompted_report.xml"

_RDL_NS = "http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition"


def _ns(tag: str) -> str:
    return f"{{{_RDL_NS}}}{tag}"


# --------------------------------------------------------------------- query graph


def test_query_graph_classifies_roles() -> None:
    project = parse_report(EXAMPLE)
    roles = {node.name: node.role for node in project.query_graph.nodes}
    assert roles["AllOrders"] == QueryRole.UNION
    assert roles["SalesOutput"] == QueryRole.JOIN
    assert roles["OrdersA"] == QueryRole.DETAIL
    assert roles["OrdersB"] == QueryRole.DETAIL
    # Customer is referenced only by the join and a prompt page, not a report page, so it is a
    # detail query rather than an output query.
    assert roles["Customer"] == QueryRole.DETAIL

    output = {node.name for node in project.query_graph.nodes if node.is_output}
    assert output == {"SalesOutput"}


def test_query_graph_union_edges() -> None:
    project = parse_report(EXAMPLE)
    union_edges = {
        edge.to_query
        for edge in project.query_graph.edges
        if edge.from_query == "AllOrders" and edge.kind == QueryEdgeKind.UNION
    }
    assert union_edges == {"OrdersA", "OrdersB"}


def test_query_graph_join_edges_carry_condition() -> None:
    project = parse_report(EXAMPLE)
    join_edges = [
        edge
        for edge in project.query_graph.edges
        if edge.from_query == "SalesOutput" and edge.kind == QueryEdgeKind.JOIN
    ]
    assert {edge.to_query for edge in join_edges} == {"AllOrders", "Customer"}
    assert all(edge.condition and "CustomerKey" in edge.condition for edge in join_edges)


# ------------------------------------------------------------------------- filters


def test_detail_filters_capture_use_semantics() -> None:
    project = parse_report(EXAMPLE)
    by_expr = {flt.expression: flt for flt in project.filters}
    mandatory = next(f for f in project.filters if f.use == FilterUse.REQUIRED)
    assert mandatory.query == "SalesOutput"
    assert any(f.use == FilterUse.OPTIONAL for f in project.filters)
    assert any(f.use == FilterUse.PROHIBITED for f in project.filters)
    # The optional date filter references both range prompt parameters.
    date_filter = next(f for f in project.filters if "between" in f.expression)
    assert date_filter.parameters == ["p_From_Date", "p_To_Date"]
    assert by_expr["[Customer].[Region] in (?p_Region?)"].parameters == ["p_Region"]


def test_detail_filter_flags_distinguish_use() -> None:
    project = parse_report(EXAMPLE)
    codes = {flag.code for flag in project.review_flags}
    assert "detail-filter" in codes
    assert "detail-filter-optional" in codes
    assert "detail-filter-prohibited" in codes


# ------------------------------------------------------------------------- prompts


def test_prompts_extracted_with_metadata() -> None:
    project = parse_report(EXAMPLE)
    prompts = {p.parameter_name: p for p in project.prompts}
    assert set(prompts) == {"p_From_Date", "p_To_Date", "p_Region"}

    from_date = prompts["p_From_Date"]
    assert from_date.control_type == PromptControlType.DATE
    assert from_date.range_prompt is True
    assert from_date.required is True
    assert from_date.source_query == "SalesOutput"

    region = prompts["p_Region"]
    assert region.control_type == PromptControlType.SELECT_VALUE
    assert region.multi_select is True
    assert region.required is False
    assert region.values_query == "Customer"
    assert region.value_column == "Region"
    assert region.default_values == ["East"]


def test_prompt_review_flag_present() -> None:
    project = parse_report(EXAMPLE)
    assert any(flag.code == "prompt-parameters" for flag in project.review_flags)


# ------------------------------------------------------------------ metadata sidecar


def test_metadata_written_for_pbip(tmp_path: Path) -> None:
    project = parse_report(EXAMPLE)
    generate_pbip(project, tmp_path)
    metadata_path = tmp_path / METADATA_FILENAME
    assert metadata_path.is_file()
    data = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert data["project"] == project.name
    assert len(data["queryGraph"]["nodes"]) == 5
    assert len(data["filters"]) == 4
    assert len(data["prompts"]) == 3


def test_build_metadata_serializes_enums() -> None:
    project = parse_report(EXAMPLE)
    data = build_metadata(project)
    node_roles = {node["role"] for node in data["queryGraph"]["nodes"]}
    assert "union" in node_roles and "join" in node_roles
    assert {flt["use"] for flt in data["filters"]} >= {"required", "optional", "prohibited"}


# --------------------------------------------------------------------- RDL parameters


def test_rdl_emits_report_parameters(tmp_path: Path) -> None:
    project = parse_report(EXAMPLE)
    rdl_path = generate_rdl(project, tmp_path)
    tree = etree.parse(str(rdl_path))
    root = tree.getroot()

    params = root.find(_ns("ReportParameters"))
    assert params is not None
    names = {p.get("Name") for p in params.findall(_ns("ReportParameter"))}
    assert names == {"p_From_Date", "p_To_Date", "p_Region"}

    region = next(p for p in params.findall(_ns("ReportParameter")) if p.get("Name") == "p_Region")
    assert region.find(_ns("DataType")).text == "String"
    assert region.find(_ns("MultiValue")).text == "true"
    assert region.find(_ns("Nullable")).text == "true"
    default = region.find(_ns("DefaultValue")).find(_ns("Values")).find(_ns("Value"))
    assert default.text == "East"

    from_date = next(
        p for p in params.findall(_ns("ReportParameter")) if p.get("Name") == "p_From_Date"
    )
    assert from_date.find(_ns("DataType")).text == "DateTime"
    assert from_date.find(_ns("Nullable")).text == "false"


def test_rdl_metadata_sidecar_written(tmp_path: Path) -> None:
    project = parse_report(EXAMPLE)
    generate_rdl(project, tmp_path)
    assert (tmp_path / METADATA_FILENAME).is_file()
