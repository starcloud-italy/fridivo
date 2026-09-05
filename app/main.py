import hashlib
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import settings

app = FastAPI(title="Fridivo API", version="0.1.0")
app.include_router(api_router)

frontend_dir = Path(__file__).resolve().parent.parent / "frontend"


def _frontend_asset_version(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(candidate for candidate in directory.rglob("*") if candidate.is_file()):
        digest.update(path.relative_to(directory).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:16]


class CacheControlledStaticFiles(StaticFiles):
    def __init__(self, *args, cache_control: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.cache_control = cache_control

    async def get_response(self, path: str, scope: dict) -> Response:
        response = await super().get_response(path, scope)
        if response.status_code in (200, 304):
            response.headers["Cache-Control"] = self.cache_control
        return response


FRONTEND_ASSET_VERSION = _frontend_asset_version(frontend_dir)
VERSIONED_ASSET_PREFIX = f"/assets/{FRONTEND_ASSET_VERSION}"

app.mount(
    VERSIONED_ASSET_PREFIX,
    CacheControlledStaticFiles(
        directory=frontend_dir,
        cache_control="public, max-age=31536000, immutable",
    ),
    name="versioned-frontend-assets",
)
app.mount(
    "/assets",
    CacheControlledStaticFiles(directory=frontend_dir, cache_control="no-cache"),
    name="frontend-assets",
)


@app.get("/", include_in_schema=False, response_class=HTMLResponse)
def frontend() -> HTMLResponse:
    html = (frontend_dir / "index.html").read_text(encoding="utf-8")
    html = html.replace('"/assets/', f'"{VERSIONED_ASSET_PREFIX}/')
    return HTMLResponse(content=html, headers={"Cache-Control": "no-cache"})


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
