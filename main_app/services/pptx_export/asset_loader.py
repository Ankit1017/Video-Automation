from __future__ import annotations

from pathlib import Path
from typing import Iterable


def brand_asset_root() -> Path:
    return Path(__file__).resolve().parents[2] / "assets" / "brand"


def brand_fonts_root() -> Path:
    return brand_asset_root() / "fonts"


def brand_logo_root() -> Path:
    return brand_asset_root() / "logo"


def _first_existing(candidates: Iterable[Path]) -> Path | None:
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def discover_font_files() -> dict[str, str]:
    fonts_dir = brand_fonts_root()
    if not fonts_dir.exists() or not fonts_dir.is_dir():
        return {}

    candidates = [item for item in fonts_dir.iterdir() if item.is_file() and item.suffix.lower() in {".ttf", ".otf"}]
    if not candidates:
        return {}

    regular = _first_existing(
        item
        for item in candidates
        if "bold" not in item.stem.lower()
        and "semi" not in item.stem.lower()
        and "mono" not in item.stem.lower()
    )
    bold = _first_existing(item for item in candidates if "bold" in item.stem.lower() or "semi" in item.stem.lower())
    mono = _first_existing(item for item in candidates if "mono" in item.stem.lower() or "code" in item.stem.lower())

    if regular is None:
        regular = candidates[0]
    if bold is None:
        bold = regular
    if mono is None:
        mono = regular

    return {
        "regular": str(regular),
        "bold": str(bold),
        "mono": str(mono),
    }


def resolve_logo_path(preferred_path: str = "") -> str:
    preferred = Path(str(preferred_path).strip())
    if str(preferred).strip():
        if preferred.is_file():
            return str(preferred)
        absolute_preferred = (Path.cwd() / preferred).resolve()
        if absolute_preferred.is_file():
            return str(absolute_preferred)

    logo_dir = brand_logo_root()
    if not logo_dir.exists() or not logo_dir.is_dir():
        return ""

    name_candidates = [
        "logo.png",
        "logo.jpg",
        "logo.jpeg",
        "brand_logo.png",
        "brand_logo.jpg",
    ]
    exact = _first_existing(logo_dir / name for name in name_candidates)
    if exact is not None:
        return str(exact)

    fallback = _first_existing(item for item in logo_dir.iterdir() if item.is_file() and item.suffix.lower() in {".png", ".jpg", ".jpeg"})
    return str(fallback) if fallback is not None else ""


def brand_assets_status() -> dict[str, object]:
    fonts = discover_font_files()
    logo = resolve_logo_path("")
    return {
        "brand_root": str(brand_asset_root()),
        "fonts_found": bool(fonts),
        "logo_found": bool(logo),
        "font_paths": fonts,
        "logo_path": logo,
    }

