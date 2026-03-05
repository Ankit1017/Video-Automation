from __future__ import annotations

from typing import cast

from main_app.contracts import AudioOverviewPayload, CartoonTimeline, DialogueAudioSegment
from main_app.services.audio_overview_service import AudioOverviewService


class CartoonAudioService:
    def __init__(self, audio_overview_service: AudioOverviewService) -> None:
        self._audio_overview_service = audio_overview_service

    def synthesize_timeline_audio(
        self,
        *,
        topic: str,
        title: str,
        timeline: CartoonTimeline,
        character_roster: list[dict[str, object]],
        language: str,
        slow: bool,
    ) -> tuple[bytes | None, str | None, list[DialogueAudioSegment]]:
        dialogue: list[dict[str, str]] = []
        segments: list[DialogueAudioSegment] = []
        for scene in timeline.get("scenes", []) if isinstance(timeline.get("scenes"), list) else []:
            if not isinstance(scene, dict):
                continue
            turns = scene.get("turns", [])
            if not isinstance(turns, list):
                continue
            for turn in turns:
                if not isinstance(turn, dict):
                    continue
                speaker = _clean(turn.get("speaker_name")) or _clean(turn.get("speaker_id")) or "Speaker"
                text = _clean(turn.get("text"))
                if not text:
                    continue
                dialogue.append({"speaker": speaker, "text": text})
                start_ms = _int_safe(turn.get("start_ms"), default=0)
                end_ms = _int_safe(turn.get("end_ms"), default=start_ms + max(1000, len(text) * 70))
                if end_ms < start_ms:
                    end_ms = start_ms
                segments.append(
                    cast(
                        DialogueAudioSegment,
                        {
                            "segment_ref": f"scene_{_int_safe(scene.get('scene_index'), default=1):02d}_turn_{_int_safe(turn.get('turn_index'), default=0):02d}",
                            "speaker": speaker,
                            "start_ms": start_ms,
                            "end_ms": end_ms,
                            "duration_ms": max(0, end_ms - start_ms),
                            "text": text,
                            "cache_hit": False,
                        },
                    )
                )

        if not dialogue:
            return None, "No dialogue turns available for audio synthesis.", []

        overview_payload = cast(
            AudioOverviewPayload,
            {
                "topic": _clean(topic) or "Cartoon Shorts",
                "title": _clean(title) or "Cartoon Shorts Audio",
                "speakers": character_roster if isinstance(character_roster, list) else [],
                "dialogue": dialogue,
                "summary": "Cartoon shorts narration track.",
            },
        )
        audio_bytes, audio_error = self._audio_overview_service.synthesize_mp3(
            overview_payload=overview_payload,
            language=_clean(language) or "en",
            slow=bool(slow),
        )
        return audio_bytes, audio_error, segments


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
