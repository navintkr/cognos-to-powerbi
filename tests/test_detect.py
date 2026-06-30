"""Tests for source-kind auto-detection."""

from __future__ import annotations

from pathlib import Path

from cognos2powerbi.core.detect import SourceKind, detect_source_file, detect_source_kind

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_detects_report_xml() -> None:
    assert detect_source_file(EXAMPLES / "sample_report.xml") is SourceKind.REPORT


def test_detects_framework_manager_model() -> None:
    assert detect_source_file(EXAMPLES / "sample_model.xml") is SourceKind.FM_MODEL


def test_detects_data_module() -> None:
    assert detect_source_file(EXAMPLES / "sample_data_module.json") is SourceKind.DATA_MODULE


def test_detects_dashboard() -> None:
    assert detect_source_file(EXAMPLES / "sample_dashboard.json") is SourceKind.DASHBOARD


def test_content_first_dashboard_over_extension() -> None:
    payload = b'{"widgets": {"w1": {}}, "layout": {"items": []}}'
    assert detect_source_kind(payload, filename="thing.json") is SourceKind.DASHBOARD


def test_content_first_data_module_over_extension() -> None:
    payload = b'{"querySubject": [{"label": "Sales"}]}'
    assert detect_source_kind(payload, filename="thing.json") is SourceKind.DATA_MODULE


def test_extension_fallback_for_unknown_json() -> None:
    payload = b'{"foo": 1}'
    assert detect_source_kind(payload, filename="thing.module") is SourceKind.DATA_MODULE
