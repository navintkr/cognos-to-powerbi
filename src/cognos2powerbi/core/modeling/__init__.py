"""Star-schema modeling: classify tables and infer Power BI relationships."""

from __future__ import annotations

from cognos2powerbi.core.modeling.star_schema import ModelingSummary, analyze_model

__all__ = ["ModelingSummary", "analyze_model"]
