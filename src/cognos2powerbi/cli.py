"""Command-line interface for the Cognos to Power BI migration tool."""

from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table as RichTable

from cognos2powerbi import __version__
from cognos2powerbi.core.ai import get_provider
from cognos2powerbi.core.pipeline import run_migration

console = Console()


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
@click.option(
    "--ai",
    type=click.Choice(["claude", "copilot", "codex", "none"], case_sensitive=False),
    default="none",
    show_default=True,
    help="AI provider used to refine expressions that have no deterministic mapping.",
)
def migrate(source: Path, out_dir: Path, ai: str) -> None:
    """Migrate a single Cognos report specification to a Power BI Project."""
    console.print(f"[bold]Migrating[/bold] {source}")
    result = run_migration(source, out_dir, ai=ai)

    summary = RichTable(show_header=False, box=None, pad_edge=False)
    summary.add_row("Project", result.project_name)
    summary.add_row("PBIP", result.pbip_path)
    summary.add_row("Tables", str(result.table_count))
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


@cli.command()
@click.option(
    "--ai",
    type=click.Choice(["claude", "copilot", "codex", "none"], case_sensitive=False),
    default=None,
    help="Provider to check. Defaults to COGNOS2PBI_AI_PROVIDER.",
)
def doctor(ai: str | None) -> None:
    """Check that the selected AI provider CLI is available."""
    provider = get_provider(ai)
    if provider.name == "none":
        console.print("AI refinement is [bold]disabled[/bold] (provider: none).")
        return
    if provider.is_available():
        console.print(f"[green]Provider '{provider.name}' is available.[/green]")
    else:
        console.print(f"[red]Provider '{provider.name}' CLI was not found on PATH.[/red]")
        sys.exit(1)


def main() -> None:
    """Console-script entry point."""
    cli()


if __name__ == "__main__":
    main()
