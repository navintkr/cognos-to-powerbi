"""Command-line interface for the Cognos to Power BI migration tool."""

from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table as RichTable

from cognos2powerbi import __version__
from cognos2powerbi.core.ai import get_provider
from cognos2powerbi.core.batch import BatchResult, collect_sources, run_batch_migration
from cognos2powerbi.core.ir.models import DataSource, DataSourceKind
from cognos2powerbi.core.pipeline import (
    MigrationResult,
    run_dashboard_migration,
    run_migration,
    run_model_migration,
    run_module_migration,
)

console = Console()

_SOURCE_TYPE_OPTION = click.option(
    "--source-type",
    type=click.Choice(["sqlserver", "none"], case_sensitive=False),
    default="sqlserver",
    show_default=True,
    help="Physical data source for the generated Power Query partitions.",
)
_SERVER_OPTION = click.option(
    "--server",
    default="localhost",
    show_default=True,
    help="SQL Server name used for the Server parameter in the generated model.",
)
_DATABASE_OPTION = click.option(
    "--database",
    default="AdventureWorks",
    show_default=True,
    help="Database name used for the Database parameter in the generated model.",
)
_SCHEMA_OPTION = click.option(
    "--schema",
    "schema_name",
    default="dbo",
    show_default=True,
    help="Schema used when navigating to tables in the generated Power Query.",
)
_INFER_MODEL_OPTION = click.option(
    "--infer-model/--no-infer-model",
    "infer_model",
    default=True,
    show_default=True,
    help="Classify fact/dimension tables and infer relationship cardinality (star schema).",
)
_AI_OPTION = click.option(
    "--ai",
    type=click.Choice(["claude", "copilot", "codex", "azure", "none"], case_sensitive=False),
    default="none",
    show_default=True,
    help=(
        "AI provider used to refine expressions that have no deterministic mapping "
        "('azure' uses Azure OpenAI)."
    ),
)


def _build_data_source(
    source_type: str, server: str, database: str, schema_name: str
) -> DataSource:
    kind = DataSourceKind.NONE if source_type.lower() == "none" else DataSourceKind.SQL_SERVER
    return DataSource(
        kind=kind,
        server=server,
        database=database,
        schema_name=schema_name,
    )


def _print_summary(result: MigrationResult, out_dir: Path) -> None:
    summary = RichTable(show_header=False, box=None, pad_edge=False)
    summary.add_row("Project", result.project_name)
    summary.add_row("Source kind", result.source_kind)
    summary.add_row("PBIP", result.pbip_path)
    summary.add_row("Tables", str(result.table_count))
    summary.add_row(
        "Facts / Dimensions / Date",
        f"{result.fact_table_count} / {result.dimension_table_count} / {result.date_table_count}",
    )
    summary.add_row(
        "Relationships",
        f"{result.relationship_count} ({result.inactive_relationship_count} inactive)",
    )
    summary.add_row("Measures", str(result.measure_count))
    summary.add_row("Pages", str(result.page_count))
    summary.add_row("AI provider", result.ai_provider)
    summary.add_row("AI refinements", str(result.ai_refinements))
    summary.add_row("Items to review", str(result.review_flag_count))
    console.print(summary)

    if result.review_flag_count:
        review_path = Path(out_dir) / "MIGRATION_REVIEW.md"
        console.print(
            f"[yellow]{result.review_flag_count} item(s) need review. See {review_path}.[/yellow]"
        )
    console.print("[green]Done.[/green]")


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="cognos2pbi")
def cli() -> None:
    """Migrate IBM Cognos reports and models to Microsoft Power BI (PBIP / TMDL / PBIR)."""


@cli.command()
@click.argument("source", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--out",
    "out_dir",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Output directory for the generated Power BI Project.",
)
@_AI_OPTION
@_SOURCE_TYPE_OPTION
@_SERVER_OPTION
@_DATABASE_OPTION
@_SCHEMA_OPTION
@_INFER_MODEL_OPTION
def migrate(
    source: Path,
    out_dir: Path,
    ai: str,
    source_type: str,
    server: str,
    database: str,
    schema_name: str,
    infer_model: bool,
) -> None:
    """Migrate a single Cognos report specification to a Power BI Project."""
    console.print(f"[bold]Migrating[/bold] {source}")
    data_source = _build_data_source(source_type, server, database, schema_name)
    result = run_migration(source, out_dir, ai=ai, data_source=data_source, infer_model=infer_model)
    _print_summary(result, out_dir)


@cli.command(name="migrate-model")
@click.argument("source", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--out",
    "out_dir",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Output directory for the generated Power BI Project.",
)
@_AI_OPTION
@_SOURCE_TYPE_OPTION
@_SERVER_OPTION
@_DATABASE_OPTION
@_SCHEMA_OPTION
@_INFER_MODEL_OPTION
def migrate_model(
    source: Path,
    out_dir: Path,
    ai: str,
    source_type: str,
    server: str,
    database: str,
    schema_name: str,
    infer_model: bool,
) -> None:
    """Migrate a Cognos Framework Manager model to a Power BI semantic model."""
    console.print(f"[bold]Migrating model[/bold] {source}")
    data_source = _build_data_source(source_type, server, database, schema_name)
    result = run_model_migration(
        source, out_dir, ai=ai, data_source=data_source, infer_model=infer_model
    )
    _print_summary(result, out_dir)


