"""Batch and folder migration with a consolidated coverage report.

Migrates many Cognos source files in one pass. Each file is auto-detected (report, Framework
Manager model, data module, or dashboard), converted into its own Power BI Project subfolder, and
recorded in a single coverage report (Markdown and JSON) so a team can see, at a glance, what was
converted and what still needs review.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from cognos2powerbi.core.detect import SourceKind, detect_source_kind
from cognos2powerbi.core.ir.models import DataSource
from cognos2powerbi.core.pipeline import run_auto_migration

# File extensions considered candidate Cognos sources when scanning a folder.
_SOURCE_SUFFIXES = {".xml", ".json", ".module", ".dashboard", ".exploration", ".spec", ".cpf"}


class BatchItemResult(BaseModel):
    """The outcome of migrating a single source file in a batch."""

    source: str
    kind: str = SourceKind.UNKNOWN.value
    status: str = "ok"  # ok | failed
    error: str | None = None
    project_name: str | None = None
    output: str | None = None
    table_count: int = 0
    measure_count: int = 0
    page_count: int = 0
    relationship_count: int = 0
    review_flag_count: int = 0


class BatchResult(BaseModel):
    """The outcome of a batch migration."""

    out_dir: str
    coverage_report: str
    items: list[BatchItemResult] = Field(default_factory=list)

    @property
    def succeeded(self) -> int:
        return sum(1 for item in self.items if item.status == "ok")

    @property
    def failed(self) -> int:
        return sum(1 for item in self.items if item.status == "failed")


def collect_sources(folder: str | Path, recursive: bool = True) -> list[Path]:
    """Return the candidate Cognos source files within a folder."""
    base = Path(folder)
    if not base.is_dir():
        raise NotADirectoryError(f"Not a directory: {base}")
    pattern = "**/*" if recursive else "*"
    return sorted(
        path
        for path in base.glob(pattern)
        if path.is_file() and path.suffix.lower() in _SOURCE_SUFFIXES
    )


def _safe_subdir_name(stem: str, used: set[str]) -> str:
    """Return a unique, filesystem-safe subdirectory name for a project."""
    cleaned = "".join(ch if ch.isalnum() or ch in (" ", "-", "_") else "_" for ch in stem).strip()
    cleaned = cleaned or "project"
    candidate = cleaned
    suffix = 2
    while candidate in used:
        candidate = f"{cleaned}_{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def run_batch_migration(
    sources: list[str | Path],
    out_dir: str | Path,
    ai: str | None = None,
    data_source: DataSource | None = None,
    infer_model: bool = True,
) -> BatchResult:
    """Migrate a list of Cognos source files into one output directory.

    Each source is auto-detected and written to its own subfolder. A coverage report is written to
    ``COVERAGE_REPORT.md`` and ``coverage.json`` in ``out_dir``.
    """
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    items: list[BatchItemResult] = []
    used_names: set[str] = set()

    for source in sources:
        source_path = Path(source)
        item = BatchItemResult(source=str(source_path))
        try:
            kind = detect_source_kind(source_path.read_bytes(), filename=source_path.name)
            item.kind = kind.value
            subdir = _safe_subdir_name(source_path.stem, used_names)
            target = root / subdir
            result = run_auto_migration(
                source_path,
                target,
                ai=ai,
                data_source=data_source,
                infer_model=infer_model,
            )
            item.status = "ok"
            item.project_name = result.project_name
            item.output = str(target)
            item.kind = result.source_kind
            item.table_count = result.table_count
            item.measure_count = result.measure_count
            item.page_count = result.page_count
            item.relationship_count = result.relationship_count
            item.review_flag_count = result.review_flag_count
        except (ValueError, FileNotFoundError, OSError) as exc:
            item.status = "failed"
            item.error = str(exc)
        items.append(item)

    report_path = root / "COVERAGE_REPORT.md"
    batch = BatchResult(out_dir=str(root), coverage_report=str(report_path), items=items)
    _write_coverage_report(report_path, batch)
    _write_text(root / "coverage.json", batch.model_dump_json(indent=2))
    return batch


def _write_coverage_report(path: Path, batch: BatchResult) -> None:
    total = len(batch.items)
    lines = [
        "# Migration coverage report",
        "",
        f"Converted {batch.succeeded} of {total} source file(s); {batch.failed} failed.",
        "",
        "| Status | Source | Kind | Project | Tables | Measures | Pages | Relationships | Review |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in batch.items:
        status = "ok" if item.status == "ok" else "FAILED"
        project = item.project_name or "-"
        lines.append(
            f"| {status} | {Path(item.source).name} | {item.kind} | {project} | "
            f"{item.table_count} | {item.measure_count} | {item.page_count} | "
            f"{item.relationship_count} | {item.review_flag_count} |"
        )
    failures = [item for item in batch.items if item.status == "failed"]
    if failures:
        lines.extend(["", "## Failures", ""])
        for item in failures:
            error = (item.error or "unknown error").replace("\n", " ")
            lines.append(f"- {Path(item.source).name}: {error}")
    totals = _totals(batch)
    lines.extend(
        [
            "",
            "## Totals",
            "",
            f"- Tables: {totals['tables']}",
            f"- Measures: {totals['measures']}",
            f"- Pages: {totals['pages']}",
            f"- Relationships: {totals['relationships']}",
            f"- Items to review: {totals['review']}",
            "",
        ]
    )
    _write_text(path, "\n".join(lines))


def _totals(batch: BatchResult) -> dict[str, int]:
    return {
        "tables": sum(item.table_count for item in batch.items),
        "measures": sum(item.measure_count for item in batch.items),
        "pages": sum(item.page_count for item in batch.items),
        "relationships": sum(item.relationship_count for item in batch.items),
        "review": sum(item.review_flag_count for item in batch.items),
    }


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
