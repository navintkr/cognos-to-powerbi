"""Generator that emits a Power BI Report Builder paginated report (.rdl) from the IR.

Report Builder consumes the RDL 2016 report-definition schema. The customer requirement for the
GM Financial migration is RDL output (a paginated report backed by a SQL dataset), not a PBIP
semantic model. RDL is a natural fit for the Cognos "list + letterhead" report style: static
letterhead text maps to native ``Textbox`` items and the Cognos list maps to a ``Tablix`` bound to
a SQL ``DataSet``.

The RDL 2016 schema is strict about element order and namespaces, so this generator matches a real
Report Builder-authored ``.rdl`` byte pattern rather than inventing its own layout. Anything that
cannot be produced deterministically (the physical source query, detail-filter WHERE clauses) is
emitted as SQL comments inside the dataset ``CommandText`` for a human to complete.
"""

from __future__ import annotations

import re
from pathlib import Path
from xml.sax.saxutils import escape

from cognos2powerbi.core.ir.models import (
    DataType,
    Measure,
    MigrationProject,
    ReportPage,
    Style,
    Table,
    TextBlock,
    Visual,
    VisualType,
)

_RDL_NS = "http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition"
_RD_NS = "http://schemas.microsoft.com/SQLServer/reporting/reportdesigner"

_HEADER_BG = "#005DAB"
_FONT = "Arial"

# Layout constants, in inches, matching the Report Builder sample.
_ROW_HEIGHT = 0.25
# The header row is taller than a data row so two-word column titles that wrap onto a second line
# (for example "Contract Purchaser ID") are not clipped in the Report Builder design/print view.
_HEADER_ROW_HEIGHT = 0.35
_TEXT_HEIGHT = 0.25
_LEFT_MARGIN = 0.25

# Column auto-sizing bounds (inches). Each column is widened to fit the longer of its header word
# and its field-name placeholder so data cells are not clipped horizontally in design view; the
# whole Tablix is then scaled to stay within the printable page width.
_MIN_COL_WIDTH = 0.9
_MAX_COL_WIDTH = 2.2
# Width budget for the Tablix: body width (7.5in) minus the Tablix left offset, with a small margin
# so rounded per-column widths never push the right edge past the printable page.
_PRINTABLE_WIDTH = 7.2
_CHAR_WIDTH = 0.085
_CELL_PADDING = 0.2

# IR data type -> RDL rd:TypeName (the .NET type Report Builder records for each field).
_RDL_TYPE = {
    DataType.STRING: "System.String",
    DataType.INT64: "System.Int64",
    DataType.DOUBLE: "System.Double",
    DataType.DECIMAL: "System.Decimal",
    DataType.BOOLEAN: "System.Boolean",
    DataType.DATE_TIME: "System.DateTime",
}

# Type-based default .NET format string used when the Cognos data item carries no explicit format.
# Dates render as a short date and numeric values get thousands grouping; strings are left raw.
_RDL_DEFAULT_FORMAT = {
    DataType.DATE_TIME: "d",
    DataType.DECIMAL: "#,##0.00",
    DataType.DOUBLE: "#,##0.00",
    DataType.INT64: "#,##0",
}


def _default_format(data_type: DataType) -> str | None:
    return _RDL_DEFAULT_FORMAT.get(data_type)


def _esc(text: str) -> str:
    """XML-escape text content."""
    return escape(text)


def _field_name(raw: str, used: set[str]) -> str:
    """Produce a unique VB-safe field identifier for use in ``=Fields!Name.Value``."""
    cleaned = re.sub(r"[^0-9A-Za-z_]", "", raw)
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"_{cleaned}"
    candidate = cleaned
    suffix = 1
    while candidate in used:
        suffix += 1
        candidate = f"{cleaned}{suffix}"
    used.add(candidate)
    return candidate


