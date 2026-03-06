from __future__ import annotations

from collections import OrderedDict
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

from main_app.contracts import CartoonCharacterSpec
from main_app.services.cartoon_flat_asset_catalog_service import CartoonFlatAssetCatalogService


class CartoonFlatAssetSpriteService:
    def __init__(
        self,
        *,
        pack_root: Path,
        catalog_service: CartoonFlatAssetCatalogService | None = None,
        disk_cache_root: Path | None = None,
        memory_cache_size: int = 320,
    ) -> None:
        self._pack_root = pack_root
        self._catalog_service = catalog_service or CartoonFlatAssetCatalogService(pack_root=pack_root)
        self._disk_cache_root = disk_cache_root or (Path(".cache") / "cartoon_flat_sprite_cache")
        self._disk_cache_root.mkdir(parents=True, exist_ok=True)
        self._memory_cache_size = max(32, int(memory_cache_size))
        self._sprite_cache: OrderedDict[str, bytes] = OrderedDict()
        self._svg_cache: OrderedDict[tuple[str, int, int], bytes] = OrderedDict()
        self._svg_cache_limit = 256
        self._svg_raster_cache_hits = 0
        self._svg_raster_cache_misses = 0
        self._sprite_cache_hits = 0
        self._sprite_cache_misses = 0
        self._compose_total = 0
        self._compose_failures = 0

    @property
    def svg_raster_cache_hits(self) -> int:
        return self._svg_raster_cache_hits

    @property
    def svg_raster_cache_misses(self) -> int:
        return self._svg_raster_cache_misses

    @property
    def sprite_cache_hits(self) -> int:
        return self._sprite_cache_hits

    @property
    def sprite_cache_misses(self) -> int:
        return self._sprite_cache_misses

    def diagnostics(self) -> dict[str, int]:
        return {
            "svg_raster_cache_hits": self._svg_raster_cache_hits,
            "svg_raster_cache_misses": self._svg_raster_cache_misses,
            "sprite_cache_hits": self._sprite_cache_hits,
            "sprite_cache_misses": self._sprite_cache_misses,
            "compose_total": self._compose_total,
            "compose_failures": self._compose_failures,
        }

    def render_sprite(
        self,
        *,
        character: CartoonCharacterSpec,
        state: str,
        emotion: str,
        viseme: str,
        pose: str,
        t_ms: int,
        target_size: tuple[int, int],
    ) -> Image.Image | None:
        self._compose_total += 1
        char_id = _clean(character.get("id")).lower() or "character"
        clean_state = _clean(state).lower() or "idle"
        clean_emotion = _clean(emotion).lower() or "neutral"
        clean_viseme = _clean(viseme).upper() or "X"
        clean_pose = _clean(pose).lower() or "idle"
        width = max(24, _int_safe(target_size[0], default=256))
        height = max(24, _int_safe(target_size[1], default=256))
        frame_slot = max(0, _int_safe((max(0, int(t_ms)) * 24) // 1000, default=0))
        key = self._sprite_key(
            char_id=char_id,
            state=clean_state,
            emotion=clean_emotion,
            viseme=clean_viseme,
            pose=clean_pose,
            frame_slot=frame_slot,
            width=width,
            height=height,
        )

        memory_hit = self._read_memory_cache(key)
        if memory_hit is not None:
            self._sprite_cache_hits += 1
            return memory_hit
        disk_hit = self._read_disk_cache(key)
        if disk_hit is not None:
            self._sprite_cache_hits += 1
            self._write_memory_cache(key=key, image=disk_hit)
            return disk_hit
        self._sprite_cache_misses += 1

        profile = self._catalog_service.profile_for_character(character_id=char_id)
        base_path = self._choose_base_template(profile=profile, pose=clean_pose, frame_slot=frame_slot)
        if base_path is None or not base_path.exists():
            self._compose_failures += 1
            return None
        try:
            canvas = Image.open(base_path).convert("RGBA")
        except (OSError, ValueError):
            self._compose_failures += 1
            return None

        overlay_paths: list[Path] = []
        body_overlay = _path_safe(profile.get("body_overlay"))
        head_overlay = _path_safe(profile.get("head_overlay"))
        accessory_overlay = _path_safe(profile.get("accessory_overlay"))
        facial_hair_overlay = _path_safe(profile.get("facial_hair_overlay"))
        if body_overlay is not None:
            overlay_paths.append(body_overlay)
        pose_overlay = self._choose_pose_overlay(profile=profile, pose=clean_pose, frame_slot=frame_slot)
        if pose_overlay is not None:
            overlay_paths.append(pose_overlay)
        if head_overlay is not None:
            overlay_paths.append(head_overlay)
        if facial_hair_overlay is not None:
            overlay_paths.append(facial_hair_overlay)
        if accessory_overlay is not None and frame_slot % 3 == 0:
            overlay_paths.append(accessory_overlay)

        # Preserve precedence: blink > talk(viseme) > idle/emotion.
        face_overlays = self._face_overlays(
            profile=profile,
            state=clean_state,
            emotion=clean_emotion,
            viseme=clean_viseme,
        )
        overlay_paths.extend(face_overlays)

        composed = canvas
        for overlay_path in overlay_paths:
            overlay = self._render_overlay(path=overlay_path, width=composed.width, height=composed.height)
            if overlay is None:
                continue
            if overlay.size != composed.size:
                overlay = overlay.resize(composed.size, resample=_resample_lanczos())
            composed = Image.alpha_composite(composed, overlay)

        if (composed.width, composed.height) != (width, height):
            ratio = min(width / float(max(1, composed.width)), height / float(max(1, composed.height)))
            fit_w = max(1, int(round(composed.width * ratio)))
            fit_h = max(1, int(round(composed.height * ratio)))
            fitted = composed.resize((fit_w, fit_h), resample=_resample_lanczos())
            output = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            output.paste(fitted, ((width - fit_w) // 2, (height - fit_h) // 2), fitted)
            composed = output
        self._write_memory_cache(key=key, image=composed)
        self._write_disk_cache(key=key, image=composed)
        return composed

    def _face_overlays(self, *, profile: dict[str, object], state: str, emotion: str, viseme: str) -> list[Path]:
        paths: list[Path] = []
        emotion_faces = profile.get("emotion_faces", {})
        viseme_faces = profile.get("viseme_faces", {})
        blink_face = _path_safe(profile.get("blink_face"))
        if state == "blink":
            if blink_face is not None:
                paths.append(blink_face)
            return paths
        if isinstance(emotion_faces, dict):
            emotion_face = _path_safe(emotion_faces.get(emotion) or emotion_faces.get("neutral"))
            if emotion_face is not None:
                paths.append(emotion_face)
        if state == "talk" and isinstance(viseme_faces, dict):
            viseme_face = _path_safe(viseme_faces.get(viseme) or viseme_faces.get("X"))
            if viseme_face is not None:
                paths.append(viseme_face)
        return paths

    def _choose_base_template(self, *, profile: dict[str, object], pose: str, frame_slot: int) -> Path | None:
        templates = profile.get("templates", {})
        alternates = profile.get("template_alternates", {})
        template_group = _template_group_for_pose(pose)
        if isinstance(alternates, dict):
            candidate_list = alternates.get(template_group)
            if isinstance(candidate_list, list) and candidate_list:
                path = _path_safe(candidate_list[frame_slot % len(candidate_list)])
                if path is not None:
                    return path
        if isinstance(templates, dict):
            return _path_safe(templates.get(template_group))
        return None

    def _choose_pose_overlay(self, *, profile: dict[str, object], pose: str, frame_slot: int) -> Path | None:
        key = "pose_sitting" if _template_group_for_pose(pose) == "sitting" else "pose_standing"
        pose_entries = profile.get(key)
        if not isinstance(pose_entries, list) or not pose_entries:
            return None
        return _path_safe(pose_entries[frame_slot % len(pose_entries)])

    def _render_overlay(self, *, path: Path, width: int, height: int) -> Image.Image | None:
        if not path.exists() or not path.is_file():
            return None
        suffix = path.suffix.lower()
        if suffix == ".png":
            try:
                return Image.open(path).convert("RGBA").resize((width, height), resample=_resample_lanczos())
            except (OSError, ValueError):
                return None
        if suffix != ".svg":
            return None
        svg_bytes = self._render_svg(path=path, width=width, height=height)
        if svg_bytes is None:
            return None
        try:
            return Image.open(BytesIO(svg_bytes)).convert("RGBA")
        except (OSError, ValueError):
            return None

    def _render_svg(self, *, path: Path, width: int, height: int) -> bytes | None:
        key = (str(path), width, height)
        cached = self._svg_cache.get(key)
        if cached is not None:
            self._svg_raster_cache_hits += 1
            self._svg_cache.move_to_end(key)
            return cached
        self._svg_raster_cache_misses += 1
        try:
            import cairosvg  # type: ignore
        except ImportError:
            return None
        try:
            rendered = cairosvg.svg2png(
                url=str(path),
                output_width=max(1, int(width)),
                output_height=max(1, int(height)),
            )
        except (OSError, ValueError, TypeError):
            return None
        self._svg_cache[key] = rendered
        if len(self._svg_cache) > self._svg_cache_limit:
            self._svg_cache.popitem(last=False)
        return rendered

    @staticmethod
    def _sprite_key(
        *,
        char_id: str,
        state: str,
        emotion: str,
        viseme: str,
        pose: str,
        frame_slot: int,
        width: int,
        height: int,
    ) -> str:
        raw = f"{char_id}|{state}|{emotion}|{viseme}|{pose}|{frame_slot}|{width}x{height}"
        return sha256(raw.encode("utf-8", errors="ignore")).hexdigest()

    def _read_memory_cache(self, key: str) -> Image.Image | None:
        payload = self._sprite_cache.get(key)
        if payload is None:
            return None
        self._sprite_cache.move_to_end(key)
        try:
            return Image.open(BytesIO(payload)).convert("RGBA")
        except (OSError, ValueError):
            return None

    def _write_memory_cache(self, *, key: str, image: Image.Image) -> None:
        buffer = BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        self._sprite_cache[key] = buffer.getvalue()
        self._sprite_cache.move_to_end(key)
        while len(self._sprite_cache) > self._memory_cache_size:
            self._sprite_cache.popitem(last=False)

    def _read_disk_cache(self, key: str) -> Image.Image | None:
        path = self._disk_cache_root / f"{key}.png"
        if not path.exists():
            return None
        try:
            return Image.open(path).convert("RGBA")
        except (OSError, ValueError):
            return None

    def _write_disk_cache(self, *, key: str, image: Image.Image) -> None:
        path = self._disk_cache_root / f"{key}.png"
        try:
            image.save(path, format="PNG", optimize=True)
        except OSError:
            return


def _template_group_for_pose(pose: str) -> str:
    clean_pose = _clean(pose).lower()
    if "sit" in clean_pose:
        return "sitting"
    if "bust" in clean_pose or "close" in clean_pose:
        return "bust"
    return "standing"


def _path_safe(value: object) -> Path | None:
    if isinstance(value, Path):
        return value
    if isinstance(value, str):
        text = _clean(value)
        if text:
            return Path(text)
    return None


def _clean(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _int_safe(value: object, *, default: int) -> int:
    try:
        if isinstance(value, bool):
            return default
        if isinstance(value, (int, float, str)):
            return int(value)
        return int(str(value))
    except (TypeError, ValueError):
        return default


def _resample_lanczos() -> int:
    resampling = getattr(Image, "Resampling", None)
    if resampling is not None and hasattr(resampling, "LANCZOS"):
        return int(resampling.LANCZOS)
    return int(getattr(Image, "LANCZOS", 1))
