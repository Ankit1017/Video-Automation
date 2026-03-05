from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import sys
from typing import Any

from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from main_app.services.cartoon_character_asset_validator import CartoonCharacterAssetValidator


REQUIRED_EMOTIONS: tuple[str, ...] = ("neutral", "energetic", "tense", "warm", "inspiring")
REQUIRED_VISEMES: tuple[str, ...] = ("A", "B", "C", "D", "E", "F", "G", "H", "X")
MOUTH_OPEN_RATIO: dict[str, float] = {
    "A": 0.22,
    "B": 0.12,
    "C": 0.16,
    "D": 0.10,
    "E": 0.19,
    "F": 0.08,
    "G": 0.17,
    "H": 0.13,
    "X": 0.06,
}


@dataclass(frozen=True)
class CharacterKit:
    char_id: str
    name: str
    role: str
    color_hex: str
    voice: str
    base_path: Path
    emotion_paths: dict[str, Path]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build runtime-ready cartoon pack from composed open-source character kits.",
    )
    parser.add_argument(
        "--source-root",
        type=str,
        default="main_app/assets/open-source_packs",
        help="Root directory where character_kits and source inventory live.",
    )
    parser.add_argument(
        "--kit-subdir",
        type=str,
        default="character_kits",
        help="Character kits subdirectory under source root.",
    )
    parser.add_argument(
        "--pack-root",
        type=str,
        default="main_app/assets/cartoon_packs/open_source_curated",
        help="Output cartoon pack path.",
    )
    parser.add_argument(
        "--frames",
        type=int,
        default=12,
        help="Frame count per variant.",
    )
    parser.add_argument(
        "--size",
        type=int,
        default=512,
        help="Output cache frame resolution (square).",
    )
    parser.add_argument(
        "--cache-fps",
        type=int,
        default=24,
        help="Cache FPS metadata for deterministic frame selection.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Delete existing pack root before build.",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Run strict v2 validator after pack build.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_root = Path(args.source_root).resolve()
    kit_root = source_root / str(args.kit_subdir).strip()
    pack_root = Path(args.pack_root).resolve()
    frame_count = max(1, int(args.frames))
    size = max(192, int(args.size))
    cache_fps = max(1, int(args.cache_fps))

    if not kit_root.exists() or not kit_root.is_dir():
        raise FileNotFoundError(f"Character kits directory not found: {kit_root}")

    character_kits = load_character_kits(kit_root=kit_root)
    if not character_kits:
        raise RuntimeError(f"No usable character kits found in: {kit_root}")

    if pack_root.exists():
        if not args.overwrite:
            raise FileExistsError(
                f"Pack root already exists: {pack_root}. Use --overwrite to rebuild."
            )
        shutil.rmtree(pack_root, ignore_errors=True)
    pack_root.mkdir(parents=True, exist_ok=True)

    manifest_characters: list[dict[str, Any]] = []
    for index, kit in enumerate(character_kits):
        character_root = pack_root / "characters" / kit.char_id
        cache_root = character_root / "cache"
        lottie_root = character_root / "lottie"
        sources_root = character_root / "sources"
        cache_root.mkdir(parents=True, exist_ok=True)
        lottie_root.mkdir(parents=True, exist_ok=True)
        sources_root.mkdir(parents=True, exist_ok=True)

        lottie_placeholder = {
            "v": "5.7.0",
            "fr": cache_fps,
            "ip": 0,
            "op": max(cache_fps, frame_count),
            "w": size,
            "h": size,
            "nm": f"{kit.char_id}_placeholder",
            "ddd": 0,
            "assets": [],
            "layers": [],
        }
        (lottie_root / "main.json").write_text(
            json.dumps(lottie_placeholder, ensure_ascii=True, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        shutil.copy2(kit.base_path, sources_root / "base.png")
        for emotion, emotion_path in kit.emotion_paths.items():
            if emotion_path.exists():
                shutil.copy2(emotion_path, sources_root / f"{emotion}.png")

        render_character_cache(
            kit=kit,
            cache_root=cache_root,
            size=size,
            frame_count=frame_count,
        )

        manifest_characters.append(
            {
                "id": kit.char_id,
                "name": kit.name,
                "role": kit.role,
                "color_hex": kit.color_hex,
                "outfit_variant": "open_source_curated",
                "voice": kit.voice,
                "asset_mode": "lottie_cache",
                "lottie_source": f"characters/{kit.char_id}/lottie/main.json",
                "cache_root": f"characters/{kit.char_id}/cache",
                "state_map": {"idle": "idle", "talk": "talk", "blink": "blink"},
                "anchor": {"x": 0.5, "y": 1.0},
                "default_scale": 1.0,
                "z_layer": index + 1,
            }
        )

    manifest = {
        "pack_name": "Open Source Curated Toon Pack",
        "pack_version": "v1",
        "pack_schema_version": "v2",
        "cache_fps": cache_fps,
        "cache_resolution": f"{size}x{size}",
        "license": "Mixed open-source licenses; see sources and upstream files.",
        "characters": manifest_characters,
        "background_keys": [
            "studio_blue",
            "classroom_warm",
            "city_evening",
            "news_desk",
            "product_stage",
            "case_boardroom",
        ],
        "emotion_keys": list(REQUIRED_EMOTIONS),
        "source_info": {
            "source_root": str(source_root),
            "kit_root": str(kit_root),
            "generated_at": _utc_now_iso(),
        },
    }
    manifest_path = pack_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=False), encoding="utf-8")

    if args.validate:
        validator = CartoonCharacterAssetValidator(
            pack_root=pack_root,
            expected_cache_resolution=f"{size}x{size}",
        )
        errors = validator.validate_roster(
            roster=manifest_characters,
            require_lottie_cache=True,
            timeline_schema_version="v2",
        )
        warnings = validator.audit_roster_motion_quality(
            roster=manifest_characters,
            timeline_schema_version="v2",
        )
        if errors:
            raise RuntimeError(f"Pack validation failed: {errors[0]}")
        print(f"Validation: errors={len(errors)}, warnings={len(warnings)}")

    print(f"Pack root: {pack_root}")
    print(f"Characters: {len(manifest_characters)}")
    print(f"Frame size: {size}x{size}")
    print(f"Frames per variant: {frame_count}")
    print(f"Manifest: {manifest_path}")
    return 0


def load_character_kits(*, kit_root: Path) -> list[CharacterKit]:
    kits: list[CharacterKit] = []
    for char_dir in sorted(kit_root.iterdir(), key=lambda item: item.name.lower()):
        if not char_dir.is_dir():
            continue
        meta_path = char_dir / "meta.json"
        if not meta_path.exists():
            continue
        try:
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(metadata, dict):
            continue
        char_id = _clean(metadata.get("character_id") or char_dir.name).lower()
        if not char_id:
            continue
        base_rel = _clean(metadata.get("base_image"))
        base_path = (kit_root / base_rel).resolve() if base_rel else char_dir / "base.png"
        if not base_path.exists():
            continue
        emotion_paths: dict[str, Path] = {}
        raw_overlays = metadata.get("emotion_overlays")
        if isinstance(raw_overlays, dict):
            for key, value in raw_overlays.items():
                emotion = _clean(key).lower()
                rel = _clean(value)
                if not emotion or not rel:
                    continue
                candidate = (kit_root / rel).resolve()
                if candidate.exists():
                    emotion_paths[emotion] = candidate
        kit = CharacterKit(
            char_id=char_id,
            name=_clean(metadata.get("name")) or char_id.replace("_", " ").title(),
            role=_clean(metadata.get("role")) or "Narrator",
            color_hex=_clean(metadata.get("color_hex")) or "#5AA9FF",
            voice=_clean(metadata.get("voice")) or "",
            base_path=base_path,
            emotion_paths=emotion_paths,
        )
        kits.append(kit)
    return kits


def render_character_cache(
    *,
    kit: CharacterKit,
    cache_root: Path,
    size: int,
    frame_count: int,
) -> None:
    base_portrait = _load_image_rgba(kit.base_path)
    emotion_images: dict[str, Image.Image] = {}
    for emotion in REQUIRED_EMOTIONS:
        emotion_path = kit.emotion_paths.get(emotion)
        if emotion_path is not None and emotion_path.exists():
            emotion_images[emotion] = _load_image_rgba(emotion_path)
        else:
            emotion_images[emotion] = apply_tint(
                image=base_portrait,
                color=_emotion_color_shift(emotion=emotion),
                alpha=26,
            )

    for state in ("idle", "blink"):
        for emotion in REQUIRED_EMOTIONS:
            variant_dir = cache_root / state / emotion
            variant_dir.mkdir(parents=True, exist_ok=True)
            for index in range(frame_count):
                frame = render_variant_frame(
                    portrait=emotion_images[emotion],
                    state=state,
                    emotion=emotion,
                    viseme="X",
                    frame_index=index,
                    frame_count=frame_count,
                    size=size,
                    accent_hex=kit.color_hex,
                )
                frame.save(variant_dir / f"f{index + 1:04d}.png", optimize=True)

    for emotion in REQUIRED_EMOTIONS:
        for viseme in REQUIRED_VISEMES:
            variant_dir = cache_root / "talk" / f"{emotion}_{viseme}"
            variant_dir.mkdir(parents=True, exist_ok=True)
            for index in range(frame_count):
                frame = render_variant_frame(
                    portrait=emotion_images[emotion],
                    state="talk",
                    emotion=emotion,
                    viseme=viseme,
                    frame_index=index,
                    frame_count=frame_count,
                    size=size,
                    accent_hex=kit.color_hex,
                )
                frame.save(variant_dir / f"f{index + 1:04d}.png", optimize=True)


def render_variant_frame(
    *,
    portrait: Image.Image,
    state: str,
    emotion: str,
    viseme: str,
    frame_index: int,
    frame_count: int,
    size: int,
    accent_hex: str,
) -> Image.Image:
    t = 0.0 if frame_count <= 1 else frame_index / float(frame_count - 1)
    wave = math.sin(t * math.pi * 2.0)
    wave2 = math.sin((t * math.pi * 2.0) + 1.3)

    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas, "RGBA")
    accent_rgb = _hex_to_rgb(accent_hex) or (95, 140, 210)
    shadow_w = int(size * 0.36)
    shadow_h = int(size * 0.06)
    shadow_x = (size - shadow_w) // 2
    shadow_y = int(size * 0.94)
    draw.ellipse(
        (shadow_x, shadow_y - shadow_h // 2, shadow_x + shadow_w, shadow_y + shadow_h // 2),
        fill=(12, 15, 20, 55),
    )

    source = _crop_to_alpha_bounds(portrait)
    base_height = int(size * 0.86)
    pulse_scale = 1.0 + (0.018 * wave)
    target_h = max(1, int(round(base_height * pulse_scale)))
    ratio = float(source.width) / float(max(1, source.height))
    target_w = max(1, int(round(target_h * ratio)))
    resample = _resample_lanczos()
    sprite = source.resize((target_w, target_h), resample=resample)
    if abs(wave2) > 0.45:
        rotate_resample = _resample_bicubic()
        sprite = sprite.rotate(
            wave2 * 1.1,
            resample=rotate_resample,
            expand=True,
        )
    left = (size - sprite.width) // 2 + int(wave2 * 1.8)
    top = int(size * 0.94) - sprite.height + int(wave * 2.5)
    canvas.paste(sprite, (left, top), sprite)

    alpha = canvas.split()[-1]
    accent_layer = Image.new("RGBA", canvas.size, (*accent_rgb, 16))
    canvas = Image.composite(Image.alpha_composite(canvas, accent_layer), canvas, alpha)

    face_cx = size // 2 + int(wave2 * 1.0)
    face_cy = int(size * 0.33 + (wave * 1.8))
    eye_dx = int(size * 0.078)
    eye_w = int(size * 0.032)
    eye_h = int(size * 0.016)
    blink_on = state == "blink" or (state != "talk" and frame_index % max(3, frame_count // 3) == 0)
    if blink_on:
        draw.line(
            (face_cx - eye_dx - eye_w, face_cy, face_cx - eye_dx + eye_w, face_cy),
            fill=(18, 24, 30, 240),
            width=max(1, size // 220),
        )
        draw.line(
            (face_cx + eye_dx - eye_w, face_cy, face_cx + eye_dx + eye_w, face_cy),
            fill=(18, 24, 30, 240),
            width=max(1, size // 220),
        )
    else:
        draw.ellipse(
            (
                face_cx - eye_dx - eye_w,
                face_cy - eye_h,
                face_cx - eye_dx + eye_w,
                face_cy + eye_h,
            ),
            fill=(255, 255, 255, 210),
        )
        draw.ellipse(
            (
                face_cx + eye_dx - eye_w,
                face_cy - eye_h,
                face_cx + eye_dx + eye_w,
                face_cy + eye_h,
            ),
            fill=(255, 255, 255, 210),
        )
        pupil_r = max(1, int(size * 0.008))
        draw.ellipse(
            (
                face_cx - eye_dx - pupil_r,
                face_cy - pupil_r,
                face_cx - eye_dx + pupil_r,
                face_cy + pupil_r,
            ),
            fill=(26, 30, 38, 255),
        )
        draw.ellipse(
            (
                face_cx + eye_dx - pupil_r,
                face_cy - pupil_r,
                face_cx + eye_dx + pupil_r,
                face_cy + pupil_r,
            ),
            fill=(26, 30, 38, 255),
        )

    brow_y = face_cy - int(size * 0.032)
    brow_tilt = 0
    if emotion == "tense":
        brow_tilt = -int(size * 0.008)
    elif emotion in {"energetic", "inspiring"}:
        brow_tilt = int(size * 0.007)
    draw.line(
        (face_cx - eye_dx - eye_w, brow_y, face_cx - eye_dx + eye_w, brow_y + brow_tilt),
        fill=(24, 28, 34, 255),
        width=max(1, size // 260),
    )
    draw.line(
        (face_cx + eye_dx - eye_w, brow_y + brow_tilt, face_cx + eye_dx + eye_w, brow_y),
        fill=(24, 28, 34, 255),
        width=max(1, size // 260),
    )

    mouth_y = int(size * 0.42 + wave * 1.2)
    mouth_w = int(size * 0.1)
    if state == "talk":
        open_ratio = MOUTH_OPEN_RATIO.get(viseme.upper(), 0.1)
        mouth_h = max(2, int(size * open_ratio * (0.9 + (0.25 * abs(wave)))))
        draw.ellipse(
            (face_cx - mouth_w // 2, mouth_y - mouth_h // 2, face_cx + mouth_w // 2, mouth_y + mouth_h // 2),
            fill=(34, 12, 16, 240),
            outline=(12, 10, 14, 245),
            width=max(1, size // 300),
        )
        if mouth_h > int(size * 0.02):
            draw.rounded_rectangle(
                (
                    face_cx - int(mouth_w * 0.35),
                    mouth_y - int(mouth_h * 0.32),
                    face_cx + int(mouth_w * 0.35),
                    mouth_y - int(mouth_h * 0.12),
                ),
                radius=max(1, size // 500),
                fill=(246, 242, 236, 212),
            )
    else:
        smile = 0
        if emotion in {"warm", "inspiring"}:
            smile = int(size * 0.008)
        draw.arc(
            (face_cx - mouth_w // 2, mouth_y - int(size * 0.02), face_cx + mouth_w // 2, mouth_y + int(size * 0.02) + smile),
            start=12,
            end=168,
            fill=(20, 24, 30, 245),
            width=max(1, size // 220),
        )
    return canvas


def apply_tint(*, image: Image.Image, color: tuple[int, int, int], alpha: int) -> Image.Image:
    overlay = Image.new("RGBA", image.size, (color[0], color[1], color[2], max(0, min(255, alpha))))
    return Image.alpha_composite(image.copy(), overlay)


def _emotion_color_shift(*, emotion: str) -> tuple[int, int, int]:
    mapping = {
        "neutral": (0, 0, 0),
        "energetic": (240, 92, 78),
        "tense": (174, 56, 46),
        "warm": (232, 165, 84),
        "inspiring": (112, 126, 232),
    }
    return mapping.get(_clean(emotion).lower(), (0, 0, 0))


def _load_image_rgba(path: Path) -> Image.Image:
    with Image.open(path) as image:
        return image.convert("RGBA")


def _crop_to_alpha_bounds(image: Image.Image) -> Image.Image:
    bbox = image.getbbox()
    if bbox is None:
        return image
    return image.crop(bbox)


def _hex_to_rgb(value: object) -> tuple[int, int, int] | None:
    raw = _clean(value).lstrip("#")
    if len(raw) != 6:
        return None
    try:
        return (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16))
    except ValueError:
        return None


def _resample_lanczos() -> int:
    resampling = getattr(Image, "Resampling", None)
    if resampling is not None and hasattr(resampling, "LANCZOS"):
        return int(resampling.LANCZOS)
    return int(getattr(Image, "LANCZOS", 1))


def _resample_bicubic() -> int:
    resampling = getattr(Image, "Resampling", None)
    if resampling is not None and hasattr(resampling, "BICUBIC"):
        return int(resampling.BICUBIC)
    return int(getattr(Image, "BICUBIC", 3))


def _clean(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
