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
import uuid
from pathlib import Path

from cognos2powerbi.core.ir.models import (
    MigrationProject,
    Table,
    Visual,
)

_COMPATIBILITY_LEVEL = 1567


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
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/pbip/1.0.0/schema.json",
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
                self._render_table_tmdl(table),
            )

    def _render_model_tmdl(self, project: MigrationProject) -> str:
        lines = [
            "model Model",
            "\tculture: en-US",
            "\tdefaultPowerBIDataSourceVersion: powerBI_V3",
            "",
        ]
        for table in project.tables:
            lines.append(f"ref table {table.name}")
        lines.append("")
        return "\n".join(lines)

    def _render_table_tmdl(self, table: Table) -> str:
        lines = [f"table {table.name}", ""]
        for column in table.columns:
            lines.append(f"\tcolumn {_escape_tmdl_name(column.name)}")
            lines.append(f"\t\tdataType: {column.data_type.value}")
            lines.append(f"\t\tsourceColumn: {column.source_column or column.name}")
            if column.is_hidden:
                lines.append("\t\tisHidden")
            lines.append("")
        for measure in table.measures:
            expression = measure.dax_expression or '"TODO: translate Cognos expression"'
            lines.append(f"\tmeasure {_escape_tmdl_name(measure.name)} = {expression}")
            if measure.format_string:
                lines.append(f"\t\tformatString: {measure.format_string}")
            lines.append("")
        lines.append(f"\tpartition {table.name} = m")
        lines.append("\t\tmode: import")
        lines.append("\t\tsource =")
        lines.append("\t\t\tlet")
        lines.append(
            "\t\t\t\tSource = #table(type table [], {})"
            "  // TODO: replace with the Power Query for this Cognos query"
        )
        lines.append("\t\t\tin")
        lines.append("\t\t\t\tSource")
        lines.append("")
        return "\n".join(lines)

    # -------------------------------------------------------------------- Report

    def _write_report(self, report_dir: Path, model_dir: Path, project: MigrationProject) -> None:
        _write_json(report_dir / ".platform", _platform("Report", project.name))
        _write_json(
            report_dir / "definition.pbir",
            {
                "version": "1.0",
                "datasetReference": {"byPath": {"path": f"../{model_dir.name}"}},
            },
        )
        _write_json(report_dir / "report.json", self._render_report_json(project))

    def _render_report_json(self, project: MigrationProject) -> dict:
        sections = []
        for index, page in enumerate(project.pages):
            visual_containers = [
                self._render_visual_container(visual, position)
                for position, visual in enumerate(page.visuals)
            ]
            sections.append(
                {
                    "name": page.name,
                    "displayName": page.display_name,
                    "ordinal": index,
                    "width": 1280,
                    "height": 720,
                    "visualContainers": visual_containers,
                }
            )
        return {
            "version": "1.0",
            "themeCollection": {"baseTheme": {"name": "CY24SU10"}},
            "sections": sections,
            "config": json.dumps({"version": "5.43"}),
        }

    def _render_visual_container(self, visual: Visual, position: int) -> dict:
        projections: dict[str, list[dict]] = {}
        for field in visual.fields:
            projections.setdefault(field.role, []).append(
                {"queryRef": f"{field.table}.{field.name}"}
            )
        single_visual = {
            "visualType": visual.visual_type.value,
            "projections": projections,
            "drillFilterOtherVisuals": True,
        }
        return {
            "x": 16 + (position % 2) * 632,
            "y": 16 + (position // 2) * 360,
            "width": visual.width,
            "height": visual.height,
            "config": json.dumps({"singleVisual": single_visual}),
        }

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
    """Quote a TMDL object name when it contains spaces or special characters."""
    if name and all(ch.isalnum() or ch == "_" for ch in name):
        return name
    return f"'{name}'"


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def generate_pbip(project: MigrationProject, out_dir: str | Path) -> Path:
    """Convenience wrapper to render a migration project to PBIP files."""
    return PbipGenerator().generate(project, out_dir)
