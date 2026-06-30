"""Tests for batch and folder migration with a coverage report."""

from __future__ import annotations

import json
from pathlib import Path

from cognos2powerbi.core.batch import collect_sources, run_batch_migration

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_collect_sources_finds_known_extensions() -> None:
    found = collect_sources(EXAMPLES, recursive=True)
    names = {path.name for path in found}
    assert "sample_report.xml" in names
    assert "sample_data_module.json" in names
    assert "sample_dashboard.json" in names


def test_batch_migrates_mixed_sources(tmp_path: Path) -> None:
    sources = [
        EXAMPLES / "sample_report.xml",
        EXAMPLES / "sample_model.xml",
        EXAMPLES / "sample_data_module.json",
        EXAMPLES / "sample_dashboard.json",
    ]
    batch = run_batch_migration(sources, tmp_path, ai="none")

    assert batch.succeeded == 4
    assert batch.failed == 0
    kinds = {item.kind for item in batch.items}
    assert {"report", "model", "module", "dashboard"} <= kinds


def test_batch_writes_coverage_report(tmp_path: Path) -> None:
    sources = [EXAMPLES / "sample_data_module.json", EXAMPLES / "sample_dashboard.json"]
    batch = run_batch_migration(sources, tmp_path, ai="none")

    report = Path(batch.coverage_report)
    assert report.is_file()
    text = report.read_text(encoding="utf-8")
    assert "Migration coverage report" in text
    assert "| Status |" in text

    coverage_json = tmp_path / "coverage.json"
    assert coverage_json.is_file()
    data = json.loads(coverage_json.read_text(encoding="utf-8"))
    assert len(data["items"]) == 2


def test_batch_records_failure_for_unknown_source(tmp_path: Path) -> None:
    bad = tmp_path / "broken.json"
    bad.write_text("not valid json or known shape", encoding="utf-8")
    batch = run_batch_migration([bad], tmp_path / "out", ai="none")

    assert batch.failed == 1
    assert batch.items[0].status == "failed"
