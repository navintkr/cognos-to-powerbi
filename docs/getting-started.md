# Getting started

This guide takes you from install to a generated Power BI Project.

## Prerequisites

- Python 3.10 or later.
- Power BI Desktop (to open the generated `.pbip`).
- Optional: an AI provider CLI (`claude`, `copilot`, or `codex`) for expression refinement.

## Install

From PyPI:

```bash
pip install cognos2powerbi
```

From source (recommended while the project is in preview):

```bash
git clone https://github.com/navintkr/cognos-to-powerbi.git
cd cognos-to-powerbi
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -e ".[dev,api]"
```

## Migrate a report

```bash
cognos2pbi migrate ./examples/sample_report.xml --out ./out/SalesReport
```

The command prints a summary and writes the project to `./out/SalesReport`:

```
out/SalesReport/
├── SalesReport.pbip
├── SalesReport.SemanticModel/
│   └── definition/
│       ├── model.tmdl
│       └── tables/Sales.tmdl
├── SalesReport.Report/
│   ├── definition.pbir
│   └── report.json
└── MIGRATION_REVIEW.md      (only when items need review)
```

Open `SalesReport.pbip` in Power BI Desktop.

## Refine with AI

Check that your provider CLI is reachable, then migrate with it enabled:

```bash
cognos2pbi doctor --ai claude
cognos2pbi migrate ./examples/sample_report.xml --out ./out/SalesReport --ai claude
```

## Review the output

Open `MIGRATION_REVIEW.md` for items that need attention, such as complex Cognos expressions
that need a DAX equivalent or visuals that need manual binding. Each row links the issue back to
the source construct.

## Next steps

- Replace the placeholder Power Query in each table partition with the real data source.
- Validate measures and relationships in Power BI Desktop.
- Publish to the Power BI / Microsoft Fabric service.
