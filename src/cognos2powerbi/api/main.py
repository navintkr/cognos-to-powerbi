"""FastAPI application exposing the Cognos to Power BI migration engine.

This is the SaaS surface. It accepts Cognos source artifacts (report specifications, Framework
Manager models, data modules, and dashboards), runs the migration, and returns the generated Power
BI Project as a zip archive plus a JSON summary of review items. It also supports analyzing a file
for review before download, and batch migration of many files with a coverage report.

Run locally:

    pip install -e ".[api]"
    uvicorn cognos2powerbi.api.main:app --reload
"""

from __future__ import annotations

import io
import tempfile
import zipfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from cognos2powerbi import __version__
from cognos2powerbi.core.batch import run_batch_migration
from cognos2powerbi.core.detect import detect_source_kind
from cognos2powerbi.core.pipeline import (
    MigrationResult,
    run_auto_migration,
    run_dashboard_migration,
    run_migration,
    run_model_migration,
    run_module_migration,
)

app = FastAPI(
    title="Cognos to Power BI Migration API",
    version=__version__,
    description="Convert IBM Cognos reports, models, data modules, and dashboards to Power BI.",
)

_MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB per file
_MAX_BATCH_FILES = 50
_ALLOWED_PROVIDERS = {"claude", "copilot", "codex", "none"}
_ALLOWED_KINDS = {"auto", "report", "model", "module", "dashboard"}
_KIND_RUNNERS = {
    "report": run_migration,
    "model": run_model_migration,
    "module": run_module_migration,
    "dashboard": run_dashboard_migration,
    "auto": run_auto_migration,
}
_WEB_DIR = Path(__file__).resolve().parents[3] / "web"

if _WEB_DIR.is_dir():
    app.mount("/app", StaticFiles(directory=str(_WEB_DIR), html=True), name="app")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        """Serve the single-page web frontend."""
        return FileResponse(str(_WEB_DIR / "index.html"))


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok", "version": __version__}


def _validated_provider(ai: str) -> str:
    provider = ai.strip().lower()
    if provider not in _ALLOWED_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unsupported AI provider: {ai}")
    return provider


def _validated_kind(kind: str) -> str:
    value = kind.strip().lower()
    if value not in _ALLOWED_KINDS:
        raise HTTPException(status_code=400, detail=f"Unsupported source kind: {kind}")
    return value


def _read_payload(payload: bytes) -> bytes:
    if not payload:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(payload) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Uploaded file exceeds the size limit.")
    return payload


def _run_one(
    payload: bytes, filename: str, kind: str, provider: str, work_dir: Path
) -> MigrationResult:
    source = work_dir / (filename or "source")
    source.write_bytes(payload)
    out_dir = work_dir / "out"
    runner = _KIND_RUNNERS[kind]
    try:
        return runner(source, out_dir, ai=provider)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/v1/migrate")
async def migrate(
    file: UploadFile = File(..., description="Cognos source artifact."),
    ai: str = Form("none", description="AI provider: claude, copilot, codex, or none."),
    kind: str = Form("auto", description="Source kind: auto, report, model, module, dashboard."),
) -> StreamingResponse:
    """Migrate an uploaded Cognos source and stream back the PBIP as a zip archive."""
    provider = _validated_provider(ai)
    source_kind = _validated_kind(kind)
    payload = _read_payload(await file.read())

    with tempfile.TemporaryDirectory() as work:
        work_dir = Path(work)
        result = _run_one(payload, file.filename or "source", source_kind, provider, work_dir)
        archive = _zip_directory(work_dir / "out")

    headers = {
        "Content-Disposition": f'attachment; filename="{result.project_name}.pbip.zip"',
        "X-Migration-Kind": result.source_kind,
        "X-Migration-Tables": str(result.table_count),
        "X-Migration-Measures": str(result.measure_count),
        "X-Migration-Pages": str(result.page_count),
        "X-Migration-Review-Items": str(result.review_flag_count),
        "X-Migration-AI-Provider": result.ai_provider,
    }
    return StreamingResponse(archive, media_type="application/zip", headers=headers)


@app.post("/api/v1/analyze")
async def analyze(
    file: UploadFile = File(..., description="Cognos source artifact."),
    kind: str = Form("auto", description="Source kind: auto, report, model, module, dashboard."),
) -> JSONResponse:
    """Migrate without returning artifacts; respond with a JSON summary and review items."""
    source_kind = _validated_kind(kind)
    payload = _read_payload(await file.read())
    detected = detect_source_kind(payload, filename=file.filename)

    with tempfile.TemporaryDirectory() as work:
        work_dir = Path(work)
        result = _run_one(payload, file.filename or "source", source_kind, "none", work_dir)

    body = result.model_dump()
    body["detected_kind"] = detected.value
    return JSONResponse(body)


@app.post("/api/v1/batch")
async def batch(
    files: list[UploadFile] = File(..., description="Multiple Cognos source artifacts."),
    ai: str = Form("none", description="AI provider: claude, copilot, codex, or none."),
) -> StreamingResponse:
    """Migrate many uploaded Cognos sources; return a zip of all projects plus a coverage report."""
    provider = _validated_provider(ai)
    if not files:
        raise HTTPException(status_code=400, detail="No files were uploaded.")
    if len(files) > _MAX_BATCH_FILES:
        raise HTTPException(
            status_code=413, detail=f"Too many files; the limit is {_MAX_BATCH_FILES}."
        )

    with tempfile.TemporaryDirectory() as work:
        work_dir = Path(work)
        inbox = work_dir / "in"
        inbox.mkdir(parents=True, exist_ok=True)
        sources: list[Path] = []
        for index, upload in enumerate(files):
            payload = _read_payload(await upload.read())
            name = upload.filename or f"source_{index}"
            target = inbox / Path(name).name
            target.write_bytes(payload)
            sources.append(target)

        out_dir = work_dir / "out"
        run_batch_migration([str(path) for path in sources], out_dir, ai=provider)
        archive = _zip_directory(out_dir)

    headers = {
        "Content-Disposition": 'attachment; filename="cognos-migration-batch.zip"',
        "X-Migration-Batch-Files": str(len(files)),
    }
    return StreamingResponse(archive, media_type="application/zip", headers=headers)


def _zip_directory(directory: Path) -> io.BytesIO:
    """Zip a directory tree into an in-memory buffer."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in directory.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(directory))
    buffer.seek(0)
    return buffer
