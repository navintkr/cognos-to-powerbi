"""Smoke tests for the FastAPI migration portal.

These avoid an HTTP client dependency and assert the app wiring instead: routes are registered,
and the validation helpers reject bad input.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from cognos2powerbi.api.main import _validated_kind, _validated_provider, app


def test_routes_are_registered() -> None:
    paths = {route.path for route in app.routes}
    assert "/health" in paths
    assert "/api/v1/migrate" in paths
    assert "/api/v1/analyze" in paths
    assert "/api/v1/batch" in paths


def test_validated_kind_accepts_known_kinds() -> None:
    for kind in ("auto", "report", "model", "module", "dashboard"):
        assert _validated_kind(kind) == kind


def test_validated_kind_rejects_unknown() -> None:
    with pytest.raises(HTTPException):
        _validated_kind("spreadsheet")


def test_validated_provider_rejects_unknown() -> None:
    with pytest.raises(HTTPException):
        _validated_provider("gpt-9")
