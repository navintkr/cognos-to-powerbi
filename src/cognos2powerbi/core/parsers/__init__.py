"""Parsers that read Cognos source artifacts into the intermediate representation."""

from cognos2powerbi.core.parsers.report_parser import CognosReportParser, parse_report

__all__ = ["CognosReportParser", "parse_report"]
