"""Tests for the Azure OpenAI provider registration and DAX normalization.

These avoid any network call: they check provider wiring and the deterministic helpers.
"""

from __future__ import annotations

from cognos2powerbi.core.ai import get_provider
from cognos2powerbi.core.ai.providers import AzureOpenAiProvider
from cognos2powerbi.core.generators.pbip_generator import _dax_single_line
from cognos2powerbi.core.translate import translate_measure_expression


def test_azure_provider_is_registered() -> None:
    for alias in ("azure", "aoai", "azureopenai"):
        provider = get_provider(alias)
        assert isinstance(provider, AzureOpenAiProvider)
        assert provider.name == "azure"


def test_dax_single_line_collapses_multiline_and_comments() -> None:
    multiline = (
        "CALCULATE(\n    MIN('SRS'[List]), // running minimum\n    ALLEXCEPT('SRS', 'SRS'[Date])\n)"
    )
    result = _dax_single_line(multiline)
    assert "\n" not in result
    assert "//" not in result
    assert result.startswith("CALCULATE(")
    assert "ALLEXCEPT('SRS', 'SRS'[Date])" in result


def test_hyphenated_cognos_function_is_not_confident() -> None:
    # running-count has no deterministic DAX mapping and must not be marked confident.
    result = translate_measure_expression("running-count([Q].[Order ID])", "Q", "none")
    assert result.confident is False