class RdlColumn:
    """A resolved report column: display header, field identifier, .NET type, and source styles."""

    def __init__(
        self,
        display: str,
        field: str,
        type_name: str,
        header_style: Style | None = None,
        cell_style: Style | None = None,
        value_format: str | None = None,
    ) -> None:
        self.display = display
        self.field = field
        self.type_name = type_name
        self.header_style = header_style
        self.cell_style = cell_style
        self.value_format = value_format


class RdlGenerator:
    """Render a migration project to a single ``.rdl`` paginated report on disk."""

    def generate(self, project: MigrationProject, out_dir: str | Path) -> Path:
        root = Path(out_dir)
        root.mkdir(parents=True, exist_ok=True)

        page, visual = self._select_list(project)
        table = self._lookup_table(project, visual)
        columns = self._resolve_columns(project, visual, table)
        dataset_name = f"{_safe_name(table)}DataSet" if table else "ReportDataSet"

        xml = self._render(project, page, columns, dataset_name, table_name=_safe_name(table))
        out_path = root / f"{_safe_file(project.name)}.rdl"
        out_path.write_text(xml, encoding="utf-8")
        return out_path

    # ------------------------------------------------------------------ selection

    @staticmethod
    def _select_list(project: MigrationProject) -> tuple[ReportPage | None, Visual | None]:
        """Return the first page and its first table/matrix visual (the Cognos list)."""
        for page in project.pages:
            for visual in page.visuals:
                if visual.visual_type in (VisualType.TABLE, VisualType.MATRIX):
                    return page, visual
        first_page = project.pages[0] if project.pages else None
        return first_page, None

    @staticmethod
    def _lookup_table(project: MigrationProject, visual: Visual | None) -> Table | None:
        if visual is None or not visual.fields:
            return project.tables[0] if project.tables else None
        target = visual.fields[0].table
        for table in project.tables:
            if table.name == target:
                return table
        return project.tables[0] if project.tables else None

    def _resolve_columns(
        self,
        project: MigrationProject,
        visual: Visual | None,
        table: Table | None,
    ) -> list[RdlColumn]:
        """Resolve the ordered report columns from the list visual (or the whole table)."""
        used: set[str] = set()
        columns: list[RdlColumn] = []
        if visual is not None and visual.fields:
            for field in visual.fields:
                col = table.column(field.name) if table else None
                measure = _find_measure(table, field.name) if table and col is None else None
                display = field.name
                data_type = col.data_type if col else DataType.STRING
                type_name = _RDL_TYPE.get(data_type, "System.String")
                source_format = (
                    col.format_string if col else (measure.format_string if measure else None)
                )
                columns.append(
                    RdlColumn(
                        display,
                        _field_name(field.name, used),
                        type_name,
                        header_style=field.header_style,
                        cell_style=field.cell_style,
                        value_format=source_format or _default_format(data_type),
                    )
                )
        elif table is not None:
            for col in table.columns:
                columns.append(
                    RdlColumn(
                        col.name,
                        _field_name(col.name, used),
                        _RDL_TYPE.get(col.data_type, "System.String"),
                        value_format=col.format_string or _default_format(col.data_type),
                    )
                )
        return columns

    # --------------------------------------------------------------------- render

    def _render(
        self,
        project: MigrationProject,
        page: ReportPage | None,
        columns: list[RdlColumn],
        dataset_name: str,
        table_name: str,
    ) -> str:
        header_blocks = list(page.header_blocks) if page else []
        footer_blocks = list(page.footer_blocks) if page else []

        parts: list[str] = []
        parts.append('<?xml version="1.0" encoding="utf-8"?>')
        parts.append(f'<Report xmlns="{_RDL_NS}" xmlns:rd="{_RD_NS}">')
        parts.append("  <AutoRefresh>0</AutoRefresh>")
        parts.append(self._data_sources())
        parts.append(self._data_sets(project, columns, dataset_name, table_name))
        parts.append(self._report_sections(header_blocks, footer_blocks, columns, dataset_name))
        parts.append("  <ReportParametersLayout>")
        parts.append("    <GridLayoutDefinition>")
        parts.append("      <NumberOfColumns>4</NumberOfColumns>")
        parts.append("      <NumberOfRows>2</NumberOfRows>")
        parts.append("    </GridLayoutDefinition>")
        parts.append("  </ReportParametersLayout>")
        parts.append("  <rd:ReportUnitType>Inch</rd:ReportUnitType>")
        parts.append("  <rd:ReportID>00000000-0000-0000-0000-000000000000</rd:ReportID>")
        parts.append("</Report>")
        return "\n".join(parts) + "\n"

    @staticmethod
    def _data_sources() -> str:
        return (
            "  <DataSources>\n"
            '    <DataSource Name="DataSource1">\n'
            "      <ConnectionProperties>\n"
            "        <DataProvider>SQL</DataProvider>\n"
            "        <ConnectString>Data Source=YOUR_SERVER;Initial Catalog=YOUR_DATABASE"
            "</ConnectString>\n"
            "      </ConnectionProperties>\n"
            "      <rd:SecurityType>Integrated</rd:SecurityType>\n"
            "      <rd:DataSourceID>00000000-0000-0000-0000-000000000000</rd:DataSourceID>\n"
            "    </DataSource>\n"
            "  </DataSources>"
        )

    def _data_sets(
        self,
        project: MigrationProject,
        columns: list[RdlColumn],
        dataset_name: str,
        table_name: str,
    ) -> str:
        command = self._command_text(project, columns, table_name)
        fields = []
        for col in columns:
            fields.append(
                f'        <Field Name="{_esc(col.field)}">\n'
                f"          <DataField>{_esc(col.field)}</DataField>\n"
                f"          <rd:TypeName>{col.type_name}</rd:TypeName>\n"
                "        </Field>"
            )
        fields_xml = "\n".join(fields) if fields else ""
        return (
            "  <DataSets>\n"
            f'    <DataSet Name="{_esc(dataset_name)}">\n'
            "      <Query>\n"
            "        <DataSourceName>DataSource1</DataSourceName>\n"
            f"        <CommandText>{_esc(command)}</CommandText>\n"
            "      </Query>\n"
            "      <Fields>\n"
            f"{fields_xml}\n"
            "      </Fields>\n"
            "    </DataSet>\n"
            "  </DataSets>"
        )

    @staticmethod
    def _command_text(project: MigrationProject, columns: list[RdlColumn], table_name: str) -> str:
        lines = [
            "-- TODO: point this query at the physical source for the Cognos report.",
            f"-- Cognos query: {table_name or 'unknown'}",
        ]
        filters = [
            flag.source_ref
            for flag in project.review_flags
            if flag.code == "detail-filter" and flag.source_ref
        ]
        if filters:
            lines.append("-- Cognos detail filters to translate into a WHERE clause:")
            lines.extend(f"--   {text}" for text in filters)
        select_cols = ",\n".join(f"    {col.field}" for col in columns) if columns else "    *"
        lines.append("SELECT")
        lines.append(select_cols)
        lines.append(f"FROM {table_name or 'YourTableName'}")
        return "\n".join(lines)

    def _report_sections(
        self,
        header_blocks: list[TextBlock],
        footer_blocks: list[TextBlock],
        columns: list[RdlColumn],
        dataset_name: str,
    ) -> str:
        items: list[str] = []
        used_names: set[str] = set()

        top = 0.1
        for index, block in enumerate(header_blocks):
            name = _unique(f"Header{index + 1}", used_names)
            items.append(
                self._textbox(name, block.text, top, _LEFT_MARGIN, 6.5, _TEXT_HEIGHT, block.style)
            )
            top += _TEXT_HEIGHT + 0.03

        tablix_top = top + 0.15
        tablix_height = _HEADER_ROW_HEIGHT + _ROW_HEIGHT
        if columns:
            widths = _column_widths(columns)
            items.append(self._tablix(columns, dataset_name, tablix_top, tablix_height, widths))
            top = tablix_top + tablix_height

        top += 0.35
        for index, block in enumerate(footer_blocks):
            name = _unique(f"Footer{index + 1}", used_names)
            items.append(
                self._textbox(name, block.text, top, _LEFT_MARGIN, 6.5, _TEXT_HEIGHT, block.style)
            )
            top += _TEXT_HEIGHT + 0.03

        body_height = max(top + 0.25, 4.0)
        items_xml = "\n".join(items)
        return (
            "  <ReportSections>\n"
            "    <ReportSection>\n"
            "      <Body>\n"
            "        <ReportItems>\n"
            f"{items_xml}\n"
            "        </ReportItems>\n"
            f"        <Height>{body_height:.2f}in</Height>\n"
            "        <Style />\n"
            "      </Body>\n"
            "      <Width>7.5in</Width>\n"
            "      <Page>\n"
            "        <PageHeight>11in</PageHeight>\n"
            "        <PageWidth>8.5in</PageWidth>\n"
            "        <LeftMargin>0.5in</LeftMargin>\n"
            "        <RightMargin>0.5in</RightMargin>\n"
            "        <TopMargin>0.5in</TopMargin>\n"
            "        <BottomMargin>0.5in</BottomMargin>\n"
            "        <Style />\n"
            "      </Page>\n"
            "    </ReportSection>\n"
            "  </ReportSections>"
        )

    @staticmethod
    def _textbox(
        name: str,
        value: str,
        top: float,
        left: float,
        width: float,
        height: float,
        style: Style | None = None,
    ) -> str:
        """Build a free-standing letterhead textbox, honoring the font/size/color Cognos set."""
        return _textbox_xml(
            name=name,
            value=value,
            family=_family(style),
            size_pt=style.font_size_pt if style else None,
            bold=bool(style and style.bold),
            italic=bool(style and style.italic),
            color=style.color if style else None,
            underline=bool(style and style.underline),
            align=style.text_align if style else None,
            top=top,
            left=left,
            width=width,
            height=height,
            indent=10,
        )

    def _tablix(
        self,
        columns: list[RdlColumn],
        dataset_name: str,
        top: float,
        height: float,
        widths: list[float],
    ) -> str:
        tablix_columns = "\n".join(
            "              <TablixColumn>\n"
            f"                <Width>{w:.2f}in</Width>\n"
            "              </TablixColumn>"
            for w in widths
        )
        header_cells = "\n".join(self._header_cell(col) for col in columns)
        data_cells = "\n".join(self._data_cell(col) for col in columns)
        column_members = "\n".join("                <TablixMember />" for _ in columns)
        width = sum(widths)
        return (
            '          <Tablix Name="ReportTablix">\n'
            "            <TablixBody>\n"
            "              <TablixColumns>\n"
            f"{tablix_columns}\n"
            "              </TablixColumns>\n"
            "              <TablixRows>\n"
            "                <TablixRow>\n"
            f"                  <Height>{_HEADER_ROW_HEIGHT:.2f}in</Height>\n"
            "                  <TablixCells>\n"
            f"{header_cells}\n"
            "                  </TablixCells>\n"
            "                </TablixRow>\n"
            "                <TablixRow>\n"
            f"                  <Height>{_ROW_HEIGHT:.2f}in</Height>\n"
            "                  <TablixCells>\n"
            f"{data_cells}\n"
            "                  </TablixCells>\n"
            "                </TablixRow>\n"
            "              </TablixRows>\n"
            "            </TablixBody>\n"
            "            <TablixColumnHierarchy>\n"
            "              <TablixMembers>\n"
            f"{column_members}\n"
            "              </TablixMembers>\n"
            "            </TablixColumnHierarchy>\n"
            "            <TablixRowHierarchy>\n"
            "              <TablixMembers>\n"
            "                <TablixMember>\n"
            "                  <KeepWithGroup>After</KeepWithGroup>\n"
            "                </TablixMember>\n"
            "                <TablixMember>\n"
            '                  <Group Name="Details" />\n'
            "                </TablixMember>\n"
            "              </TablixMembers>\n"
            "            </TablixRowHierarchy>\n"
            f"            <DataSetName>{_esc(dataset_name)}</DataSetName>\n"
            f"            <Top>{top:.2f}in</Top>\n"
            f"            <Left>{_LEFT_MARGIN:.2f}in</Left>\n"
            f"            <Height>{height:.2f}in</Height>\n"
            f"            <Width>{width:.2f}in</Width>\n"
            "          </Tablix>"
        )

    @staticmethod
    def _header_cell(col: RdlColumn) -> str:
        """Header cell: keep the branded blue treatment as the default, overlay any source style."""
        style = col.header_style
        textbox = _textbox_xml(
            name=f"{col.field}Header",
            value=col.display,
            family=_family(style),
            size_pt=style.font_size_pt if style else None,
            bold=True if style is None else (style.bold or True),
            italic=bool(style and style.italic),
            color=(style.color if style and style.color else "White"),
            underline=bool(style and style.underline),
            align=(style.text_align if style and style.text_align else "Center"),
            background=(style.background_color if style and style.background_color else _HEADER_BG),
            vertical_align="Middle",
            border_style="Solid",
            border_color="White",
            indent=24,
        )
        return (
            "                    <TablixCell>\n"
            "                      <CellContents>\n"
            f"{textbox}\n"
            "                      </CellContents>\n"
            "                    </TablixCell>"
        )

    @staticmethod
    def _data_cell(col: RdlColumn) -> str:
        """Data cell: bind the field and carry the source font/alignment through."""
        style = col.cell_style
        textbox = _textbox_xml(
            name=col.field,
            value=f"=Fields!{col.field}.Value",
            family=_family(style),
            size_pt=style.font_size_pt if style else None,
            bold=bool(style and style.bold),
            italic=bool(style and style.italic),
            color=style.color if style else None,
            underline=bool(style and style.underline),
            align=style.text_align if style else None,
            value_format=col.value_format,
            background=style.background_color if style else None,
            border_style="Solid",
            indent=24,
        )
        return (
            "                    <TablixCell>\n"
            "                      <CellContents>\n"
            f"{textbox}\n"
            "                      </CellContents>\n"
            "                    </TablixCell>"
        )


