"""End-to-end migration pipeline: parse, refine with AI, generate PBIP."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from cognos2powerbi.core.ai import AiProvider, AiRequest, get_provider
from cognos2powerbi.core.generators import generate_pbip
from cognos2powerbi.core.ir.models import (
    DataSource,
    MigrationProject,
    Severity,
)
from cognos2powerbi.core.modeling import ModelingSummary, analyze_model
from cognos2powerbi.core.parsers import parse_model, parse_report


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
    fact_table_count: int = 0
    dimension_table_count: int = 0
    date_table_count: int = 0
    relationship_count: int = 0
    inactive_relationship_count: int = 0


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
    if provider.name == "none":
        return 0

    refined = 0
    for table in project.tables:
        for measure in table.measures:
            if not measure.cognos_expression:
                continue
            if measure.dax_expression and not measure.needs_review:
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
                measure.needs_review = False
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
    data_source: DataSource | None = None,
    infer_model: bool = True,
) -> MigrationResult:
    """Run the full migration for a single Cognos report specification.

    Args:
        source: Path to the Cognos report specification XML.
        out_dir: Directory to write the Power BI Project into.
        ai: AI provider name (``claude``, ``copilot``, ``codex``, or ``none``).
        data_source: Optional physical data source used for generated Power Query partitions.
        infer_model: Run the star-schema modeling pass (classify tables, infer relationships).

    Returns:
        A :class:`MigrationResult` summarizing the migration.
    """
    project = parse_report(source)
    if data_source is not None:
        project.data_source = data_source
    summary = analyze_model(project) if infer_model else None
    provider = get_provider(ai)
    refinements = _refine_with_ai(project, provider)
    pbip_path = generate_pbip(project, out_dir)

    measure_count = sum(len(table.measures) for table in project.tables)
    return _build_result(project, pbip_path, measure_count, provider.name, refinements, summary)


def run_model_migration(
    source: str | Path,
    out_dir: str | Path,
    ai: str | None = None,
    data_source: DataSource | None = None,
    infer_model: bool = True,
) -> MigrationResult:
    """Run the migration for a single Cognos Framework Manager model.

    Args:
        source: Path to the Framework Manager model XML.
        out_dir: Directory to write the Power BI Project into.
        ai: AI provider name (``claude``, ``copilot``, ``codex``, or ``none``).
        data_source: Optional physical data source used for generated Power Query partitions.
        infer_model: Run the star-schema modeling pass (classify tables, infer relationships).

    Returns:
        A :class:`MigrationResult` summarizing the migration.
    """
    project = parse_model(source)
    if data_source is not None:
        project.data_source = data_source
    summary = analyze_model(project) if infer_model else None
    provider = get_provider(ai)
    refinements = _refine_with_ai(project, provider)
    pbip_path = generate_pbip(project, out_dir)

    measure_count = sum(len(table.measures) for table in project.tables)
    return _build_result(project, pbip_path, measure_count, provider.name, refinements, summary)


def _build_result(
    project: MigrationProject,
    pbip_path: Path,
    measure_count: int,
    provider_name: str,
    refinements: int,
    summary: ModelingSummary | None,
) -> MigrationResult:
    return MigrationResult(
        project_name=project.name,
        pbip_path=str(pbip_path),
        table_count=len(project.tables),
        page_count=len(project.pages),
        measure_count=measure_count,
        review_flag_count=len(project.review_flags),
        ai_provider=provider_name,
        ai_refinements=refinements,
        fact_table_count=summary.fact_tables if summary else 0,
        dimension_table_count=summary.dimension_tables if summary else 0,
        date_table_count=summary.date_tables if summary else 0,
        relationship_count=len(project.relationships),
        inactive_relationship_count=summary.inactive_relationships if summary else 0,
    )
