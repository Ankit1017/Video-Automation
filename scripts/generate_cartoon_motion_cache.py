from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw


REQUIRED_EMOTIONS: tuple[str, ...] = ("neutral", "energetic", "tense", "warm", "inspiring")
REQUIRED_VISEMES: tuple[str, ...] = ("A", "B", "C", "D", "E", "F", "G", "H", "X")

MOUTH_OPEN: dict[str, float] = {
    "A": 0.24,
    "B": 0.12,
    "C": 0.18,
    "D": 0.10,
    "E": 0.20,
    "F": 0.09,
    "G": 0.18,
    "H": 0.13,
    "X": 0.04,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate demo multi-frame cartoon cache variants from manifest.")
    parser.add_argument("--pack-root", type=str, default="main_app/assets/cartoon_packs/default")
    parser.add_argument("--frames", type=int, default=8, help="Frame count per variant (recommended >= 8).")
    parser.add_argument("--size", type=int, default=384, help="Sprite canvas size in pixels.")
    parser.add_argument("--characters", type=str, default="", help="Comma-separated character ids (default: all manifest characters).")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing frame files.")
    args = parser.parse_args()

    pack_root = Path(args.pack_root).resolve()
    manifest_path = pack_root / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("Manifest must be a JSON object.")

    characters_raw = manifest.get("characters", [])
    if not isinstance(characters_raw, list):
        raise ValueError("Manifest characters must be an array.")
    selected = {
        clean(item).lower()
        for item in str(args.characters or "").split(",")
        if clean(item)
    }
    frames = max(1, int(args.frames))
    size = max(128, int(args.size))
    generated = 0

    for item in characters_raw:
        if not isinstance(item, dict):
            continue
        char_id = clean(item.get("id")).lower()
        if not char_id:
            continue
        if selected and char_id not in selected:
            continue
        rgb = hex_to_rgb(clean(item.get("color_hex"))) or (95, 140, 210)
        cache_root_hint = clean(item.get("cache_root")) or f"characters/{char_id}/cache"
        cache_root = resolve_path(pack_root=pack_root, hint=cache_root_hint)

        for state in ("idle", "blink"):
            for emotion in REQUIRED_EMOTIONS:
                generated += write_variant(
                    cache_root=cache_root,
                    state=state,
                    variant=emotion,
                    base_rgb=rgb,
                    frames=frames,
                    size=size,
                    overwrite=bool(args.overwrite),
                )
        for emotion in REQUIRED_EMOTIONS:
            for viseme in REQUIRED_VISEMES:
                generated += write_variant(
                    cache_root=cache_root,
                    state="talk",
                    variant=f"{emotion}_{viseme}",
                    base_rgb=rgb,
                    frames=frames,
                    size=size,
                    overwrite=bool(args.overwrite),
                )

    print(f"Generated/updated {generated} frame files under {pack_root}.")


def write_variant(
    *,
    cache_root: Path,
    state: str,
    variant: str,
    base_rgb: tuple[int, int, int],
    frames: int,
    size: int,
    overwrite: bool,
) -> int:
    folder = cache_root / state / variant
    folder.mkdir(parents=True, exist_ok=True)
    emotion, viseme = parse_variant(state=state, variant=variant)
    created = 0
    for index in range(frames):
        file_name = f"f{index + 1:04d}.png"
        path = folder / file_name
        if path.exists() and not overwrite:
            continue
        image = render_sprite_frame(
            size=size,
            base_rgb=base_rgb,
            state=state,
            emotion=emotion,
            viseme=viseme,
            frame_idx=index,
            frame_count=frames,
        )
        image.save(path)
        created += 1
    return created


def render_sprite_frame(
    *,
    size: int,
    base_rgb: tuple[int, int, int],
    state: str,
    emotion: str,
    viseme: str,
    frame_idx: int,
    frame_count: int,
) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    t = 0.0 if frame_count <= 1 else frame_idx / float(frame_count - 1)
    wave = math.sin(t * math.pi * 2.0)

    skin = tint((239, 206, 165), emotion=emotion, amount=0.07)
    shirt = tint(base_rgb, emotion=emotion, amount=0.16)
    outline = (24, 28, 36, 255)

    # Body and head
    torso = (
        int(size * 0.28),
        int(size * 0.46 + wave * 2.0),
        int(size * 0.72),
        int(size * 0.94 + wave * 2.0),
    )
    draw.rounded_rectangle(torso, radius=int(size * 0.06), fill=(*shirt, 255), outline=outline, width=max(1, size // 180))
    head_cx = int(size * 0.50)
    head_cy = int(size * 0.30 + wave * 3.0)
    head_r = int(size * 0.17)
    draw.ellipse((head_cx - head_r, head_cy - head_r, head_cx + head_r, head_cy + head_r), fill=(*skin, 255), outline=outline, width=max(1, size // 180))

    # Eyes / blink
    eye_y = int(head_cy - head_r * 0.15)
    eye_dx = int(head_r * 0.42)
    eye_r = max(2, int(size * 0.01))
    blinking = state == "blink" or (state != "talk" and (frame_idx % max(2, frame_count // 2) == 0))
    if blinking:
        draw.line((head_cx - eye_dx - eye_r, eye_y, head_cx - eye_dx + eye_r, eye_y), fill=(22, 26, 34, 255), width=max(1, size // 180))
        draw.line((head_cx + eye_dx - eye_r, eye_y, head_cx + eye_dx + eye_r, eye_y), fill=(22, 26, 34, 255), width=max(1, size // 180))
    else:
        draw.ellipse((head_cx - eye_dx - eye_r, eye_y - eye_r, head_cx - eye_dx + eye_r, eye_y + eye_r), fill=(22, 26, 34, 255))
        draw.ellipse((head_cx + eye_dx - eye_r, eye_y - eye_r, head_cx + eye_dx + eye_r, eye_y + eye_r), fill=(22, 26, 34, 255))

    # Brows (emotion hint)
    brow_y = eye_y - int(head_r * 0.26)
    brow_tilt = 0
    if emotion == "tense":
        brow_tilt = -int(size * 0.01)
    elif emotion in {"energetic", "inspiring"}:
        brow_tilt = int(size * 0.01)
    draw.line((head_cx - eye_dx - eye_r, brow_y, head_cx - eye_dx + eye_r, brow_y + brow_tilt), fill=(28, 30, 36, 255), width=max(1, size // 180))
    draw.line((head_cx + eye_dx - eye_r, brow_y + brow_tilt, head_cx + eye_dx + eye_r, brow_y), fill=(28, 30, 36, 255), width=max(1, size // 180))

    # Mouth / viseme
    mouth_y = int(head_cy + head_r * 0.34)
    mouth_w = int(head_r * 0.55)
    if state == "talk":
        openness = MOUTH_OPEN.get(clean(viseme).upper(), 0.10)
        talk_pulse = 0.85 + (0.3 * abs(wave))
        mouth_h = max(2, int(size * openness * talk_pulse))
        draw.ellipse(
            (head_cx - mouth_w // 2, mouth_y - mouth_h // 2, head_cx + mouth_w // 2, mouth_y + mouth_h // 2),
            fill=(46, 16, 20, 255),
            outline=(18, 20, 28, 255),
            width=max(1, size // 220),
        )
    else:
        smile = 0
        if emotion in {"warm", "inspiring"}:
            smile = int(size * 0.01)
        draw.arc(
            (head_cx - mouth_w // 2, mouth_y - size // 40, head_cx + mouth_w // 2, mouth_y + size // 28 + smile),
            start=10,
            end=170,
            fill=(24, 28, 34, 255),
            width=max(1, size // 180),
        )
    return image


def parse_variant(*, state: str, variant: str) -> tuple[str, str]:
    if state == "talk":
        parts = clean(variant).split("_")
        if len(parts) >= 2:
            return parts[0].lower() or "neutral", parts[-1].upper() or "X"
        return "neutral", "X"
    return clean(variant).lower() or "neutral", "X"


def resolve_path(*, pack_root: Path, hint: str) -> Path:
    raw = Path(hint)
    if raw.is_absolute():
        return raw
    return (pack_root / raw).resolve()


def clean(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def hex_to_rgb(hex_color: str) -> tuple[int, int, int] | None:
    raw = clean(hex_color).lstrip("#")
    if len(raw) != 6:
        return None
    try:
        return (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16))
    except ValueError:
        return None


def tint(rgb: tuple[int, int, int], *, emotion: str, amount: float) -> tuple[int, int, int]:
    mood = clean(emotion).lower()
    shift = {
        "neutral": (0.0, 0.0, 0.0),
        "energetic": (1.0, -0.2, 0.4),
        "tense": (0.6, -0.5, -0.3),
        "warm": (0.9, 0.25, -0.4),
        "inspiring": (-0.15, 0.25, 0.9),
    }.get(mood, (0.0, 0.0, 0.0))
    return (
        clip_channel(rgb[0] + (255.0 * shift[0] * amount)),
        clip_channel(rgb[1] + (255.0 * shift[1] * amount)),
        clip_channel(rgb[2] + (255.0 * shift[2] * amount)),
    )


def clip_channel(value: float) -> int:
    return int(max(0, min(255, round(value))))


if __name__ == "__main__":
    main()
