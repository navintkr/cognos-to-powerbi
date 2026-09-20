"""Structured migration metadata sidecar.

The parser captures business logic that has no single deterministic Power BI target - the report's
query graph, the detail filters with their Cognos ``use`` semantics, and the prompt/parameter
definitions. Rather than lose that information, the generators write it next to the Power BI output
as ``MIGRATION_METADATA.json`` so it can drive later steps (for example generating RDL
``ReportParameters`` or Power BI parameters/slicers) and give reviewers a structured view of the
hidden logic.
"""

from __future__ import annotations

import json
from pathlib import Path

from cognos2powerbi.core.ir.models import MigrationProject

METADATA_FILENAME = "MIGRATION_METADATA.json"


def build_metadata(project: MigrationProject) -> dict:
    """Return the structured migration metadata for a project as a JSON-serializable dict."""
    return {
        "project": project.name,
        "sourcePath": project.source_path,
        "queryGraph": project.query_graph.model_dump(mode="json"),
        "filters": [flt.model_dump(mode="json") for flt in project.filters],
        "prompts": [prompt.model_dump(mode="json") for prompt in project.prompts],
    }


def has_metadata(project: MigrationProject) -> bool:
    """Return True when the project carries any query-graph, filter, or prompt metadata."""
    return bool(
        project.query_graph.nodes
        or project.query_graph.edges
        or project.filters
        or project.prompts
    )


def write_migration_metadata(project: MigrationProject, out_dir: str | Path) -> Path | None:
    """Write ``MIGRATION_METADATA.json`` into ``out_dir`` when the project has metadata.

    Returns the path written, or ``None`` when there is nothing to record.
    """
    if not has_metadata(project):
        return None
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = root / METADATA_FILENAME
    path.write_text(json.dumps(build_metadata(project), indent=2), encoding="utf-8")
    return path
