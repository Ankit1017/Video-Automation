from __future__ import annotations

from typing import Any

from main_app.contracts import VideoRenderProfile


class VideoAvatarOverlayService:
    def apply_overlay(
        self,
        *,
        image: Any,
        draw_module: Any,
        font_module: Any,
        speaker_roster: list[dict[str, str]],
        active_speaker: str,
        last_speaker: str,
        subtitle_text: str,
        subtitles_enabled: bool,
        style_pack: str,
        render_profile: VideoRenderProfile | None,
    ) -> None:
        drawer = draw_module.Draw(image)
        width, height = image.size
        profile_key = str((render_profile or {}).get("profile_key", "")).strip().lower()
        scale = 1.0 if profile_key == "gpu_high" else (0.92 if profile_key == "gpu_balanced" else 0.84)
        if style_pack == "compact":
            scale *= 0.9

        avatar_size = int(min(width, height) * 0.18 * scale)
        margin = int(16 * scale)
        left_center = (margin + avatar_size // 2, height - margin - avatar_size // 2)
        right_center = (width - margin - avatar_size // 2, height - margin - avatar_size // 2)

        visible = self._visible_speakers(
            speaker_roster=speaker_roster,
            active_speaker=active_speaker,
            last_speaker=last_speaker,
        )
        left_name = visible[0] if visible else "Speaker"
        right_name = visible[1] if len(visible) > 1 else left_name

        self._draw_avatar_bubble(
            drawer=drawer,
            center=left_center,
            radius=avatar_size // 2,
            name=left_name,
            is_active=(left_name == active_speaker),
            font_module=font_module,
        )
        self._draw_avatar_bubble(
            drawer=drawer,
            center=right_center,
            radius=avatar_size // 2,
            name=right_name,
            is_active=(right_name == active_speaker),
            font_module=font_module,
        )

        self._draw_speaker_chips(
            drawer=drawer,
            width=width,
            speaker_roster=speaker_roster,
            visible_names={left_name, right_name},
            font_module=font_module,
        )

        if subtitles_enabled and subtitle_text:
            self._draw_subtitle(
                drawer=drawer,
                width=width,
                height=height,
                text=subtitle_text,
                speaker=active_speaker,
                font_module=font_module,
            )

    @staticmethod
    def _visible_speakers(
        *,
        speaker_roster: list[dict[str, str]],
        active_speaker: str,
        last_speaker: str,
    ) -> list[str]:
        roster_names = [
            " ".join(str(item.get("name", "")).split()).strip()
            for item in speaker_roster
            if isinstance(item, dict) and str(item.get("name", "")).strip()
        ]
        ordered: list[str] = []
        if active_speaker:
            ordered.append(active_speaker)
        if last_speaker and last_speaker not in ordered:
            ordered.append(last_speaker)
        for name in roster_names:
            if name not in ordered:
                ordered.append(name)
        if not ordered:
            ordered = ["Speaker A", "Speaker B"]
        if len(ordered) == 1:
            ordered.append(ordered[0])
        return ordered[:2]

    @staticmethod
    def _draw_avatar_bubble(
        *,
        drawer: Any,
        center: tuple[int, int],
        radius: int,
        name: str,
        is_active: bool,
        font_module: Any,
    ) -> None:
        x, y = center
        fill = (26, 32, 44, 235) if is_active else (46, 58, 78, 210)
        outline = (74, 164, 255, 255) if is_active else (126, 142, 168, 220)
        border = 6 if is_active else 3
        drawer.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill, outline=outline, width=border)
        label_font = _font(font_module=font_module, size=max(16, radius // 4), bold=True)
        label = " ".join(str(name).split()).strip() or "Speaker"
        bbox = drawer.textbbox((0, 0), label, font=label_font)
        text_w = max(0, bbox[2] - bbox[0])
        text_h = max(0, bbox[3] - bbox[1])
        drawer.text((x - text_w // 2, y - text_h // 2), label, fill=(245, 248, 255, 255), font=label_font)

    @staticmethod
    def _draw_speaker_chips(
        *,
        drawer: Any,
        width: int,
        speaker_roster: list[dict[str, str]],
        visible_names: set[str],
        font_module: Any,
    ) -> None:
        chip_font = _font(font_module=font_module, size=18, bold=False)
        x = 18
        y = 16
        for item in speaker_roster:
            if not isinstance(item, dict):
                continue
            name = " ".join(str(item.get("name", "")).split()).strip()
            if not name or name in visible_names:
                continue
            label = f"{name}"
            bbox = drawer.textbbox((0, 0), label, font=chip_font)
            text_w = max(0, bbox[2] - bbox[0])
            text_h = max(0, bbox[3] - bbox[1])
            chip_w = text_w + 24
            chip_h = text_h + 10
            if x + chip_w > width - 18:
                break
            drawer.rounded_rectangle((x, y, x + chip_w, y + chip_h), radius=12, fill=(22, 27, 39, 190), outline=(92, 108, 133, 220), width=2)
            drawer.text((x + 12, y + 5), label, fill=(235, 241, 255, 255), font=chip_font)
            x += chip_w + 8

    @staticmethod
    def _draw_subtitle(
        *,
        drawer: Any,
        width: int,
        height: int,
        text: str,
        speaker: str,
        font_module: Any,
    ) -> None:
        subtitle_font = _font(font_module=font_module, size=24, bold=True)
        speaker_label = " ".join(str(speaker).split()).strip() or "Speaker"
        subtitle = f"{speaker_label}: {text}"
        lines = _wrap_text(drawer=drawer, text=subtitle, font=subtitle_font, max_width=max(400, width - 120))
        if not lines:
            return
        line_height = max(28, int(subtitle_font.size * 1.35))
        block_h = line_height * len(lines) + 18
        top = height - block_h - 10
        drawer.rounded_rectangle((40, top, width - 40, height - 10), radius=14, fill=(8, 12, 19, 200), outline=(55, 85, 130, 220), width=2)
        y = top + 10
        for line in lines:
            bbox = drawer.textbbox((0, 0), line, font=subtitle_font)
            text_w = max(0, bbox[2] - bbox[0])
            drawer.text(((width - text_w) // 2, y), line, fill=(240, 245, 255, 255), font=subtitle_font)
            y += line_height


def _font(*, font_module: Any, size: int, bold: bool) -> Any:
    candidates = [
        "C:\\Windows\\Fonts\\arialbd.ttf" if bold else "C:\\Windows\\Fonts\\arial.ttf",
        "C:\\Windows\\Fonts\\segoeuib.ttf" if bold else "C:\\Windows\\Fonts\\segoeui.ttf",
    ]
    for path in candidates:
        try:
            return font_module.truetype(path, size)
        except (OSError, ValueError):
            continue
    try:
        return font_module.load_default()
    except (AttributeError, OSError, ValueError):
        return None


def _wrap_text(*, drawer: Any, text: str, font: Any, max_width: int) -> list[str]:
    words = [word for word in str(text).split() if word]
    if not words:
        return []
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join([*current, word]).strip()
        bbox = drawer.textbbox((0, 0), candidate, font=font)
        width = max(0, bbox[2] - bbox[0])
        if width <= max_width or not current:
            current.append(word)
            continue
        lines.append(" ".join(current))
        current = [word]
    if current:
        lines.append(" ".join(current))
    return lines[:3]

