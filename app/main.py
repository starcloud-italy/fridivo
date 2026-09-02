import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import settings

app = FastAPI(title="Fridivo API", version="0.1.0")
app.include_router(api_router)

frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/assets", StaticFiles(directory=frontend_dir), name="frontend-assets")


@app.get("/", include_in_schema=False)
def frontend() -> FileResponse:
    return FileResponse(frontend_dir / "index.html")


@app.get("/app-config.js", include_in_schema=False)
def frontend_config() -> Response:
    config = json.dumps({"apiBaseUrl": settings.frontend_api_base_url})
    return Response(
        content=f"window.__FRIDIVO_CONFIG__ = {config};",
        media_type="application/javascript",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}
