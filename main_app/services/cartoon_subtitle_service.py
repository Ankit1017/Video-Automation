from __future__ import annotations

import textwrap

from main_app.contracts import CartoonCharacterSpec


class CartoonSubtitleService:
    def compose_line(
        self,
        *,
        speaker_name: str,
        text: str,
        max_chars: int = 84,
        max_lines: int = 2,
    ) -> str:
        speaker = " ".join(str(speaker_name).split()).strip() or "Speaker"
        content = " ".join(str(text).split()).strip()
        if not content:
            return ""
        speaker_prefix = f"{speaker}: "
        available = max(24, int(max_chars) - len(speaker_prefix))
        wrapped = textwrap.wrap(content, width=available)
        if not wrapped:
            return speaker_prefix.strip()
        clipped = wrapped[: max(1, int(max_lines))]
        if len(wrapped) > len(clipped):
            clipped[-1] = clipped[-1].rstrip(". ") + "..."
        clipped[0] = f"{speaker_prefix}{clipped[0]}"
        return "\n".join(clipped)

    def speaker_color(self, speaker_id: str, roster: list[CartoonCharacterSpec]) -> tuple[int, int, int]:
        normalized = " ".join(str(speaker_id).split()).strip().lower()
        for item in roster:
            if not isinstance(item, dict):
                continue
            candidate_id = " ".join(str(item.get("id", "")).split()).strip().lower()
            if candidate_id != normalized:
                continue
            hex_color = " ".join(str(item.get("color_hex", "")).split()).strip()
            rgb = _hex_to_rgb(hex_color)
            if rgb is not None:
                return rgb
        return (235, 242, 255)


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int] | None:
    cleaned = hex_color.strip().lstrip("#")
    if len(cleaned) != 6:
        return None
    try:
        return tuple(int(cleaned[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return None
