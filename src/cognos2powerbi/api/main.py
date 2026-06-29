"""FastAPI application exposing the Cognos to Power BI migration engine.

This is the SaaS surface. It accepts a Cognos report specification, runs the migration, and
returns the generated Power BI Project as a zip archive plus a JSON summary of review items.

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
from cognos2powerbi.core.pipeline import run_migration

app = FastAPI(
    title="Cognos to Power BI Migration API",
    version=__version__,
    description="Convert IBM Cognos reports and models to Microsoft Power BI (PBIP).",
)

_MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB
_ALLOWED_PROVIDERS = {"claude", "copilot", "codex", "none"}
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


@app.post("/api/v1/migrate")
async def migrate(
    file: UploadFile = File(..., description="Cognos report specification XML."),
    ai: str = Form("none", description="AI provider: claude, copilot, codex, or none."),
) -> StreamingResponse:
    """Migrate an uploaded Cognos report and stream back the PBIP as a zip archive."""
    provider = ai.strip().lower()
    if provider not in _ALLOWED_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unsupported AI provider: {ai}")

    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(payload) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Uploaded file exceeds the size limit.")

    with tempfile.TemporaryDirectory() as work:
        work_dir = Path(work)
        source = work_dir / (file.filename or "report.xml")
        source.write_bytes(payload)
        out_dir = work_dir / "out"
        try:
            result = run_migration(source, out_dir, ai=provider)
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        archive = _zip_directory(out_dir)

    headers = {
        "Content-Disposition": f'attachment; filename="{result.project_name}.pbip.zip"',
        "X-Migration-Tables": str(result.table_count),
        "X-Migration-Measures": str(result.measure_count),
        "X-Migration-Review-Items": str(result.review_flag_count),
        "X-Migration-AI-Provider": result.ai_provider,
    }
    return StreamingResponse(archive, media_type="application/zip", headers=headers)


@app.post("/api/v1/analyze")
async def analyze(
    file: UploadFile = File(..., description="Cognos report specification XML."),
) -> JSONResponse:
    """Migrate without returning artifacts; respond with a JSON summary only."""
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    with tempfile.TemporaryDirectory() as work:
        work_dir = Path(work)
        source = work_dir / (file.filename or "report.xml")
        source.write_bytes(payload)
        try:
            result = run_migration(source, work_dir / "out", ai="none")
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return JSONResponse(result.model_dump())


def _zip_directory(directory: Path) -> io.BytesIO:
    """Zip a directory tree into an in-memory buffer."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in directory.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(directory))
    buffer.seek(0)
    return buffer
