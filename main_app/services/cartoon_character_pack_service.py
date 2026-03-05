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
        }

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
                },
            ),
        ]


def _clean(value: object) -> str:
    return " ".join(str(value or "").split()).strip()

