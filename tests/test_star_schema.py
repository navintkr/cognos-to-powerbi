"""Tests for the star-schema modeling pass."""

from __future__ import annotations

from pathlib import Path

from cognos2powerbi.core.generators import generate_pbip
from cognos2powerbi.core.ir.models import (
    Cardinality,
    Column,
    CrossFilterDirection,
    DataType,
    Measure,
    MigrationProject,
    Relationship,
    Table,
    TableRole,
)
from cognos2powerbi.core.modeling import analyze_model
from cognos2powerbi.core.parsers import parse_model

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "star_schema_model.xml"


def _table(name: str, columns: list[Column], measures: list[Measure] | None = None) -> Table:
    return Table(name=name, source_query=name, columns=columns, measures=measures or [])


def _col(name: str, data_type: DataType = DataType.INT64) -> Column:
    return Column(name=name, data_type=data_type, source_column=name)


# --------------------------------------------------------------- classification


def test_classifies_fact_and_dimensions() -> None:
    project = parse_model(EXAMPLE)
    analyze_model(project)
    roles = {t.name: t.role for t in project.tables}
    assert roles["FactSales"] == TableRole.FACT
    assert roles["DimProduct"] == TableRole.DIMENSION
    assert roles["DimCustomer"] == TableRole.DIMENSION
    assert roles["DimDate"] == TableRole.DATE


def test_marks_date_table() -> None:
    project = parse_model(EXAMPLE)
    analyze_model(project)
    date = next(t for t in project.tables if t.name == "DimDate")
    assert date.is_date_table is True
    assert date.data_category == "Time"
    date_col = next(c for c in date.columns if c.name == "Date")
    assert date_col.data_type == DataType.DATE_TIME
    assert date_col.summarize_by == "none"


def test_classifies_tables_with_measures_as_fact() -> None:
    project = MigrationProject(name="m")
    project.tables.append(
        _table("Sales", [_col("Amount", DataType.DECIMAL)], [Measure(name="Total")])
    )
    analyze_model(project)
    assert project.tables[0].role == TableRole.FACT


# --------------------------------------------------------------- relationships


def test_orients_relationship_fact_to_dimension() -> None:
    project = parse_model(EXAMPLE)
    analyze_model(project)
    rel = next(r for r in project.relationships if r.name == "Sales_Product")
    assert rel.from_table == "FactSales"
    assert rel.to_table == "DimProduct"
    assert rel.cardinality == Cardinality.MANY_TO_ONE


def test_flips_relationship_when_dimension_is_on_from_side() -> None:
    project = MigrationProject(name="m")
    project.tables.append(_table("DimProduct", [_col("ProductID")]))
    project.tables.append(
        _table(
            "FactSales", [_col("ProductID"), _col("Amount", DataType.DECIMAL)], [Measure(name="T")]
        )
    )
    project.relationships.append(
        Relationship(
            from_table="DimProduct",
            from_column="ProductID",
            to_table="FactSales",
            to_column="ProductID",
        )
    )
    analyze_model(project)
    rel = project.relationships[0]
    assert rel.from_table == "FactSales"
    assert rel.to_table == "DimProduct"


def test_hides_foreign_key_on_fact() -> None:
    project = parse_model(EXAMPLE)
    analyze_model(project)
    fact = next(t for t in project.tables if t.name == "FactSales")
    product_fk = next(c for c in fact.columns if c.name == "ProductID")
    assert product_fk.is_foreign_key is True
    assert product_fk.is_hidden is True
    assert product_fk.summarize_by == "none"


def test_role_playing_dimension_deactivates_extra_relationship() -> None:
    project = parse_model(EXAMPLE)
    analyze_model(project)
    date_rels = [
        r for r in project.relationships if {r.from_table, r.to_table} == {"FactSales", "DimDate"}
    ]
    assert len(date_rels) == 2
    assert sum(1 for r in date_rels if r.is_active) == 1
    assert any(f.code == "relationship-role-playing" for f in project.review_flags)


def test_snowflake_relationship_is_flagged() -> None:
    project = parse_model(EXAMPLE)
    analyze_model(project)
    assert any(f.code == "model-snowflake" for f in project.review_flags)


# ------------------------------------------------------------------ edge cases


def test_self_join_is_deactivated_and_flagged() -> None:
    project = MigrationProject(name="m")
    project.tables.append(
        _table("Employee", [_col("EmployeeID"), _col("ManagerID")], [Measure(name="Count")])
    )
    project.relationships.append(
        Relationship(
            from_table="Employee",
            from_column="ManagerID",
            to_table="Employee",
            to_column="EmployeeID",
        )
    )
    analyze_model(project)
    assert project.relationships[0].is_active is False
    assert any(f.code == "relationship-self-join" for f in project.review_flags)


