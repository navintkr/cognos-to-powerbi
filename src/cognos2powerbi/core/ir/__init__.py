"""Vendor-neutral intermediate representation (IR).

The IR decouples Cognos parsing from Power BI generation. Parsers populate the IR from a
source artifact; generators read the IR to emit Power BI Project output. New input formats
and output formats can therefore be added independently.
"""

from cognos2powerbi.core.ir.models import (
    Column,
    DataType,
    Measure,
    MigrationProject,
    Relationship,
    ReportPage,
    ReviewFlag,
    Severity,
    Table,
    Visual,
    VisualField,
    VisualType,
)

__all__ = [
    "Column",
    "DataType",
    "Measure",
    "MigrationProject",
    "Relationship",
    "ReportPage",
    "ReviewFlag",
    "Severity",
    "Table",
    "Visual",
    "VisualField",
    "VisualType",
]
