from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw


REQUIRED_EMOTIONS: tuple[str, ...] = ("neutral", "energetic", "tense", "warm", "inspiring")


@dataclass(frozen=True)
class CharacterProfile:
    char_id: str
    name: str
    role: str
    color_hex: str
    voice: str


@dataclass(frozen=True)
class CandidateImage:
    path: Path
    score: float
    width: int
    height: int
    source_pack: str


CHARACTER_PROFILES: tuple[CharacterProfile, ...] = (
    CharacterProfile(char_id="ava", name="Ava", role="Guide", color_hex="#4F8EF7", voice="female_1"),
    CharacterProfile(char_id="noah", name="Noah", role="Engineer", color_hex="#5BC0A8", voice="male_1"),
    CharacterProfile(char_id="mia", name="Mia", role="Reviewer", color_hex="#F39C6B", voice="female_2"),
    CharacterProfile(char_id="liam", name="Liam", role="Examples Specialist", color_hex="#BA8CFF", voice="male_2"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compose normalized character kit images from open-source pack assets.",
    )
    parser.add_argument(
        "--source-root",
        type=str,
        default="main_app/assets/open-source_packs",
        help="Root path containing normalized assets from ingest step.",
    )
    parser.add_argument(
        "--normalized-subdir",
        type=str,
        default="normalized",
        help="Subdirectory under source root containing normalized files.",
    )
    parser.add_argument(
        "--kit-subdir",
        type=str,
        default="character_kits",
        help="Subdirectory under source root where composed kits are written.",
    )
    parser.add_argument(
        "--canvas-size",
        type=int,
        default=1024,
        help="Output kit canvas size in pixels (square).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing kit outputs.",
    )
    parser.add_argument(
        "--include-openmoji",
        action="store_true",
        help="Allow OpenMoji PNG images as candidate portraits (disabled by default).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed candidate selection output.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_root = Path(args.source_root).resolve()
    normalized_root = source_root / str(args.normalized_subdir).strip()
    kit_root = source_root / str(args.kit_subdir).strip()

    if not normalized_root.exists() or not normalized_root.is_dir():
        raise FileNotFoundError(f"Normalized root not found: {normalized_root}")

    canvas_size = max(384, int(args.canvas_size))
    candidates = discover_candidates(
        normalized_root=normalized_root,
        include_openmoji=bool(args.include_openmoji),
    )
    if not candidates:
        raise RuntimeError("No usable PNG candidates found in normalized assets.")

    if args.verbose:
        print(f"Candidates discovered: {len(candidates)}")
        for candidate in candidates[:12]:
            print(
                f"  {candidate.source_pack:24s} score={candidate.score:7.2f} "
                f"{candidate.width:4d}x{candidate.height:<4d} {candidate.path}"
            )

    kit_root.mkdir(parents=True, exist_ok=True)
    selected = select_candidates(candidates=candidates, count=len(CHARACTER_PROFILES))
    kit_index: dict[str, dict[str, Any]] = {}

    for index, profile in enumerate(CHARACTER_PROFILES):
        candidate = selected[index] if index < len(selected) else selected[-1]
        char_dir = kit_root / profile.char_id
        if char_dir.exists() and not args.overwrite:
            raise FileExistsError(
                f"Character kit exists and --overwrite not set: {char_dir}. "
                "Use --overwrite to regenerate."
            )
        char_dir.mkdir(parents=True, exist_ok=True)
        base_path = char_dir / "base.png"
        emotion_dir = char_dir / "emotion_overlays"
        emotion_dir.mkdir(parents=True, exist_ok=True)
        meta_path = char_dir / "meta.json"

        base_image = compose_base_image(
            source_path=candidate.path,
            canvas_size=canvas_size,
            accent_hex=profile.color_hex,
        )
        base_image.save(base_path, optimize=True)

        emotion_paths: dict[str, str] = {}
        for emotion in REQUIRED_EMOTIONS:
            emotion_image = apply_emotion_grade(
                image=base_image,
                emotion=emotion,
                accent_hex=profile.color_hex,
            )
            emotion_file = emotion_dir / f"{emotion}.png"
            emotion_image.save(emotion_file, optimize=True)
            emotion_paths[emotion] = str(emotion_file.relative_to(kit_root))

        metadata = {
            "character_id": profile.char_id,
            "name": profile.name,
            "role": profile.role,
            "voice": profile.voice,
            "color_hex": profile.color_hex,
            "source_file": str(candidate.path),
            "source_pack": candidate.source_pack,
            "source_dimensions": {"width": candidate.width, "height": candidate.height},
            "selection_score": round(candidate.score, 3),
            "base_image": str(base_path.relative_to(kit_root)),
            "emotion_overlays": emotion_paths,
            "generated_at": _utc_now_iso(),
        }
        meta_path.write_text(json.dumps(metadata, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
        kit_index[profile.char_id] = metadata

        if args.verbose:
            print(f"[kit] {profile.char_id}: {candidate.path}")

    index_path = kit_root / "index.json"
    index_payload = {
        "generated_at": _utc_now_iso(),
        "canvas_size": canvas_size,
        "kit_count": len(kit_index),
        "kits": kit_index,
    }
    index_path.write_text(json.dumps(index_payload, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Kits generated: {len(kit_index)}")
    print(f"Kit root: {kit_root}")
    print(f"Index file: {index_path}")
    return 0


def discover_candidates(*, normalized_root: Path, include_openmoji: bool) -> list[CandidateImage]:
    candidates: list[CandidateImage] = []
    for path in sorted(normalized_root.rglob("*.png"), key=lambda item: str(item).lower()):
        if not path.is_file():
            continue
        if _looks_like_junk(path):
            continue
        lowered = str(path).lower()
        if not include_openmoji and "openmoji" in lowered:
            continue
        if _looks_like_emoji_file(path):
            continue
        if _looks_like_atom_piece(path):
            continue
        file_size = path.stat().st_size
        if file_size < 14_000:
            continue
        try:
            with Image.open(path) as image:
                width, height = image.size
        except (OSError, ValueError):
            continue
        if width < 180 or height < 180:
            continue
        ratio = float(width) / float(max(1, height))
        if ratio < 0.35 or ratio > 1.45:
            continue
        source_pack = _source_pack_name(path=path, normalized_root=normalized_root)
        score = _candidate_score(
            path=path,
            source_pack=source_pack,
            width=width,
            height=height,
            file_size=file_size,
        )
        if score <= 0.0:
            continue
        candidates.append(
            CandidateImage(
                path=path,
                score=score,
                width=width,
                height=height,
                source_pack=source_pack,
            )
        )
    candidates.sort(key=lambda item: (item.score, item.height * item.width), reverse=True)
    return candidates


def select_candidates(*, candidates: list[CandidateImage], count: int) -> list[CandidateImage]:
    selected: list[CandidateImage] = []
    used_stems: set[str] = set()
    for candidate in candidates:
        stem = candidate.path.stem.lower()
        if stem in used_stems:
            continue
        selected.append(candidate)
        used_stems.add(stem)
        if len(selected) >= count:
            break
    if not selected:
        raise RuntimeError("No candidates selected for character kits.")
    while len(selected) < count:
        selected.append(selected[-1])
    return selected


def compose_base_image(*, source_path: Path, canvas_size: int, accent_hex: str) -> Image.Image:
    with Image.open(source_path) as source:
        source_rgba = source.convert("RGBA")
    source_cropped = _crop_to_alpha_bounds(source_rgba)
    target_max_width = int(canvas_size * 0.72)
    target_max_height = int(canvas_size * 0.88)
    ratio = min(
        target_max_width / float(max(1, source_cropped.width)),
        target_max_height / float(max(1, source_cropped.height)),
    )
    ratio = max(0.1, min(ratio, 1.8))
    resized_w = max(1, int(round(source_cropped.width * ratio)))
    resized_h = max(1, int(round(source_cropped.height * ratio)))
    resample = _resample_lanczos()
    portrait = source_cropped.resize((resized_w, resized_h), resample=resample)

    canvas = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas, "RGBA")
    shadow_w = int(canvas_size * 0.42)
    shadow_h = int(canvas_size * 0.08)
    shadow_y = int(canvas_size * 0.93)
    shadow_x = (canvas_size - shadow_w) // 2
    draw.ellipse((shadow_x, shadow_y - shadow_h // 2, shadow_x + shadow_w, shadow_y + shadow_h // 2), fill=(10, 12, 16, 54))

    offset_x = (canvas_size - resized_w) // 2
    offset_y = int(canvas_size * 0.95) - resized_h
    canvas.paste(portrait, (offset_x, offset_y), portrait)

    accent_rgb = _hex_to_rgb(accent_hex) or (95, 140, 210)
    tint_overlay = Image.new("RGBA", canvas.size, (*accent_rgb, 34))
    alpha = canvas.split()[-1]
    canvas = Image.composite(Image.alpha_composite(canvas, tint_overlay), canvas, alpha)
    return canvas


def apply_emotion_grade(*, image: Image.Image, emotion: str, accent_hex: str) -> Image.Image:
    mood = " ".join(str(emotion or "").split()).strip().lower()
    tint_map: dict[str, tuple[int, int, int, int]] = {
        "neutral": (0, 0, 0, 0),
        "energetic": (250, 98, 88, 24),
        "tense": (176, 58, 48, 28),
        "warm": (245, 168, 80, 24),
        "inspiring": (122, 138, 255, 26),
    }
    accent_rgb = _hex_to_rgb(accent_hex) or (95, 140, 210)
    accent_layer = Image.new("RGBA", image.size, (*accent_rgb, 12))
    output = Image.alpha_composite(image.copy(), accent_layer)
    tint = tint_map.get(mood, tint_map["neutral"])
    if tint[3] > 0:
        output = Image.alpha_composite(output, Image.new("RGBA", output.size, tint))
    return output


def _candidate_score(
    *,
    path: Path,
    source_pack: str,
    width: int,
    height: int,
    file_size: int,
) -> float:
    score = 0.0
    area = width * height
    score += min(120.0, area / 5000.0)
    score += min(42.0, file_size / 10000.0)
    ratio = float(width) / float(max(1, height))
    if 0.55 <= ratio <= 1.0:
        score += 24.0
    if height >= width:
        score += 10.0
    lowered = str(path).lower()
    if "open_doodles" in source_pack or "open-doodles" in lowered:
        score += 42.0
    if "flat_assets" in source_pack or "open_peeps" in lowered:
        score += 34.0
    if "standing" in lowered:
        score += 28.0
    if "bust" in lowered:
        score += 18.0
    if "doodle" in lowered:
        score += 32.0
    if "template" in lowered:
        score += 6.0
    if "face" in lowered and "complete" not in lowered:
        score -= 40.0
    if "eyebrow" in lowered or "eye/" in lowered or "mouth/" in lowered:
        score -= 60.0
    if "kenney_modular_characters" in source_pack:
        score -= 14.0
    return score


def _crop_to_alpha_bounds(image: Image.Image) -> Image.Image:
    bbox = image.getbbox()
    if bbox is None:
        return image
    return image.crop(bbox)


def _source_pack_name(*, path: Path, normalized_root: Path) -> str:
    try:
        relative = path.relative_to(normalized_root)
    except ValueError:
        return "unknown"
    if not relative.parts:
        return "unknown"
    return relative.parts[0]


def _looks_like_junk(path: Path) -> bool:
    lowered = path.name.lower()
    if lowered in {".ds_store", "thumbs.db"}:
        return True
    if lowered.startswith("._"):
        return True
    return "__macosx" in {part.lower() for part in path.parts}


def _looks_like_emoji_file(path: Path) -> bool:
    stem = path.stem
    if not stem:
        return True
    cleaned = stem.replace("-", "")
    if not cleaned:
        return True
    return all(ch in "0123456789abcdefABCDEF" for ch in cleaned) and len(cleaned) >= 4


def _looks_like_atom_piece(path: Path) -> bool:
    lowered = str(path).lower()
    fragments = ("eyebrow", "eyelash", "mouth", "hair/", "face/", "arm/", "leg/")
    return any(fragment in lowered for fragment in fragments)


def _hex_to_rgb(value: object) -> tuple[int, int, int] | None:
    raw = " ".join(str(value or "").split()).strip().lstrip("#")
    if len(raw) != 6:
        return None
    try:
        return (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16))
    except ValueError:
        return None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _resample_lanczos() -> int:
    resampling = getattr(Image, "Resampling", None)
    if resampling is not None and hasattr(resampling, "LANCZOS"):
        return int(resampling.LANCZOS)
    return int(getattr(Image, "LANCZOS", 1))


if __name__ == "__main__":
    raise SystemExit(main())