def _unique(base: str, used: set[str]) -> str:
    candidate = base
    suffix = 1
    while candidate in used:
        suffix += 1
        candidate = f"{base}{suffix}"
    used.add(candidate)
    return candidate


def _fmt_pt(size_pt: float) -> str:
    return f"{size_pt:g}pt"


def _family(style: Style | None) -> str:
    """Return the source font family, falling back to the default when none was specified."""
    if style and style.font_family:
        return style.font_family
    return _FONT


def _textbox_xml(
    *,
    name: str,
    value: str,
    family: str,
    size_pt: float | None = None,
    bold: bool = False,
    italic: bool = False,
    color: str | None = None,
    underline: bool = False,
    align: str | None = None,
    value_format: str | None = None,
    background: str | None = None,
    vertical_align: str | None = None,
    border_style: str = "None",
    border_color: str | None = None,
    top: float | None = None,
    left: float | None = None,
    width: float | None = None,
    height: float | None = None,
    indent: int,
) -> str:
    """Build a Report Builder ``<Textbox>`` element with run, paragraph, and box-level styles.

    A ``top``/``left``/``width``/``height`` set positions a free-standing (letterhead) textbox; when
    omitted the textbox is a Tablix cell that inherits its cell geometry. Whitespace between RDL
    elements is insignificant, so a single indent base keeps the builder readable.
    """
    p = " " * indent
    run: list[str] = [f"{p}      <FontFamily>{_esc(family)}</FontFamily>"]
    if size_pt:
        run.append(f"{p}      <FontSize>{_fmt_pt(size_pt)}</FontSize>")
    if bold:
        run.append(f"{p}      <FontWeight>Bold</FontWeight>")
    if italic:
        run.append(f"{p}      <FontStyle>Italic</FontStyle>")
    if color:
        run.append(f"{p}      <Color>{_esc(color)}</Color>")
    if underline:
        run.append(f"{p}      <TextDecoration>Underline</TextDecoration>")
    if value_format:
        run.append(f"{p}      <Format>{_esc(value_format)}</Format>")
    paragraph_style = (
        f"{p}        <Style>\n{p}          <TextAlign>{align}</TextAlign>\n{p}        </Style>"
        if align
        else f"{p}        <Style />"
    )
    box: list[str] = []
    if background:
        box.append(f"{p}    <BackgroundColor>{_esc(background)}</BackgroundColor>")
    if vertical_align:
        box.append(f"{p}    <VerticalAlign>{vertical_align}</VerticalAlign>")
    box.append(f"{p}    <Border>")
    if border_color:
        box.append(f"{p}      <Color>{_esc(border_color)}</Color>")
    box.append(f"{p}      <Style>{border_style}</Style>")
    box.append(f"{p}    </Border>")
    position: list[str] = []
    if top is not None:
        position.append(f"{p}  <Top>{top:.2f}in</Top>")
    if left is not None:
        position.append(f"{p}  <Left>{left:.2f}in</Left>")
    if height is not None:
        position.append(f"{p}  <Height>{height:.2f}in</Height>")
    if width is not None:
        position.append(f"{p}  <Width>{width:.2f}in</Width>")
    lines = [
        f'{p}<Textbox Name="{_esc(name)}">',
        f"{p}  <CanGrow>true</CanGrow>",
        f"{p}  <KeepTogether>true</KeepTogether>",
        f"{p}  <Paragraphs>",
        f"{p}    <Paragraph>",
        f"{p}      <TextRuns>",
        f"{p}        <TextRun>",
        f"{p}          <Value>{_esc(value)}</Value>",
        f"{p}          <Style>",
        *run,
        f"{p}          </Style>",
        f"{p}        </TextRun>",
        f"{p}      </TextRuns>",
        paragraph_style,
        f"{p}    </Paragraph>",
        f"{p}  </Paragraphs>",
        f"{p}  <rd:DefaultName>{_esc(name)}</rd:DefaultName>",
        *position,
        f"{p}  <Style>",
        *box,
        f"{p}  </Style>",
        f"{p}</Textbox>",
    ]
    return "\n".join(lines)


