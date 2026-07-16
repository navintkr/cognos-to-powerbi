"""Generate a Power BI Project (PBIP) from a :class:`MigrationProject`.

The generator writes the modern, Git-friendly PBIP layout:

    <Name>.pbip
    <Name>.SemanticModel/
        .platform
        definition.pbism
        definition/
            database.tmdl
            model.tmdl
            tables/<Table>.tmdl
    <Name>.Report/
        .platform
        definition.pbir
        report.json

TMDL (Tabular Model Definition Language) describes the semantic model; PBIR describes the
report. The output is a deterministic starting point. Visual fidelity and complex expressions
are best-effort and are refined by the optional AI stage; unmapped items are listed in
review_flags and surfaced to the user.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from cognos2powerbi.core.ir.models import (
    Cardinality,
    CrossFilterDirection,
    DataSource,
    DataSourceKind,
    MigrationProject,
    Relationship,
    ReportPage,
    Table,
    Visual,
    VisualField,
    VisualType,
)

_COMPATIBILITY_LEVEL = 1567

# An unquoted TMDL identifier: ASCII letter or underscore, then ASCII letters, digits, underscores.
_TMDL_BARE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# PBIR (enhanced report format) JSON schema URLs. Current Power BI Desktop renders PBIR; the legacy
# single-file report.json is retired and fails to render in recent builds.
_PBIR_DEFINITION_PROPERTIES_SCHEMA = (
    "https://developer.microsoft.com/json-schemas/fabric/item/report/"
    "definitionProperties/2.0.0/schema.json"
)
_PBIR_VERSION_SCHEMA = (
    "https://developer.microsoft.com/json-schemas/fabric/item/report/"
    "definition/versionMetadata/1.0.0/schema.json"
)
_PBIR_REPORT_SCHEMA = (
    "https://developer.microsoft.com/json-schemas/fabric/item/report/"
    "definition/report/1.0.0/schema.json"
)
_PBIR_PAGES_SCHEMA = (
    "https://developer.microsoft.com/json-schemas/fabric/item/report/"
    "definition/pagesMetadata/1.0.0/schema.json"
)
_PBIR_PAGE_SCHEMA = (
    "https://developer.microsoft.com/json-schemas/fabric/item/report/"
    "definition/page/1.0.0/schema.json"
)
_PBIR_VISUAL_SCHEMA = (
    "https://developer.microsoft.com/json-schemas/fabric/item/report/"
    "definition/visualContainer/1.0.0/schema.json"
)
# A built-in (SharedResources) base theme shipped with Power BI.
_BASE_THEME_NAME = "CY24SU10"
_BASE_THEME_VERSION = "5.55"

_CHART_VISUAL_TYPES = {
    VisualType.COLUMN_CHART,
    VisualType.BAR_CHART,
    VisualType.LINE_CHART,
    VisualType.PIE_CHART,
}


class PbipGenerator:
    """Render a migration project to PBIP files on disk."""

    def generate(self, project: MigrationProject, out_dir: str | Path) -> Path:
        root = Path(out_dir)
        name = project.name
        model_dir = root / f"{name}.SemanticModel"
        report_dir = root / f"{name}.Report"
        (model_dir / "definition" / "tables").mkdir(parents=True, exist_ok=True)
        report_dir.mkdir(parents=True, exist_ok=True)

        self._write_pbip_root(root, name)
        self._write_semantic_model(model_dir, project)
        self._write_report(report_dir, model_dir, project)
        self._write_review_report(root, project)
        return root / f"{name}.pbip"

    # ------------------------------------------------------------------ PBIP root

    def _write_pbip_root(self, root: Path, name: str) -> None:
        pbip = {
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json",
            "version": "1.0",
            "artifacts": [{"report": {"path": f"{name}.Report"}}],
            "settings": {"enableAutoRecovery": True},
        }
        _write_json(root / f"{name}.pbip", pbip)

    # ------------------------------------------------------------ Semantic model

    def _write_semantic_model(self, model_dir: Path, project: MigrationProject) -> None:
        _write_json(
            model_dir / ".platform",
            _platform("SemanticModel", project.name),
        )
        _write_json(model_dir / "definition.pbism", {"version": "4.0", "settings": {}})

        definition = model_dir / "definition"
        _write_text(
            definition / "database.tmdl",
            f"database\n\tcompatibilityLevel: {_COMPATIBILITY_LEVEL}\n",
        )
        _write_text(definition / "model.tmdl", self._render_model_tmdl(project))

        for table in project.tables:
            _write_text(
                definition / "tables" / f"{table.name}.tmdl",
                self._render_table_tmdl(table, project.data_source),
            )

    def _render_model_tmdl(self, project: MigrationProject) -> str:
        lines = [
            "model Model",
            "\tculture: en-US",
            "\tdefaultPowerBIDataSourceVersion: powerBI_V3",
            "",
        ]
        source = project.data_source
        if source.kind == DataSourceKind.SQL_SERVER:
            lines.append(
                f'expression Server = "{source.server}" meta '
                '[IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]'
            )
            lines.append(
                f'expression Database = "{source.database}" meta '
                '[IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]'
            )
            lines.append("")
        for table in project.tables:
            lines.append(f"ref table {_escape_tmdl_name(table.name)}")
        lines.append("")
        for relationship in project.relationships:
            lines.extend(self._render_relationship_tmdl(relationship))
        return "\n".join(lines)

    def _render_relationship_tmdl(self, relationship: Relationship) -> list[str]:
        from_ref = (
            f"{_escape_tmdl_name(relationship.from_table)}."
            f"{_escape_tmdl_name(relationship.from_column)}"
        )
        to_ref = (
            f"{_escape_tmdl_name(relationship.to_table)}."
            f"{_escape_tmdl_name(relationship.to_column)}"
        )
        lines = [f"relationship {uuid.uuid4()}"]
        if not relationship.is_active:
            lines.append("\tisActive: false")
        lines.append(f"\tfromColumn: {from_ref}")
        lines.append(f"\ttoColumn: {to_ref}")
        # many-to-one is the Power BI default and needs no explicit cardinality tokens.
        if relationship.cardinality == Cardinality.MANY_TO_MANY:
            lines.append("\tfromCardinality: many")
            lines.append("\ttoCardinality: many")
        elif relationship.cardinality == Cardinality.ONE_TO_ONE:
            lines.append("\tfromCardinality: one")
            lines.append("\ttoCardinality: one")
        elif relationship.cardinality == Cardinality.ONE_TO_MANY:
            lines.append("\tfromCardinality: one")
            lines.append("\ttoCardinality: many")
        if relationship.cross_filter == CrossFilterDirection.BOTH:
            lines.append("\tcrossFilteringBehavior: bothDirections")
        lines.append("")
        return lines

    def _render_table_tmdl(self, table: Table, data_source: DataSource) -> str:
        lines = [f"table {_escape_tmdl_name(table.name)}"]
        if table.data_category:
            lines.append(f"\tdataCategory: {table.data_category}")
        lines.append("")
        for column in table.columns:
            if column.is_calculated and column.dax_expression:
                dax = _dax_single_line(column.dax_expression)
                lines.append(f"\tcolumn {_escape_tmdl_name(column.name)} = {dax}")
                lines.append(f"\t\tdataType: {column.data_type.value}")
                if column.is_hidden:
                    lines.append("\t\tisHidden")
                if column.summarize_by:
                    lines.append(f"\t\tsummarizeBy: {column.summarize_by}")
                if column.data_category:
                    lines.append(f"\t\tdataCategory: {column.data_category}")
                lines.append("")
                continue
            lines.append(f"\tcolumn {_escape_tmdl_name(column.name)}")
            lines.append(f"\t\tdataType: {column.data_type.value}")
            lines.append(f"\t\tsourceColumn: {column.source_column or column.name}")
            if column.is_hidden:
                lines.append("\t\tisHidden")
            if column.summarize_by:
                lines.append(f"\t\tsummarizeBy: {column.summarize_by}")
            if column.data_category:
                lines.append(f"\t\tdataCategory: {column.data_category}")
            lines.append("")
        for measure in table.measures:
            expression = (
                _dax_single_line(measure.dax_expression)
                if measure.dax_expression
                else '"TODO: translate Cognos expression"'
            )
            lines.append(f"\tmeasure {_escape_tmdl_name(measure.name)} = {expression}")
            if measure.format_string:
                lines.append(f"\t\tformatString: {measure.format_string}")
            lines.append("")
        lines.append(f"\tpartition {_escape_tmdl_name(table.name)} = m")
        lines.append("\t\tmode: import")
        lines.append("\t\tsource =")
        lines.extend(self._render_partition_source(table, data_source))
        lines.append("")
        return "\n".join(lines)

    def _render_partition_source(self, table: Table, data_source: DataSource) -> list[str]:
        if data_source.kind == DataSourceKind.SQL_SERVER:
            item = table.source_query or table.name
            return [
                "\t\t\tlet",
                "\t\t\t\tSource = Sql.Database(Server, Database),",
                f'\t\t\t\tNavigation = Source{{[Schema="{data_source.schema_name}", '
                f'Item="{item}"]}}[Data]',
                "\t\t\tin",
                "\t\t\t\tNavigation",
            ]
        return [
            "\t\t\tlet",
            "\t\t\t\tSource = #table(type table [], {})"
            "  // TODO: replace with the Power Query for this Cognos query",
            "\t\t\tin",
            "\t\t\t\tSource",
        ]

    # -------------------------------------------------------------------- Report

    def _write_report(self, report_dir: Path, model_dir: Path, project: MigrationProject) -> None:
        """Write the report as PBIR (the modern ``definition/`` folder), not legacy report.json.

        Power BI Desktop (2026) renders the PBIR format; the legacy single-file report.json is
        being retired and fails to render in current builds.
        """
        _write_json(report_dir / ".platform", _platform("Report", project.name))
        _write_json(
            report_dir / "definition.pbir",
            {
                "$schema": _PBIR_DEFINITION_PROPERTIES_SCHEMA,
                "version": "4.0",
                "datasetReference": {"byPath": {"path": f"../{model_dir.name}"}},
            },
        )
        definition = report_dir / "definition"
        _write_json(
            definition / "version.json",
            {"$schema": _PBIR_VERSION_SCHEMA, "version": "4.0.0"},
        )
        _write_json(
            definition / "report.json",
            {
                "$schema": _PBIR_REPORT_SCHEMA,
                "themeCollection": {
                    "baseTheme": {
                        "name": _BASE_THEME_NAME,
                        "reportVersionAtImport": _BASE_THEME_VERSION,
                        "type": "SharedResources",
                    }
                },
                "layoutOptimization": "None",
            },
        )
        self._write_pages(definition / "pages", project)

    def _write_pages(self, pages_dir: Path, project: MigrationProject) -> None:
        used: set[str] = set()
        page_names: list[str] = []
        for index, page in enumerate(project.pages, start=1):
            base = page.name or page.display_name or f"Page{index}"
            page_name = _safe_report_name(base, used, f"Page{index}")
            page_names.append(page_name)
            self._write_page(pages_dir / page_name, page_name, page, project)
        _write_json(
            pages_dir / "pages.json",
            {
                "$schema": _PBIR_PAGES_SCHEMA,
                "pageOrder": page_names,
                "activePageName": page_names[0] if page_names else "",
            },
        )

    def _write_page(
        self, page_dir: Path, page_name: str, page: ReportPage, project: MigrationProject
    ) -> None:
        _write_json(
            page_dir / "page.json",
            {
                "$schema": _PBIR_PAGE_SCHEMA,
                "name": page_name,
                "displayName": page.display_name or page_name,
                "displayOption": "FitToPage",
                "height": 720,
                "width": 1280,
            },
        )
        used: set[str] = set()
        for index, visual in enumerate(page.visuals, start=1):
            visual_name = _safe_report_name(
                f"{visual.visual_type.value}{index}", used, f"visual{index}"
            )
            self._write_visual(page_dir / "visuals" / visual_name, visual_name, visual, project)

    def _write_visual(
        self, visual_dir: Path, visual_name: str, visual: Visual, project: MigrationProject
    ) -> None:
        visual_config: dict[str, object] = {"visualType": visual.visual_type.value}
        query_state = self._build_query_state(visual, project)
        if query_state:
            visual_config["query"] = {"queryState": query_state}
        _write_json(
            visual_dir / "visual.json",
            {
                "$schema": _PBIR_VISUAL_SCHEMA,
                "name": visual_name,
                "position": {
                    "x": visual.x,
                    "y": visual.y,
                    "z": 0,
                    "width": visual.width,
                    "height": visual.height,
                    "tabOrder": 0,
                },
                "visual": visual_config,
            },
        )

    def _build_query_state(self, visual: Visual, project: MigrationProject) -> dict:
        role_projections: dict[str, list[dict]] = {}
        for field in visual.fields:
            role = _pbir_role(visual.visual_type, field.role)
            role_projections.setdefault(role, []).append(
                {
                    "field": self._field_expression(field, project),
                    "queryRef": f"{field.table}.{field.name}",
                    "nativeQueryRef": field.name,
                }
            )
        return {
            role: {"projections": projections} for role, projections in role_projections.items()
        }

    def _field_expression(self, field: VisualField, project: MigrationProject) -> dict:
        table = next((t for t in project.tables if t.name == field.table), None)
        is_measure = bool(table and any(m.name == field.name for m in table.measures))
        inner = {"Expression": {"SourceRef": {"Entity": field.table}}, "Property": field.name}
        return {"Measure": inner} if is_measure else {"Column": inner}

    # -------------------------------------------------------------- Review report

    def _write_review_report(self, root: Path, project: MigrationProject) -> None:
        if not project.review_flags:
            return
        lines = [
            f"# Migration review: {project.name}",
            "",
            "The following items were converted with reduced fidelity or could not be mapped",
            "deterministically. Review them in Power BI Desktop or run the AI refinement stage.",
            "",
            "| Severity | Code | Message | Source |",
            "| --- | --- | --- | --- |",
        ]
        for flag in project.review_flags:
            source = (flag.source_ref or "").replace("|", "\\|")
            message = flag.message.replace("|", "\\|")
            lines.append(f"| {flag.severity.value} | {flag.code} | {message} | {source} |")
        lines.append("")
        _write_text(root / "MIGRATION_REVIEW.md", "\n".join(lines))


# ----------------------------------------------------------------------- helpers


def _platform(item_type: str, display_name: str) -> dict:
    return {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
        "metadata": {"type": item_type, "displayName": display_name},
        "config": {"version": "2.0", "logicalId": str(uuid.uuid4())},
    }


def _escape_tmdl_name(name: str) -> str:
    """Quote a TMDL object name unless it is a bare identifier.

    An unquoted TMDL identifier must start with an ASCII letter or underscore and contain only
    ASCII letters, digits, and underscores. Anything else (spaces, punctuation, accented letters,
    or a leading digit such as a column literally named "1") must be single-quoted, and any single
    quote inside the name is doubled.
    """
    if name and _TMDL_BARE_IDENTIFIER.match(name):
        return name
    return "'" + name.replace("'", "''") + "'"


def _dax_single_line(expression: str) -> str:
    """Collapse a DAX expression to a single line.

    TMDL renders an inline ``column X = <expr>`` / ``measure X = <expr>`` on one line. A multi-line
    expression (for example from an AI provider) would break TMDL indentation, so newlines and runs
    of whitespace are collapsed to single spaces. ``//`` and ``/* */`` comments are removed first so
    collapsing does not comment out the rest. DAX is whitespace-insensitive between tokens, so this
    preserves the semantics.
    """
    without_line_comments = re.sub(r"//[^\n]*", " ", expression)
    without_block_comments = re.sub(r"/\*.*?\*/", " ", without_line_comments, flags=re.DOTALL)
    return re.sub(r"\s+", " ", without_block_comments).strip()


def _safe_report_name(base: str, used: set[str], fallback: str) -> str:
    """Return a unique PBIR object name (word characters or hyphens, max 50 chars)."""
    cleaned = re.sub(r"[^0-9A-Za-z_-]+", "", base)[:50] or fallback
    candidate = cleaned
    suffix = 2
    while candidate in used:
        candidate = f"{cleaned}{suffix}"[:50]
        suffix += 1
    used.add(candidate)
    return candidate


def _pbir_role(visual_type: VisualType, role: str) -> str:
    """Map a generic field role onto the PBIR data role for the given visual type."""
    key = (role or "").strip().lower()
    if visual_type == VisualType.MATRIX:
        return {
            "category": "Rows",
            "rows": "Rows",
            "series": "Columns",
            "columns": "Columns",
        }.get(key, "Values")
    if visual_type in _CHART_VISUAL_TYPES:
        return {"category": "Category", "series": "Series", "values": "Y", "y": "Y"}.get(key, "Y")
    return "Values"


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def generate_pbip(project: MigrationProject, out_dir: str | Path) -> Path:
    """Convenience wrapper to render a migration project to PBIP files."""
    return PbipGenerator().generate(project, out_dir)
