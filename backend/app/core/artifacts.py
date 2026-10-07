"""Screenshot/artifact path helpers: absolute path <-> safe relative URL."""
from __future__ import annotations

from pathlib import Path

from app.core.config import get_settings


def _root() -> Path:
    return Path(get_settings().screenshot_dir).resolve()


def to_relative(path: str | None) -> str | None:
    """Absolute screenshot path -> path relative to SCREENSHOT_DIR (None if outside)."""
    if not path:
        return None
    try:
        return Path(path).resolve().relative_to(_root()).as_posix()
    except (ValueError, OSError):
        return None


def to_url(rel: str | None) -> str | None:
    return f"/api/artifacts/screenshots/{rel}" if rel else None


def resolve_screenshot(rel: str) -> Path | None:
    """Relative path -> file under SCREENSHOT_DIR, or None (blocks traversal, symlink escape, non-images)."""
    root = _root()
    try:
        candidate = (root / rel).resolve()
        candidate.relative_to(root)
    except (ValueError, OSError):
        return None
    if candidate.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"} or not candidate.is_file():
        return None
    return candidate
