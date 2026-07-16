"""Tests for the CLI review-breakdown output."""

from __future__ import annotations

from cognos2powerbi.cli import _print_review_breakdown
from cognos2powerbi.core.ir.models import ReviewFlag, Severity
from cognos2powerbi.core.pipeline import MigrationResult


def _result(flags: list[ReviewFlag]) -> MigrationResult:
    return MigrationResult(
        project_name="Demo",
        pbip_path="out/Demo.pbip",
        table_count=1,
        page_count=1,
        measure_count=0,
        review_flag_count=len(flags),
        ai_provider="none",
        ai_refinements=0,
        review_flags=flags,
    )


def test_review_breakdown_groups_by_category(capsys) -> None:
    flags = [
        ReviewFlag(code="detail-filter", message="a", severity=Severity.WARNING),
        ReviewFlag(code="detail-filter", message="b", severity=Severity.WARNING),
        ReviewFlag(code="join-relationship", message="c", severity=Severity.INFO),
    ]
    _print_review_breakdown(_result(flags))
    out = capsys.readouterr().out
    assert "detail-filter" in out
    assert "join-relationship" in out
    # The two detail-filter items are grouped into a single row with a count of 2.
    assert "2" in out


def test_review_breakdown_handles_no_flags(capsys) -> None:
    _print_review_breakdown(_result([]))
    assert capsys.readouterr().out == ""
