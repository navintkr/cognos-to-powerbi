"""Tests for the deterministic Cognos-to-DAX expression translator."""

from __future__ import annotations

from cognos2powerbi.core.translate import translate_measure_expression


def test_simple_reference_with_aggregate() -> None:
    result = translate_measure_expression("[Sales].[Measures].[Revenue]", "Sales", "total")
    assert result.dax == "SUM(Sales[Revenue])"
    assert result.confident is True


def test_simple_reference_without_aggregate() -> None:
    result = translate_measure_expression("[Sales].[Products].[Line]", "Sales", "none")
    assert result.dax == "Sales[Line]"
    assert result.confident is True


def test_arithmetic_of_references_is_aggregated() -> None:
    result = translate_measure_expression(
        "[Sales].[Measures].[Revenue] - [Sales].[Measures].[Cost]", "Sales", "total"
    )
    assert result.dax == "SUM(Sales[Revenue]) - SUM(Sales[Cost])"
    assert result.confident is True


def test_if_then_else_becomes_dax_if() -> None:
    result = translate_measure_expression(
        "if ([Sales].[Measures].[Revenue] > 0) then (1) else (0)", "Sales", "none"
    )
    assert result.dax == "IF(Sales[Revenue] > 0, 1, 0)"
    assert result.confident is True


def test_substring_function_maps_to_mid() -> None:
    result = translate_measure_expression(
        "substring([Sales].[Products].[Line], 1, 3)", "Sales", "none"
    )
    assert result.dax == "MID(Sales[Line], 1, 3)"
    assert result.confident is True


def test_extract_year_maps_to_year() -> None:
    result = translate_measure_expression(
        "extract(year, [Sales].[Time].[Order date])", "Sales", "none"
    )
    assert result.dax == "YEAR(Sales[Order date])"
    assert result.confident is True


def test_unknown_function_is_not_confident() -> None:
    result = translate_measure_expression(
        "rank([Sales].[Measures].[Revenue])", "Sales", "calculated"
    )
    assert result.confident is False
    assert result.dax is not None


def test_empty_expression_returns_none() -> None:
    result = translate_measure_expression("", "Sales", "total")
    assert result.dax is None
    assert result.confident is False
