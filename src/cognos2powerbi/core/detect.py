"""Detect the kind of a Cognos source artifact.

The toolkit converts four kinds of Cognos source: report specifications and Framework Manager
models (XML), and data modules and dashboards (JSON). Batch migration and the SaaS portal need to
route each file to the right parser without the user having to classify it, so this module sniffs
the content (and falls back to the file extension) to decide.
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path


class SourceKind(str, Enum):
    """A supported Cognos source artifact."""

    REPORT = "report"
    FM_MODEL = "model"
    DATA_MODULE = "module"
    DASHBOARD = "dashboard"
    UNKNOWN = "unknown"


def _detect_json(text: str) -> SourceKind:
    try:
        document = json.loads(text)
    except ValueError:
        document = None
    if isinstance(document, dict):
        keys = {key.lower() for key in document.keys()}
        if "widgets" in keys or "layout" in keys:
            return SourceKind.DASHBOARD
        if "querysubject" in keys or "relationship" in keys:
            return SourceKind.DATA_MODULE
    # Fall back to substring sniffing for truncated or wrapped payloads.
    lowered = text.lower()
    if '"widgets"' in lowered or '"layout"' in lowered:
        return SourceKind.DASHBOARD
    if '"querysubject"' in lowered:
        return SourceKind.DATA_MODULE
    return SourceKind.UNKNOWN


def _detect_xml(text: str) -> SourceKind:
    lowered = text.lower()
    # Framework Manager models use the BMT schema and querySubject elements.
    if "querysubject" in lowered or "/bmt/" in lowered or "<project" in lowered:
        return SourceKind.FM_MODEL
    if "<report" in lowered:
        return SourceKind.REPORT
    # Default XML to a report specification; the parser flags anything it cannot map.
    return SourceKind.REPORT


def detect_source_kind(data: bytes, filename: str | None = None) -> SourceKind:
    """Return the :class:`SourceKind` for raw source bytes.

    Detection is content-first (JSON object keys or XML root and element names) with a filename
    extension fallback for ambiguous payloads.
    """
    stripped = data.lstrip()
    if stripped[:1] in (b"{", b"["):
        kind = _detect_json(stripped.decode("utf-8", errors="ignore"))
        if kind is not SourceKind.UNKNOWN:
            return kind
    elif stripped[:1] == b"<":
        return _detect_xml(stripped[:8192].decode("utf-8", errors="ignore"))

    # Extension fallback when the content sniff was inconclusive.
    suffix = Path(filename).suffix.lower() if filename else ""
    if suffix in {".json", ".module"}:
        return SourceKind.DATA_MODULE
    if suffix in {".dashboard", ".exploration"}:
        return SourceKind.DASHBOARD
    if suffix in {".cpf", ".fm"}:
        return SourceKind.FM_MODEL
    if suffix in {".xml", ".spec", ".txt"}:
        return SourceKind.REPORT
    return SourceKind.UNKNOWN


def detect_source_file(path: str | Path) -> SourceKind:
    """Return the :class:`SourceKind` for a file on disk."""
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Source file not found: {source}")
    return detect_source_kind(source.read_bytes(), filename=source.name)
