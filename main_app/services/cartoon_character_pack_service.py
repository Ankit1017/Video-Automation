from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from main_app.contracts import CartoonCharacterSpec


class CartoonCharacterPackService:
    def __init__(self, *, pack_root: Path | None = None) -> None:
        default_root = Path(__file__).resolve().parents[1] / "assets" / "cartoon_packs" / "default"
        self._pack_root = pack_root or default_root

    def load_roster(self, *, speaker_count: int = 2) -> list[CartoonCharacterSpec]:
        count = max(2, min(int(speaker_count), 4))
        manifest = self._load_manifest()
        characters_raw = manifest.get("characters", [])
        roster: list[CartoonCharacterSpec] = []
        if isinstance(characters_raw, list):
            for item in characters_raw:
                if not isinstance(item, dict):
                    continue
                character = cast(
                    CartoonCharacterSpec,
                    {
                        "id": _clean(item.get("id")) or f"char_{len(roster) + 1}",
                        "name": _clean(item.get("name")) or f"Character {len(roster) + 1}",
                        "role": _clean(item.get("role")) or "Narrator",
                        "color_hex": _clean(item.get("color_hex")) or "#5AA9FF",
                        "outfit_variant": _clean(item.get("outfit_variant")) or "default",
                        "voice": _clean(item.get("voice")) or "",
                        "asset_mode": _clean(item.get("asset_mode")) or "procedural",
                        "lottie_source": _clean(item.get("lottie_source")),
                        "cache_root": _clean(item.get("cache_root")) or f"characters/{_clean(item.get('id')) or f'char_{len(roster) + 1}'}/cache",
                        "state_map": _dict_safe(item.get("state_map")),
                        "anchor": _anchor_map(item.get("anchor")),
                        "default_scale": _float_safe(item.get("default_scale"), default=1.0),
                        "z_layer": _int_safe(item.get("z_layer"), default=len(roster)),
                    },
                )
                roster.append(character)
                if len(roster) >= count:
                    break
        if len(roster) < count:
            for fallback in self._fallback_characters():
                if len(roster) >= count:
                    break
                if any(str(item.get("id", "")).strip() == str(fallback.get("id", "")).strip() for item in roster):
                    continue
                roster.append(fallback)
        return roster[:count]

    def pack_metadata(self) -> dict[str, Any]:
        manifest = self._load_manifest()
        return {
            "pack_root": str(self._pack_root),
            "pack_name": _clean(manifest.get("pack_name")) or "default",
            "pack_version": _clean(manifest.get("pack_version")) or "v1",
            "pack_schema_version": _clean(manifest.get("pack_schema_version")) or "v1",
            "cache_fps": _int_safe(manifest.get("cache_fps"), default=24),
            "cache_resolution": _clean(manifest.get("cache_resolution")) or "unknown",
        }

    def pack_root_path(self) -> Path:
        return self._pack_root

    def _load_manifest(self) -> dict[str, Any]:
        path = self._pack_root / "manifest.json"
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return payload

    @staticmethod
    def _fallback_characters() -> list[CartoonCharacterSpec]:
        return [
            cast(
                CartoonCharacterSpec,
                {
                    "id": "ava",
                    "name": "Ava",
                    "role": "Guide",
                    "color_hex": "#4F8EF7",
                    "outfit_variant": "hoodie_blue",
                    "voice": "female_1",
                    "asset_mode": "procedural",
                    "lottie_source": "",
                    "cache_root": "characters/ava/cache",
                    "state_map": {},
                    "anchor": {"x": 0.5, "y": 1.0},
                    "default_scale": 1.0,
                    "z_layer": 0,
                },
            ),
            cast(
                CartoonCharacterSpec,
                {
                    "id": "noah",
                    "name": "Noah",
                    "role": "Engineer",
                    "color_hex": "#5BC0A8",
                    "outfit_variant": "shirt_green",
                    "voice": "male_1",
                    "asset_mode": "procedural",
                    "lottie_source": "",
                    "cache_root": "characters/noah/cache",
                    "state_map": {},
                    "anchor": {"x": 0.5, "y": 1.0},
                    "default_scale": 1.0,
                    "z_layer": 1,
                },
            ),
            cast(
                CartoonCharacterSpec,
                {
                    "id": "mia",
                    "name": "Mia",
                    "role": "Reviewer",
                    "color_hex": "#F39C6B",
                    "outfit_variant": "jacket_orange",
                    "voice": "female_2",
                    "asset_mode": "procedural",
                    "lottie_source": "",
                    "cache_root": "characters/mia/cache",
                    "state_map": {},
                    "anchor": {"x": 0.5, "y": 1.0},
                    "default_scale": 1.0,
                    "z_layer": 2,
                },
            ),
            cast(
                CartoonCharacterSpec,
                {
                    "id": "liam",
                    "name": "Liam",
                    "role": "Examples Specialist",
                    "color_hex": "#BA8CFF",
                    "outfit_variant": "shirt_purple",
                    "voice": "male_2",
                    "asset_mode": "procedural",
                    "lottie_source": "",
                    "cache_root": "characters/liam/cache",
                    "state_map": {},
                    "anchor": {"x": 0.5, "y": 1.0},
                    "default_scale": 1.0,
                    "z_layer": 3,
                },
            ),
        ]


def _clean(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _dict_safe(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return {str(key): item for key, item in value.items()}
    return {}


def _anchor_map(value: object) -> dict[str, float]:
    if isinstance(value, dict):
        return {
            "x": _float_safe(value.get("x"), default=0.5),
            "y": _float_safe(value.get("y"), default=1.0),
        }
    return {"x": 0.5, "y": 1.0}


def _int_safe(value: object, *, default: int) -> int:
    try:
        if isinstance(value, bool):
            return default
        if isinstance(value, (int, float, str)):
            return int(value)
        return int(str(value))
    except (TypeError, ValueError):
        return default


def _float_safe(value: object, *, default: float) -> float:
    try:
        if isinstance(value, bool):
            return default
        if isinstance(value, (int, float, str)):
            return float(value)
        return float(str(value))
    except (TypeError, ValueError):
        return default