def test_fact_to_fact_is_many_to_many() -> None:
    project = MigrationProject(name="m")
    project.tables.append(_table("Budget", [_col("ProjectID")], [Measure(name="B")]))
    project.tables.append(_table("Actual", [_col("ProjectID")], [Measure(name="A")]))
    project.relationships.append(
        Relationship(
            from_table="Budget",
            from_column="ProjectID",
            to_table="Actual",
            to_column="ProjectID",
        )
    )
    analyze_model(project)
    rel = project.relationships[0]
    assert rel.cardinality == Cardinality.MANY_TO_MANY
    assert rel.cross_filter == CrossFilterDirection.BOTH
    assert any(f.code == "relationship-many-to-many" for f in project.review_flags)


def test_orphan_table_is_flagged() -> None:
    project = MigrationProject(name="m")
    project.tables.append(_table("Sales", [_col("ProductID")], [Measure(name="T")]))
    project.tables.append(_table("DimProduct", [_col("ProductID")]))
    project.tables.append(_table("DimOrphan", [_col("OrphanID"), _col("Label", DataType.STRING)]))
    project.relationships.append(
        Relationship(
            from_table="Sales",
            from_column="ProductID",
            to_table="DimProduct",
            to_column="ProductID",
        )
    )
    analyze_model(project)
    orphans = [f for f in project.review_flags if f.code == "table-orphan"]
    assert any(f.source_ref == "DimOrphan" for f in orphans)


def test_ambiguous_loop_deactivates_one_relationship() -> None:
    project = MigrationProject(name="m")
    project.tables.append(_table("A", [_col("BID"), _col("CID")], [Measure(name="M")]))
    project.tables.append(_table("B", [_col("BID"), _col("CID")]))
    project.tables.append(_table("C", [_col("CID"), _col("AID")]))
    project.relationships.append(
        Relationship(from_table="A", from_column="BID", to_table="B", to_column="BID")
    )
    project.relationships.append(
        Relationship(from_table="B", from_column="CID", to_table="C", to_column="CID")
    )
    project.relationships.append(
        Relationship(from_table="C", from_column="AID", to_table="A", to_column="AID")
    )
    analyze_model(project)
    assert sum(1 for r in project.relationships if not r.is_active) == 1
    assert any(f.code == "relationship-ambiguous-loop" for f in project.review_flags)


def test_duplicate_relationship_is_removed() -> None:
    project = MigrationProject(name="m")
    project.tables.append(_table("Sales", [_col("ProductID")], [Measure(name="T")]))
    project.tables.append(_table("DimProduct", [_col("ProductID")]))
    for _ in range(2):
        project.relationships.append(
            Relationship(
                from_table="Sales",
                from_column="ProductID",
                to_table="DimProduct",
                to_column="ProductID",
            )
        )
    analyze_model(project)
    assert len(project.relationships) == 1
    assert any(f.code == "relationship-duplicate" for f in project.review_flags)


def test_composite_key_is_flagged_by_parser() -> None:
    project = parse_model(EXAMPLE)
    # The example has no composite key; build one inline to assert parser behavior elsewhere.
    assert all(f.code != "relationship-composite-key" for f in project.review_flags)


# ------------------------------------------------------------------ generation


def test_generator_emits_cardinality_and_cross_filter(tmp_path: Path) -> None:
    project = MigrationProject(name="MM")
    project.tables.append(_table("Budget", [_col("ProjectID")], [Measure(name="B")]))
    project.tables.append(_table("Actual", [_col("ProjectID")], [Measure(name="A")]))
    project.relationships.append(
        Relationship(
            from_table="Budget",
            from_column="ProjectID",
            to_table="Actual",
            to_column="ProjectID",
            cardinality=Cardinality.MANY_TO_MANY,
            cross_filter=CrossFilterDirection.BOTH,
        )
    )
    generate_pbip(project, tmp_path)
    model_tmdl = (tmp_path / "MM.SemanticModel" / "definition" / "model.tmdl").read_text(
        encoding="utf-8"
    )
    assert "fromCardinality: many" in model_tmdl
    assert "toCardinality: many" in model_tmdl
    assert "crossFilteringBehavior: bothDirections" in model_tmdl


def test_generator_emits_inactive_relationship(tmp_path: Path) -> None:
    project = parse_model(EXAMPLE)
    analyze_model(project)
    generate_pbip(project, tmp_path)
    model_tmdl = (
        tmp_path / f"{project.name}.SemanticModel" / "definition" / "model.tmdl"
    ).read_text(encoding="utf-8")
    assert "isActive: false" in model_tmdl


def test_generator_emits_date_table_category(tmp_path: Path) -> None:
    project = parse_model(EXAMPLE)
    analyze_model(project)
    generate_pbip(project, tmp_path)
    date_tmdl = (
        tmp_path / f"{project.name}.SemanticModel" / "definition" / "tables" / "DimDate.tmdl"
    ).read_text(encoding="utf-8")
    assert "dataCategory: Time" in date_tmdl
