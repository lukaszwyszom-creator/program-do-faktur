"""
Router serwujący panel webowy (mobile-first SPA).

Mapowanie ścieżek:
  GET /ui/          → frontend/index.html   (lista faktur)
  GET /ui/login     → frontend/login.html
  GET /ui/invoice   → frontend/invoice.html (szczegóły, ?id=<uuid>)
  GET /ui/sw.js     → frontend/sw.js        (Service Worker — musi być na /ui/)
  GET /ui/manifest.webmanifest → frontend/manifest.webmanifest

Pliki statyczne (CSS, JS) serwowane przez StaticFiles pod /ui/static/.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

_FRONTEND = Path(__file__).parent.parent.parent.parent / "frontend"

router = APIRouter(prefix="/ui", include_in_schema=False)


def _file(name: str) -> FileResponse:
    return FileResponse(_FRONTEND / name)


@router.get("/")
@router.head("/")
def ui_index() -> FileResponse:
    return _file("index.html")


@router.get("/login")
def ui_login() -> FileResponse:
    return _file("login.html")


@router.get("/invoice")
def ui_invoice() -> FileResponse:
    return _file("invoice.html")


@router.get("/payments")
def ui_payments() -> FileResponse:
    return _file("payments.html")


@router.get("/sw.js")
def ui_sw() -> FileResponse:
    """Service Worker musi być serwowany z zakresu /ui/, nie /ui/static/."""
    return FileResponse(_FRONTEND / "sw.js", media_type="application/javascript")


@router.get("/manifest.webmanifest")
def ui_manifest() -> FileResponse:
    return FileResponse(
        _FRONTEND / "manifest.webmanifest",
        media_type="application/manifest+json",
    )


# Favicon serwowany też poza prefixem /ui przez główny router aplikacji
def get_favicon_path() -> Path:
    return _FRONTEND / "favicon.ico"
