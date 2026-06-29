"""End-to-end migration pipeline: parse, refine with AI, generate PBIP."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from cognos2powerbi.core.ai import AiProvider, AiRequest, get_provider
from cognos2powerbi.core.generators import generate_pbip
from cognos2powerbi.core.ir.models import MigrationProject, Severity
from cognos2powerbi.core.parsers import parse_report


class MigrationResult(BaseModel):
    """Summary of a completed migration."""

    project_name: str
    pbip_path: str
    table_count: int
    page_count: int
    measure_count: int
    review_flag_count: int
    ai_provider: str
    ai_refinements: int


def _refine_with_ai(project: MigrationProject, provider: AiProvider) -> int:
    """Translate Cognos measure expressions to DAX using the AI provider.

    Returns the number of measures successfully refined. Failures leave the deterministic
    output untouched and keep the existing review flags.
    """
    if not provider.is_available():
        project.add_flag(
            "ai-unavailable",
            f"AI provider '{provider.name}' is not available; skipped refinement.",
            Severity.INFO,
        )
        return 0

    refined = 0
    for table in project.tables:
        for measure in table.measures:
            if measure.dax_expression or not measure.cognos_expression:
                continue
            request = AiRequest(
                instruction=(
                    "Translate the following IBM Cognos report expression into a single "
                    "Microsoft Power BI DAX measure expression. Return only the DAX expression, "
                    "with no explanation, code fences, or measure name."
                ),
                context=(
                    f"Table: {table.name}\n"
                    f"Measure: {measure.name}\n"
                    f"Cognos expression: {measure.cognos_expression}"
                ),
            )
            result = provider.complete(request)
            if result.ok and result.text:
                measure.dax_expression = result.text.strip()
                refined += 1
            else:
                project.add_flag(
                    "ai-refine-failed",
                    f"AI could not translate measure '{measure.name}': "
                    f"{result.error or 'empty response'}",
                    Severity.WARNING,
                    source_ref=measure.cognos_expression,
                )
    return refined


def run_migration(
    source: str | Path,
    out_dir: str | Path,
    ai: str | None = None,
) -> MigrationResult:
    """Run the full migration for a single Cognos report specification.

    Args:
        source: Path to the Cognos report specification XML.
        out_dir: Directory to write the Power BI Project into.
        ai: AI provider name (``claude``, ``copilot``, ``codex``, or ``none``).

    Returns:
        A :class:`MigrationResult` summarizing the migration.
    """
    project = parse_report(source)
    provider = get_provider(ai)
    refinements = _refine_with_ai(project, provider)
    pbip_path = generate_pbip(project, out_dir)

    measure_count = sum(len(table.measures) for table in project.tables)
    return MigrationResult(
        project_name=project.name,
        pbip_path=str(pbip_path),
        table_count=len(project.tables),
        page_count=len(project.pages),
        measure_count=measure_count,
        review_flag_count=len(project.review_flags),
        ai_provider=provider.name,
        ai_refinements=refinements,
    )