@cli.command(name="migrate-module")
@click.argument("source", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--out",
    "out_dir",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Output directory for the generated Power BI Project.",
)
@_AI_OPTION
@_SOURCE_TYPE_OPTION
@_SERVER_OPTION
@_DATABASE_OPTION
@_SCHEMA_OPTION
@_INFER_MODEL_OPTION
def migrate_module(
    source: Path,
    out_dir: Path,
    ai: str,
    source_type: str,
    server: str,
    database: str,
    schema_name: str,
    infer_model: bool,
) -> None:
    """Migrate a Cognos data module (.module JSON) to a Power BI semantic model."""
    console.print(f"[bold]Migrating data module[/bold] {source}")
    data_source = _build_data_source(source_type, server, database, schema_name)
    result = run_module_migration(
        source, out_dir, ai=ai, data_source=data_source, infer_model=infer_model
    )
    _print_summary(result, out_dir)


@cli.command(name="migrate-dashboard")
@click.argument("source", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--out",
    "out_dir",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Output directory for the generated Power BI Project.",
)
@_AI_OPTION
@_SOURCE_TYPE_OPTION
@_SERVER_OPTION
@_DATABASE_OPTION
@_SCHEMA_OPTION
@_INFER_MODEL_OPTION
def migrate_dashboard(
    source: Path,
    out_dir: Path,
    ai: str,
    source_type: str,
    server: str,
    database: str,
    schema_name: str,
    infer_model: bool,
) -> None:
    """Migrate a Cognos dashboard (JSON) to Power BI report pages."""
    console.print(f"[bold]Migrating dashboard[/bold] {source}")
    data_source = _build_data_source(source_type, server, database, schema_name)
    result = run_dashboard_migration(
        source, out_dir, ai=ai, data_source=data_source, infer_model=infer_model
    )
    _print_summary(result, out_dir)


@cli.command(name="migrate-batch")
@click.argument(
    "sources",
    nargs=-1,
    required=True,
    type=click.Path(exists=True, path_type=Path),
)
@click.option(
    "--out",
    "out_dir",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Output directory for the generated Power BI Projects and coverage report.",
)
@_AI_OPTION
@click.option(
    "--recursive/--no-recursive",
    default=True,
    show_default=True,
    help="When a folder is given, scan it recursively for Cognos sources.",
)
@_SOURCE_TYPE_OPTION
@_SERVER_OPTION
@_DATABASE_OPTION
@_SCHEMA_OPTION
@_INFER_MODEL_OPTION
def migrate_batch(
    sources: tuple[Path, ...],
    out_dir: Path,
    ai: str,
    recursive: bool,
    source_type: str,
    server: str,
    database: str,
    schema_name: str,
    infer_model: bool,
) -> None:
    """Migrate many Cognos sources (files and/or folders) with a coverage report.

    Each source is auto-detected (report, model, data module, or dashboard) and written to its own
    subfolder. A consolidated COVERAGE_REPORT.md is written to the output directory.
    """
    files: list[Path] = []
    for entry in sources:
        if entry.is_dir():
            files.extend(collect_sources(entry, recursive=recursive))
        else:
            files.append(entry)
    if not files:
        console.print("[yellow]No Cognos source files were found.[/yellow]")
        raise SystemExit(1)

    console.print(f"[bold]Migrating[/bold] {len(files)} source file(s)")
    data_source = _build_data_source(source_type, server, database, schema_name)
    batch = run_batch_migration(
        [str(path) for path in files],
        out_dir,
        ai=ai,
        data_source=data_source,
        infer_model=infer_model,
    )
    _print_batch_summary(batch)


def _print_batch_summary(batch: BatchResult) -> None:
    table = RichTable(title="Batch migration")
    table.add_column("Status")
    table.add_column("Source")
    table.add_column("Kind")
    table.add_column("Tables", justify="right")
    table.add_column("Measures", justify="right")
    table.add_column("Pages", justify="right")
    table.add_column("Review", justify="right")
    for item in batch.items:
        status = "[green]ok[/green]" if item.status == "ok" else "[red]FAILED[/red]"
        table.add_row(
            status,
            Path(item.source).name,
            item.kind,
            str(item.table_count),
            str(item.measure_count),
            str(item.page_count),
            str(item.review_flag_count),
        )
    console.print(table)
    console.print(
        f"[bold]{batch.succeeded}[/bold] succeeded, "
        f"[bold]{batch.failed}[/bold] failed. Coverage report: {batch.coverage_report}"
    )
    console.print("[green]Done.[/green]")


@cli.command()
@click.option(
    "--ai",
    type=click.Choice(["claude", "copilot", "codex", "azure", "none"], case_sensitive=False),
    default=None,
    help="Provider to check. Defaults to COGNOS2PBI_AI_PROVIDER.",
)
def doctor(ai: str | None) -> None:
    """Check that the selected AI provider is available."""
    provider = get_provider(ai)
    if provider.name == "none":
        console.print("AI refinement is [bold]disabled[/bold] (provider: none).")
        return
    if provider.is_available():
        console.print(f"[green]Provider '{provider.name}' is available.[/green]")
    else:
        console.print(f"[red]Provider '{provider.name}' is not available or not configured.[/red]")
        sys.exit(1)


def main() -> None:
    """Console-script entry point."""
    cli()


if __name__ == "__main__":
    main()
