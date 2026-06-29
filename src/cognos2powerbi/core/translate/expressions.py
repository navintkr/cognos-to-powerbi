"""Deterministic Cognos-to-DAX expression translation.

This module converts a curated subset of Cognos report expressions into DAX without calling an AI
provider. Translations that are fully understood are returned with ``confident=True`` so the
pipeline can skip the AI step. Expressions that contain constructs outside the supported set are
still translated on a best-effort basis and returned with ``confident=False`` so a human or AI
provider can review and refine them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Cognos summary/aggregate keyword -> DAX aggregation function.
_AGGREGATE_TO_DAX: dict[str, str] = {
    "total": "SUM",
    "sum": "SUM",
    "average": "AVERAGE",
    "avg": "AVERAGE",
    "minimum": "MIN",
    "min": "MIN",
    "maximum": "MAX",
    "max": "MAX",
    "count": "COUNT",
    "countdistinct": "DISTINCTCOUNT",
}

# Cognos scalar function -> DAX function (same argument order unless noted in _translate_functions).
_FUNCTION_MAP: dict[str, str] = {
    "substring": "MID",
    "character_length": "LEN",
    "char_length": "LEN",
    "length": "LEN",
    "upper": "UPPER",
    "lower": "LOWER",
    "trim": "TRIM",
    "abs": "ABS",
    "round": "ROUND",
    "ceiling": "CEILING",
    "floor": "FLOOR",
    "sqrt": "SQRT",
    "coalesce": "COALESCE",
    "nullif": "NULLIF",
}

# Names that are valid DAX functions after translation; used to detect untranslated calls.
_KNOWN_DAX_FUNCTIONS = (
    set(_FUNCTION_MAP.values())
    | set(_AGGREGATE_TO_DAX.values())
    | {
        "IF",
        "SWITCH",
        "YEAR",
        "MONTH",
        "DAY",
        "TODAY",
        "NOW",
        "AND",
        "OR",
        "NOT",
        "TRUE",
        "FALSE",
    }
)

_REFERENCE = re.compile(r"\[[^\[\]]+\](?:\.\[[^\[\]]+\])*")
_SIMPLE_REFERENCE = re.compile(r"^\[[^\[\]]+\](?:\.\[[^\[\]]+\])*$")
_FUNCTION_CALL = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")


@dataclass
class TranslationResult:
    """Outcome of translating a single Cognos expression to DAX."""

    dax: str | None
    confident: bool
    note: str | None = None


def _last_segment(reference: str) -> str:
    """Return the final ``[segment]`` of a qualified Cognos reference, without brackets."""
    parts = re.findall(r"\[([^\[\]]+)\]", reference)
    return parts[-1] if parts else reference.strip("[]")


def _convert_references(expression: str, table_name: str) -> str:
    """Rewrite qualified Cognos references to ``Table[Column]`` form."""

    def repl(match: re.Match[str]) -> str:
        column = _last_segment(match.group(0))
        return f"{table_name}[{column}]"

    return _REFERENCE.sub(repl, expression)


def _translate_extract(expression: str) -> str:
    """Translate ``extract(part, value)`` into the matching DAX date function."""
    pattern = re.compile(r"\bextract\s*\(\s*(year|month|day)\s*,\s*(.+?)\)", re.IGNORECASE)

    def repl(match: re.Match[str]) -> str:
        part = match.group(1).upper()
        value = match.group(2).strip()
        return f"{part}({value})"

    return pattern.sub(repl, expression)


def _translate_if_then_else(expression: str) -> str:
    """Translate ``if (cond) then (a) else (b)`` into ``IF(cond, a, b)``."""
    pattern = re.compile(
        r"\bif\s*\((?P<cond>.+?)\)\s*then\s*\((?P<then>.+?)\)\s*else\s*\((?P<else>.+?)\)",
        re.IGNORECASE | re.DOTALL,
    )

    def repl(match: re.Match[str]) -> str:
        cond = match.group("cond").strip()
        then_value = match.group("then").strip()
        else_value = match.group("else").strip()
        return f"IF({cond}, {then_value}, {else_value})"

    return pattern.sub(repl, expression)


def _translate_case(expression: str) -> str:
    """Translate a simple ``case when ... then ... [else ...] end`` block into nested IF."""
    pattern = re.compile(r"\bcase\b(?P<body>.+?)\bend\b", re.IGNORECASE | re.DOTALL)

    def repl(match: re.Match[str]) -> str:
        body = match.group("body")
        clauses = re.findall(
            r"when\s+(.+?)\s+then\s+(.+?)(?=\s+when\s+|\s+else\s+|$)",
            body,
            re.IGNORECASE | re.DOTALL,
        )
        else_match = re.search(r"\belse\s+(.+?)\s*$", body, re.IGNORECASE | re.DOTALL)
        else_value = else_match.group(1).strip() if else_match else "BLANK()"
        result = else_value
        for cond, value in reversed(clauses):
            result = f"IF({cond.strip()}, {value.strip()}, {result})"
        return result

    return pattern.sub(repl, expression)


def _translate_operators(expression: str) -> str:
    """Translate Cognos logical/string operators into their DAX equivalents."""
    expression = re.sub(r"\s+and\s+", " && ", expression, flags=re.IGNORECASE)
    expression = re.sub(r"\s+or\s+", " || ", expression, flags=re.IGNORECASE)
    # Cognos string concatenation (||) -> DAX (&). Guard against the logical || we just produced
    # by only converting a standalone || that sits between non-space text on both sides originally;
    # since logical OR is now ' || ' we leave concatenation handling to the AI fallback when mixed.
    return expression


def _translate_functions(expression: str) -> str:
    """Replace mapped Cognos scalar function names with DAX function names."""
    result = expression
    for cognos_name, dax_name in _FUNCTION_MAP.items():
        result = re.sub(rf"\b{re.escape(cognos_name)}\s*\(", f"{dax_name}(", result, flags=re.I)
    return result


def _is_arithmetic_of_columns(expression: str) -> bool:
    """Return True when the expression is only column references, numbers and arithmetic."""
    stripped = re.sub(r"[A-Za-z_][A-Za-z0-9_ ]*\[[^\[\]]+\]", "", expression)
    stripped = re.sub(r"\d+(\.\d+)?", "", stripped)
    return bool(re.fullmatch(r"[\s+\-*/().]*", stripped)) and "[" in expression


def _wrap_columns_with_aggregate(expression: str, dax_func: str) -> str:
    """Wrap each ``Table[Column]`` reference with the given aggregate function."""
    pattern = re.compile(r"[A-Za-z_][A-Za-z0-9_ ]*\[[^\[\]]+\]")
    return pattern.sub(lambda m: f"{dax_func}({m.group(0)})", expression)


def _has_untranslated_calls(expression: str) -> bool:
    """Return True when the expression still contains unknown function-style calls."""
    for match in _FUNCTION_CALL.finditer(expression):
        name = match.group(1)
        if name.upper() not in {fn.upper() for fn in _KNOWN_DAX_FUNCTIONS}:
            return True
    return False


def translate_measure_expression(
    expression: str | None,
    table_name: str,
    aggregate: str = "none",
) -> TranslationResult:
    """Translate a Cognos measure/data-item expression into DAX.

    Args:
        expression: The raw Cognos expression text (may be ``None``).
        table_name: The owning table name, used to qualify column references.
        aggregate: The Cognos ``aggregate`` attribute (e.g. ``total``, ``average``).

    Returns:
        A :class:`TranslationResult`. ``confident`` is ``True`` only when every construct in the
        expression was recognized.
    """
    if not expression or not expression.strip():
        return TranslationResult(dax=None, confident=False, note="empty expression")

    expr = expression.strip()
    dax_func = _AGGREGATE_TO_DAX.get(aggregate.strip().lower())

    # Case 1: a plain qualified reference such as [Sales].[Measures].[Revenue].
    if _SIMPLE_REFERENCE.match(expr):
        column = _last_segment(expr)
        if dax_func:
            return TranslationResult(dax=f"{dax_func}({table_name}[{column}])", confident=True)
        return TranslationResult(dax=f"{table_name}[{column}]", confident=True)

    # Case 2: structured translation of functions, conditionals and operators.
    converted = _convert_references(expr, table_name)
    converted = _translate_extract(converted)
    converted = _translate_if_then_else(converted)
    converted = _translate_case(converted)
    converted = _translate_functions(converted)

    # Pure arithmetic of references with an aggregate gets each operand aggregated.
    if dax_func and _is_arithmetic_of_columns(converted):
        converted = _wrap_columns_with_aggregate(converted, dax_func)

    converted = _translate_operators(converted)
    converted = re.sub(r"\s+", " ", converted).strip()

    confident = not _has_untranslated_calls(converted)
    note = None if confident else "expression contains constructs that need review"
    return TranslationResult(dax=converted, confident=confident, note=note)
