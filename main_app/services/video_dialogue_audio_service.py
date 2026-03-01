from __future__ import annotations

from typing import cast

from main_app.contracts import DialogueAudioSegment, VideoConversationTimeline


class VideoDialogueAudioService:
    def build_segment_timing(
        self,
        *,
        timeline: VideoConversationTimeline | None,
    ) -> list[DialogueAudioSegment]:
        if not isinstance(timeline, dict):
            return []
        raw_segments = timeline.get("audio_segments", [])
        if not isinstance(raw_segments, list):
            return []
        segments: list[DialogueAudioSegment] = []
        for item in raw_segments:
            if not isinstance(item, dict):
                continue
            segment = cast(
                DialogueAudioSegment,
                {
                    "segment_ref": str(item.get("segment_ref", "")).strip(),
                    "speaker": str(item.get("speaker", "Speaker")).strip() or "Speaker",
                    "start_ms": _safe_int(item.get("start_ms", 0)),
                    "end_ms": _safe_int(item.get("end_ms", 0)),
                    "duration_ms": _safe_int(item.get("duration_ms", 0)),
                    "text": " ".join(str(item.get("text", "")).split()).strip(),
                    "cache_hit": bool(item.get("cache_hit", False)),
                },
            )
            if not segment["segment_ref"] or not segment["text"]:
                continue
            if segment["end_ms"] < segment["start_ms"]:
                segment["end_ms"] = segment["start_ms"]
            if segment["duration_ms"] <= 0:
                segment["duration_ms"] = max(0, segment["end_ms"] - segment["start_ms"])
            segments.append(segment)
        return segments


def _safe_int(value: object, default: int = 0) -> int:
    try:
        if isinstance(value, bool):
            return default
        if isinstance(value, (int, float, str)):
            return int(value)
        return int(str(value))
    except (TypeError, ValueError):
        return default

