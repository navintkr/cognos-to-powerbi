"""Provider-agnostic AI adapter.

The migration engine performs a deterministic conversion without any AI. The AI layer is an
optional refinement stage that translates Cognos expressions and layouts that have no direct
mechanical mapping. Providers are pluggable and shell out to the corresponding CLI so the tool
stays credential-free in its own process.
"""

from cognos2powerbi.core.ai.base import AiProvider, AiRequest, AiResult, NullProvider
from cognos2powerbi.core.ai.providers import get_provider

__all__ = ["AiProvider", "AiRequest", "AiResult", "NullProvider", "get_provider"]
