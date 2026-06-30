"""Pydantic models that define the vendor-neutral intermediate representation (IR)."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class DataType(str, Enum):
    """Power BI / TMDL column data types."""

    STRING = "string"
    INT64 = "int64"
    DOUBLE = "double"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    DATE_TIME = "dateTime"

    @classmethod
    def from_cognos(cls, cognos_type: str | None) -> DataType:
        """Map a Cognos data-item usage/datatype hint to a TMDL data type."""
        if not cognos_type:
            return cls.STRING
        value = cognos_type.strip().lower()
        # Strip any precision/length suffix, for example "decimal(18,2)" or "varchar(50)".
        base = value.split("(", 1)[0].strip()
        if base in {"date", "datetime", "datetime2", "smalldatetime", "timestamp", "time"}:
            return cls.DATE_TIME
        if base in {"bool", "boolean", "bit"}:
            return cls.BOOLEAN
        if base in {"decimal", "numeric", "money", "smallmoney", "currency"}:
            return cls.DECIMAL
        if base in {"double", "float", "float64", "real", "number"}:
            return cls.DOUBLE
        if "int" in base or base in {"long", "short", "byte", "serial"}:
            return cls.INT64
        return cls.STRING


class Severity(str, Enum):
    """Severity of a manual-review flag raised during migration."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class VisualType(str, Enum):
    """Normalized Power BI visual types."""

    TABLE = "tableEx"
    MATRIX = "pivotTable"
    COLUMN_CHART = "columnChart"
    BAR_CHART = "barChart"
    LINE_CHART = "lineChart"
    PIE_CHART = "pieChart"
    CARD = "card"
    UNKNOWN = "tableEx"


class DataSourceKind(str, Enum):
    """Supported physical data sources for the generated Power BI model."""

    SQL_SERVER = "sqlServer"
    NONE = "none"


class TableRole(str, Enum):
    """The role a table plays in a star schema."""

    FACT = "fact"
    DIMENSION = "dimension"
    DATE = "date"
    BRIDGE = "bridge"
    UNKNOWN = "unknown"


class Cardinality(str, Enum):
    """Relationship cardinality, named so the value maps onto TMDL endpoints.

    A relationship in TMDL is oriented from the ``from`` (many) side to the ``to`` (one) side.
    ``MANY_TO_ONE`` is the Power BI default and needs no explicit cardinality tokens.
    """

    MANY_TO_ONE = "manyToOne"
    ONE_TO_MANY = "oneToMany"
    ONE_TO_ONE = "oneToOne"
    MANY_TO_MANY = "manyToMany"


class CrossFilterDirection(str, Enum):
    """Cross-filter direction for a relationship (TMDL crossFilteringBehavior)."""

    SINGLE = "oneDirection"
    BOTH = "bothDirections"


class ReviewFlag(BaseModel):
    """A migration item that needs human or AI review."""

    code: str
    message: str
    severity: Severity = Severity.WARNING
    source_ref: str | None = None


class Column(BaseModel):
    """A column in a semantic-model table."""

    name: str
    data_type: DataType = DataType.STRING
    source_column: str | None = None
    cognos_expression: str | None = None
    is_hidden: bool = False
    is_key: bool = False
    is_foreign_key: bool = False
    summarize_by: str | None = None
    data_category: str | None = None


class Measure(BaseModel):
    """A measure (aggregated calculation) in a semantic-model table."""

    name: str
    dax_expression: str | None = None
    cognos_expression: str | None = None
    format_string: str | None = None
    needs_review: bool = False


class Table(BaseModel):
    """A semantic-model table derived from a Cognos query."""

    name: str
    source_query: str | None = None
    columns: list[Column] = Field(default_factory=list)
    measures: list[Measure] = Field(default_factory=list)
    role: TableRole = TableRole.UNKNOWN
    data_category: str | None = None
    is_date_table: bool = False

    def column(self, name: str) -> Column | None:
        """Return the column with the given name, or ``None``."""
        for col in self.columns:
            if col.name == name:
                return col
        return None


class Relationship(BaseModel):
    """A relationship between two tables.

    The relationship is oriented so ``from`` is the many side and ``to`` is the one side,
    matching how Power BI / TMDL serialize a single-column relationship.
    """

    from_table: str
    from_column: str
    to_table: str
    to_column: str
    is_active: bool = True
    name: str | None = None
    cardinality: Cardinality = Cardinality.MANY_TO_ONE
    cross_filter: CrossFilterDirection = CrossFilterDirection.SINGLE


class DataSource(BaseModel):
    """Physical data source used to populate the generated semantic model.

    Cognos report specifications reference a logical model, not a physical connection, so the
    generator emits a parameterized Power Query that the user points at their own database. When
    the kind is ``NONE`` the generator emits empty placeholder tables instead.
    """

    kind: DataSourceKind = DataSourceKind.SQL_SERVER
    server: str = "localhost"
    database: str = "AdventureWorks"
    schema_name: str = "dbo"


class VisualField(BaseModel):
    """A field bound to a visual role (for example rows, values, category)."""

    table: str
    name: str
    role: str = "values"


class Visual(BaseModel):
    """A visual placed on a report page."""

    title: str | None = None
    visual_type: VisualType = VisualType.TABLE
    fields: list[VisualField] = Field(default_factory=list)
    x: float = 0.0
    y: float = 0.0
    width: float = 480.0
    height: float = 320.0


class ReportPage(BaseModel):
    """A page in the target Power BI report."""

    name: str
    display_name: str
    visuals: list[Visual] = Field(default_factory=list)


class MigrationProject(BaseModel):
    """The complete migration unit produced by parsers and consumed by generators."""

    name: str
    source_path: str | None = None
    data_source: DataSource = Field(default_factory=DataSource)
    tables: list[Table] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)
    pages: list[ReportPage] = Field(default_factory=list)
    review_flags: list[ReviewFlag] = Field(default_factory=list)

    def add_flag(
        self,
        code: str,
        message: str,
        severity: Severity = Severity.WARNING,
        source_ref: str | None = None,
    ) -> None:
        """Record a manual-review flag on the project."""
        self.review_flags.append(
            ReviewFlag(code=code, message=message, severity=severity, source_ref=source_ref)
        )
