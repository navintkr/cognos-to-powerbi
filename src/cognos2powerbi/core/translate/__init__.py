"""Deterministic translation helpers (Cognos expressions to DAX)."""

from .expressions import TranslationResult, translate_measure_expression

__all__ = ["TranslationResult", "translate_measure_expression"]
