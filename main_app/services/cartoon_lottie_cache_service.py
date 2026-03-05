from __future__ import annotations

from pathlib import Path
from typing import Literal

from main_app.contracts import CartoonCharacterSpec


CartoonSpriteState = Literal["idle", "blink", "talk"]


class CartoonLottieCacheService:
    def __init__(self, *, pack_root: Path) -> None:
        self._pack_root = pack_root
        self._cache_miss_count = 0

    @property
    def cache_miss_count(self) -> int:
        return self._cache_miss_count

    def reset_counters(self) -> None:
        self._cache_miss_count = 0

    def resolve_frame_path(
        self,
        *,
        character: CartoonCharacterSpec,
        state: CartoonSpriteState,
        emotion: str,
        viseme: str,
        t_ms: int,
        cache_fps: int,
    ) -> Path:
        cache_root = _clean(character.get("cache_root"))
        if not cache_root:
            self._cache_miss_count += 1
            raise FileNotFoundError(f"Character `{_clean(character.get('id')) or 'unknown'}` has no cache_root configured.")
        cache_root_path = self._resolve_path(cache_root)

        variants = self._variant_chain(state=state, emotion=emotion, viseme=viseme)
        for variant in variants:
            frame = self._pick_frame(cache_root=cache_root_path, state=state, variant=variant, t_ms=t_ms, cache_fps=cache_fps)
            if frame is not None:
                return frame
        self._cache_miss_count += 1
        raise FileNotFoundError(
            f"No cache frames found for character `{_clean(character.get('id')) or 'unknown'}` with state `{state}` variants {variants} under `{cache_root_path}`."
        )

    def _pick_frame(
        self,
        *,
        cache_root: Path,
        state: CartoonSpriteState,
        variant: str,
        t_ms: int,
        cache_fps: int,
    ) -> Path | None:
        folder = cache_root / state / variant
        if not folder.exists():
            return None
        frames = sorted(folder.glob("f*.png"))
        if not frames:
            return None
        safe_fps = max(1, int(cache_fps))
        frame_idx = int(max(0, int(t_ms)) * safe_fps / 1000.0) % len(frames)
        return frames[frame_idx]

    def _variant_chain(self, *, state: CartoonSpriteState, emotion: str, viseme: str) -> tuple[str, ...]:
        clean_emotion = _clean(emotion).lower() or "neutral"
        clean_viseme = _clean(viseme).upper() or "X"
        if state == "talk":
            return (
                f"{clean_emotion}_{clean_viseme}",
                f"neutral_{clean_viseme}",
                "neutral_X",
            )
        return (clean_emotion, "neutral")

    def _resolve_path(self, path_hint: str) -> Path:
        raw = Path(path_hint)
        if raw.is_absolute():
            return raw
        return (self._pack_root / raw).resolve()


def _clean(value: object) -> str:
    return " ".join(str(value or "").split()).strip()