def _column_widths(columns: list[RdlColumn]) -> list[float]:
    """Size each column to its content so data cells are not clipped, then fit the printable page.

    The width is driven by the longer of the header's longest single word (headers wrap on spaces)
    and the field-name placeholder shown in the design view. Each width is clamped to a sensible
    range; if the row is wider than the printable page it is scaled down proportionally so the whole
    Tablix still fits.
    """
    raw: list[float] = []
    for col in columns:
        longest_word = max((len(word) for word in col.display.split()), default=len(col.display))
        # The design-view placeholder renders as "[FieldName]" (field name plus two brackets).
        placeholder_len = len(col.field) + 2
        chars = max(longest_word, placeholder_len)
        width = chars * _CHAR_WIDTH + _CELL_PADDING
        raw.append(max(_MIN_COL_WIDTH, min(_MAX_COL_WIDTH, width)))
    total = sum(raw)
    if total > _PRINTABLE_WIDTH:
        scale = _PRINTABLE_WIDTH / total
        raw = [width * scale for width in raw]
    return raw


def _safe_name(table: Table | None) -> str:
    if table is None:
        return ""
    return re.sub(r"[^0-9A-Za-z_]", "", table.name) or "Table"


def _find_measure(table: Table, name: str) -> Measure | None:
    """Return the measure with the given name from a table, if present."""
    for measure in table.measures:
        if measure.name == name:
            return measure
    return None


def _safe_file(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]', "_", name).strip().rstrip(".")
    return cleaned or "report"


def generate_rdl(project: MigrationProject, out_dir: str | Path) -> Path:
    """Generate a Report Builder ``.rdl`` paginated report from a migration project."""
    return RdlGenerator().generate(project, out_dir)
