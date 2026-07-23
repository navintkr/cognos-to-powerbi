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
    MigrationProject,
    ReportPage,
    Table,
    Visual,
    VisualType,
)

_RDL_NS = "http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition"
_RD_NS = "http://schemas.microsoft.com/SQLServer/reporting/reportdesigner"

_HEADER_BG = "#005DAB"
_FONT = "Arial"

# Layout constants, in inches, matching the Report Builder sample.
_COL_WIDTH = 1.2
_ROW_HEIGHT = 0.25
_TEXT_HEIGHT = 0.25
_LEFT_MARGIN = 0.25

# IR data type -> RDL rd:TypeName (the .NET type Report Builder records for each field).
_RDL_TYPE = {
    DataType.STRING: "System.String",
    DataType.INT64: "System.Int64",
    DataType.DOUBLE: "System.Double",
    DataType.DECIMAL: "System.Decimal",
    DataType.BOOLEAN: "System.Boolean",
    DataType.DATE_TIME: "System.DateTime",
}


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
    """A resolved report column: display header, field identifier, and .NET type."""

    def __init__(self, display: str, field: str, type_name: str) -> None:
        self.display = display
        self.field = field
        self.type_name = type_name


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
                display = field.name
                type_name = _RDL_TYPE.get(
                    col.data_type if col else DataType.STRING, "System.String"
                )
                columns.append(RdlColumn(display, _field_name(field.name, used), type_name))
        elif table is not None:
            for col in table.columns:
                columns.append(
                    RdlColumn(
                        col.name,
                        _field_name(col.name, used),
                        _RDL_TYPE.get(col.data_type, "System.String"),
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
        header_texts = list(page.header_texts) if page else []
        footer_texts = list(page.footer_texts) if page else []

        parts: list[str] = []
        parts.append('<?xml version="1.0" encoding="utf-8"?>')
        parts.append(f'<Report xmlns="{_RDL_NS}" xmlns:rd="{_RD_NS}">')
        parts.append("  <AutoRefresh>0</AutoRefresh>")
        parts.append(self._data_sources())
        parts.append(self._data_sets(project, columns, dataset_name, table_name))
        parts.append(self._report_sections(header_texts, footer_texts, columns, dataset_name))
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
        header_texts: list[str],
        footer_texts: list[str],
        columns: list[RdlColumn],
        dataset_name: str,
    ) -> str:
        items: list[str] = []
        used_names: set[str] = set()

        top = 0.1
        for index, text in enumerate(header_texts):
            name = _unique(f"Header{index + 1}", used_names)
            items.append(self._textbox(name, text, top, _LEFT_MARGIN, 6.5, _TEXT_HEIGHT))
            top += _TEXT_HEIGHT + 0.03

        tablix_top = top + 0.15
        tablix_height = _ROW_HEIGHT * 2
        if columns:
            items.append(self._tablix(columns, dataset_name, tablix_top, tablix_height))
            top = tablix_top + tablix_height

        top += 0.35
        for index, text in enumerate(footer_texts):
            name = _unique(f"Footer{index + 1}", used_names)
            items.append(self._textbox(name, text, top, _LEFT_MARGIN, 6.5, _TEXT_HEIGHT))
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
        name: str, value: str, top: float, left: float, width: float, height: float
    ) -> str:
        return (
            f'          <Textbox Name="{_esc(name)}">\n'
            "            <CanGrow>true</CanGrow>\n"
            "            <KeepTogether>true</KeepTogether>\n"
            "            <Paragraphs>\n"
            "              <Paragraph>\n"
            "                <TextRuns>\n"
            "                  <TextRun>\n"
            f"                    <Value>{_esc(value)}</Value>\n"
            "                    <Style>\n"
            f"                      <FontFamily>{_FONT}</FontFamily>\n"
            "                    </Style>\n"
            "                  </TextRun>\n"
            "                </TextRuns>\n"
            "                <Style />\n"
            "              </Paragraph>\n"
            "            </Paragraphs>\n"
            f"            <rd:DefaultName>{_esc(name)}</rd:DefaultName>\n"
            f"            <Top>{top:.2f}in</Top>\n"
            f"            <Left>{left:.2f}in</Left>\n"
            f"            <Height>{height:.2f}in</Height>\n"
            f"            <Width>{width:.2f}in</Width>\n"
            "            <Style>\n"
            "              <Border>\n"
            "                <Style>None</Style>\n"
            "              </Border>\n"
            "            </Style>\n"
            "          </Textbox>"
        )

    def _tablix(
        self, columns: list[RdlColumn], dataset_name: str, top: float, height: float
    ) -> str:
        n = len(columns)
        tablix_columns = "\n".join(
            f"              <TablixColumn>\n"
            f"                <Width>{_COL_WIDTH:.1f}in</Width>\n"
            f"              </TablixColumn>"
            for _ in columns
        )
        header_cells = "\n".join(self._header_cell(col) for col in columns)
        data_cells = "\n".join(self._data_cell(col) for col in columns)
        column_members = "\n".join("                <TablixMember />" for _ in columns)
        width = n * _COL_WIDTH
        return (
            '          <Tablix Name="ReportTablix">\n'
            "            <TablixBody>\n"
            "              <TablixColumns>\n"
            f"{tablix_columns}\n"
            "              </TablixColumns>\n"
            "              <TablixRows>\n"
            "                <TablixRow>\n"
            f"                  <Height>{_ROW_HEIGHT:.2f}in</Height>\n"
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
            f"            <Width>{width:.1f}in</Width>\n"
            "          </Tablix>"
        )

    @staticmethod
    def _header_cell(col: RdlColumn) -> str:
        name = f"{col.field}Header"
        return (
            "                    <TablixCell>\n"
            "                      <CellContents>\n"
            f'                        <Textbox Name="{_esc(name)}">\n'
            "                          <CanGrow>true</CanGrow>\n"
            "                          <KeepTogether>true</KeepTogether>\n"
            "                          <Paragraphs>\n"
            "                            <Paragraph>\n"
            "                              <TextRuns>\n"
            "                                <TextRun>\n"
            f"                                  <Value>{_esc(col.display)}</Value>\n"
            "                                  <Style>\n"
            f"                                    <FontFamily>{_FONT}</FontFamily>\n"
            "                                    <FontWeight>Bold</FontWeight>\n"
            "                                    <Color>White</Color>\n"
            "                                  </Style>\n"
            "                                </TextRun>\n"
            "                              </TextRuns>\n"
            "                              <Style>\n"
            "                                <TextAlign>Center</TextAlign>\n"
            "                              </Style>\n"
            "                            </Paragraph>\n"
            "                          </Paragraphs>\n"
            f"                          <rd:DefaultName>{_esc(name)}</rd:DefaultName>\n"
            "                          <Style>\n"
            f"                            <BackgroundColor>{_HEADER_BG}</BackgroundColor>\n"
            "                            <VerticalAlign>Middle</VerticalAlign>\n"
            "                            <Border>\n"
            "                              <Color>White</Color>\n"
            "                              <Style>Solid</Style>\n"
            "                            </Border>\n"
            "                          </Style>\n"
            "                        </Textbox>\n"
            "                      </CellContents>\n"
            "                    </TablixCell>"
        )

    @staticmethod
    def _data_cell(col: RdlColumn) -> str:
        return (
            "                    <TablixCell>\n"
            "                      <CellContents>\n"
            f'                        <Textbox Name="{_esc(col.field)}">\n'
            "                          <CanGrow>true</CanGrow>\n"
            "                          <KeepTogether>true</KeepTogether>\n"
            "                          <Paragraphs>\n"
            "                            <Paragraph>\n"
            "                              <TextRuns>\n"
            "                                <TextRun>\n"
            f"                                  <Value>=Fields!{_esc(col.field)}.Value</Value>\n"
            "                                  <Style>\n"
            f"                                    <FontFamily>{_FONT}</FontFamily>\n"
            "                                  </Style>\n"
            "                                </TextRun>\n"
            "                              </TextRuns>\n"
            "                              <Style />\n"
            "                            </Paragraph>\n"
            "                          </Paragraphs>\n"
            f"                          <rd:DefaultName>{_esc(col.field)}</rd:DefaultName>\n"
            "                          <Style>\n"
            "                            <Border>\n"
            "                              <Style>Solid</Style>\n"
            "                            </Border>\n"
            "                          </Style>\n"
            "                        </Textbox>\n"
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


def _safe_name(table: Table | None) -> str:
    if table is None:
        return ""
    return re.sub(r"[^0-9A-Za-z_]", "", table.name) or "Table"


def _safe_file(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]', "_", name).strip().rstrip(".")
    return cleaned or "report"


def generate_rdl(project: MigrationProject, out_dir: str | Path) -> Path:
    """Generate a Report Builder ``.rdl`` paginated report from a migration project."""
    return RdlGenerator().generate(project, out_dir)
