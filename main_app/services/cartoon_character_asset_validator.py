from __future__ import annotations

from pathlib import Path

from main_app.contracts import CartoonCharacterSpec


class CartoonCharacterAssetValidator:
    REQUIRED_EMOTIONS: tuple[str, ...] = ("neutral", "energetic", "tense", "warm", "inspiring")
    REQUIRED_VISEMES: tuple[str, ...] = ("A", "B", "C", "D", "E", "F", "G", "H", "X")
    REQUIRED_STATES: tuple[str, ...] = ("idle", "blink", "talk")

    def __init__(self, *, pack_root: Path) -> None:
        self._pack_root = pack_root

    def validate_roster(
        self,
        *,
        roster: list[CartoonCharacterSpec],
        require_lottie_cache: bool,
        timeline_schema_version: str,
    ) -> list[str]:
        if not require_lottie_cache or _clean(timeline_schema_version).lower() != "v2":
            return []
        errors: list[str] = []
        if not roster:
            return ["Character roster missing; cannot validate v2 lottie cache assets."]
        for character in roster:
            errors.extend(self._validate_character(character))
        return errors

    def _validate_character(self, character: CartoonCharacterSpec) -> list[str]:
        errors: list[str] = []
        char_id = _clean(character.get("id")) or "unknown"
        asset_mode = _clean(character.get("asset_mode")).lower()
        if asset_mode != "lottie_cache":
            errors.append(f"Character `{char_id}` asset_mode must be `lottie_cache` for timeline v2.")
            return errors
        lottie_source = _clean(character.get("lottie_source"))
        if not lottie_source:
            errors.append(f"Character `{char_id}` missing `lottie_source`.")
        cache_root = _clean(character.get("cache_root"))
        if not cache_root:
            errors.append(f"Character `{char_id}` missing `cache_root`.")
            return errors
        cache_path = self._resolve_path(cache_root)
        if not cache_path.exists():
            errors.append(f"Character `{char_id}` cache path missing: {cache_path}")
            return errors

        for state in self.REQUIRED_STATES:
            if state == "talk":
                for emotion in self.REQUIRED_EMOTIONS:
                    for viseme in self.REQUIRED_VISEMES:
                        variant = f"{emotion}_{viseme}"
                        errors.extend(self._ensure_variant_has_frames(char_id=char_id, cache_path=cache_path, state=state, variant=variant))
            else:
                for emotion in self.REQUIRED_EMOTIONS:
                    errors.extend(self._ensure_variant_has_frames(char_id=char_id, cache_path=cache_path, state=state, variant=emotion))
        return errors

    def _ensure_variant_has_frames(
        self,
        *,
        char_id: str,
        cache_path: Path,
        state: str,
        variant: str,
    ) -> list[str]:
        state_path = cache_path / state / variant
        if not state_path.exists():
            return [f"Character `{char_id}` missing cache directory: {state_path}"]
        frame_paths = sorted(state_path.glob("f*.png"))
        if not frame_paths:
            return [f"Character `{char_id}` has no frames in: {state_path}"]
        return []

    def _resolve_path(self, path_hint: str) -> Path:
        raw = Path(path_hint)
        if raw.is_absolute():
            return raw
        return (self._pack_root / raw).resolve()


def _clean(value: object) -> str:
    return " ".join(str(value or "").split()).strip()
