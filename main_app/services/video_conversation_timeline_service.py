from __future__ import annotations

from typing import cast

from main_app.contracts import (
    DialogueAudioSegment,
    SlideRepresentation,
    SlideContent,
    VideoConversationTimeline,
    VideoConversationTurn,
    VideoSlideScript,
    VideoVisualRef,
)


class VideoConversationTimelineService:
    def build_timeline(
        self,
        *,
        slides: list[SlideContent],
        slide_scripts: list[VideoSlideScript],
    ) -> VideoConversationTimeline:
        turns: list[VideoConversationTurn] = []
        segments: list[DialogueAudioSegment] = []
        now_ms = 0
        speaker_names: set[str] = set()
        turn_index = 0

        for script_pos, script in enumerate(slide_scripts):
            if not isinstance(script, dict):
                continue
            dialogue = script.get("dialogue", [])
            if not isinstance(dialogue, list) or not dialogue:
                continue

            slide_index = _safe_int(script.get("slide_index", script_pos + 1), default=script_pos + 1)
            slide_idx_zero = max(0, slide_index - 1)
            slide = slides[slide_idx_zero] if 0 <= slide_idx_zero < len(slides) else cast(SlideContent, {})
            representation = _normalize_representation(slide.get("representation", "bullet"))
            bullets = slide.get("bullets", [])
            bullet_count = len(bullets) if isinstance(bullets, list) else 0

            raw_duration_ms = int(round(float(_safe_float(script.get("estimated_duration_sec", 0.0), default=0.0)) * 1000.0))
            script_duration_ms = raw_duration_ms if raw_duration_ms > 0 else max(8_000, len(dialogue) * 2_000)

            word_weights: list[int] = []
            for item in dialogue:
                if not isinstance(item, dict):
                    word_weights.append(1)
                    continue
                text = " ".join(str(item.get("text", "")).split()).strip()
                word_weights.append(max(1, len(text.split())))
            total_weight = sum(word_weights) or len(word_weights) or 1

            for idx, item in enumerate(dialogue):
                if not isinstance(item, dict):
                    continue
                speaker = " ".join(str(item.get("speaker", "Speaker")).split()).strip() or "Speaker"
                text = " ".join(str(item.get("text", "")).split()).strip()
                if not text:
                    continue
                speaker_names.add(speaker)

                weight = word_weights[idx] if idx < len(word_weights) else 1
                duration_ms = max(700, int(round((weight / total_weight) * script_duration_ms)))
                start_ms = now_ms
                end_ms = start_ms + duration_ms
                now_ms = end_ms

                visual_ref: VideoVisualRef = {
                    "slide_index": slide_index,
                    "representation": representation,
                }
                if bullet_count > 0:
                    visual_ref["item_index"] = min(idx, bullet_count - 1)

                segment_ref = f"s{slide_index:03d}_t{idx+1:03d}"
                turns.append(
                    {
                        "turn_index": turn_index,
                        "speaker": speaker,
                        "text": text,
                        "slide_index": slide_index,
                        "start_ms": start_ms,
                        "end_ms": end_ms,
                        "estimated_duration_ms": duration_ms,
                        "visual_ref": visual_ref,
                        "segment_ref": segment_ref,
                    }
                )
                segments.append(
                    {
                        "segment_ref": segment_ref,
                        "speaker": speaker,
                        "start_ms": start_ms,
                        "end_ms": end_ms,
                        "duration_ms": duration_ms,
                        "text": text,
                        "cache_hit": False,
                    }
                )
                turn_index += 1

        return {
            "turns": turns,
            "audio_segments": segments,
            "total_duration_ms": now_ms,
            "turn_count": len(turns),
            "speaker_count": len(speaker_names),
            "generated_with": "timeline_builder_v1",
        }


def _safe_int(value: object, *, default: int) -> int:
    try:
        if isinstance(value, bool):
            return default
        if isinstance(value, (int, float, str)):
            return int(value)
        return int(str(value))
    except (TypeError, ValueError):
        return default


def _safe_float(value: object, *, default: float) -> float:
    try:
        if isinstance(value, bool):
            return default
        if isinstance(value, (int, float, str)):
            return float(value)
        return float(str(value))
    except (TypeError, ValueError):
        return default


def _normalize_representation(value: object) -> SlideRepresentation:
    normalized = " ".join(str(value).split()).strip().lower()
    if normalized in {"bullet", "two_column", "timeline", "comparison", "process_flow", "metric_cards"}:
        return cast(SlideRepresentation, normalized)
    return "bullet"
