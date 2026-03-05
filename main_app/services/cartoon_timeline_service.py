from __future__ import annotations

from typing import cast

from main_app.contracts import (
    CartoonCameraMove,
    CartoonDialogueTurn,
    CartoonMood,
    CartoonScene,
    CartoonShotType,
    CartoonTimeline,
    CartoonTransitionType,
)


class CartoonTimelineService:
    def normalize_timeline(
        self,
        *,
        timeline: CartoonTimeline | None,
    ) -> tuple[CartoonTimeline, list[str]]:
        notes: list[str] = []
        if not isinstance(timeline, dict):
            return cast(CartoonTimeline, {"scenes": [], "total_duration_ms": 0, "scene_count": 0, "speaker_count": 0}), [
                "Timeline missing; initialized with empty structure."
            ]
        scenes_raw = timeline.get("scenes", [])
        if not isinstance(scenes_raw, list):
            return cast(CartoonTimeline, {"scenes": [], "total_duration_ms": 0, "scene_count": 0, "speaker_count": 0}), [
                "Timeline scenes field invalid; reset to empty."
            ]

        normalized_scenes: list[CartoonScene] = []
        global_ms = 0
        speaker_ids: set[str] = set()
        for scene_index, scene in enumerate(scenes_raw, start=1):
            if not isinstance(scene, dict):
                notes.append(f"Scene {scene_index} ignored: not an object.")
                continue
            turns_raw = scene.get("turns", [])
            turns: list[CartoonDialogueTurn] = []
            scene_cursor = 0
            if isinstance(turns_raw, list):
                for turn_index, turn in enumerate(turns_raw):
                    if not isinstance(turn, dict):
                        notes.append(f"Scene {scene_index} turn {turn_index + 1} ignored: not an object.")
                        continue
                    text = _clean(turn.get("text"))
                    speaker_id = _clean(turn.get("speaker_id")) or _clean(turn.get("speaker_name")).lower().replace(" ", "_")
                    speaker_name = _clean(turn.get("speaker_name")) or speaker_id.replace("_", " ").title()
                    if not text or not speaker_id:
                        notes.append(f"Scene {scene_index} turn {turn_index + 1} ignored: missing text or speaker.")
                        continue
                    duration_ms = max(1200, _int_safe(turn.get("estimated_duration_ms"), default=max(1800, len(text) * 70)))
                    start_ms = _int_safe(turn.get("start_ms"), default=scene_cursor)
                    if start_ms < scene_cursor:
                        start_ms = scene_cursor
                    end_ms = _int_safe(turn.get("end_ms"), default=start_ms + duration_ms)
                    if end_ms <= start_ms:
                        end_ms = start_ms + duration_ms
                    scene_cursor = end_ms
                    speaker_ids.add(speaker_id)
                    turns.append(
                        cast(
                            CartoonDialogueTurn,
                            {
                                "turn_index": turn_index,
                                "speaker_id": speaker_id,
                                "speaker_name": speaker_name,
                                "text": text,
                                "emotion": _clean(turn.get("emotion")) or "neutral",
                                "start_ms": global_ms + start_ms,
                                "end_ms": global_ms + end_ms,
                                "estimated_duration_ms": end_ms - start_ms,
                            },
                        )
                    )
            if not turns:
                notes.append(f"Scene {scene_index} ignored: no valid turns.")
                continue
            scene_duration_ms = max(2000, _int_safe(scene.get("duration_ms"), default=scene_cursor))
            if scene_duration_ms < scene_cursor:
                scene_duration_ms = scene_cursor
            normalized_scenes.append(
                cast(
                    CartoonScene,
                    {
                        "scene_index": scene_index,
                        "title": _clean(scene.get("title")) or f"Scene {scene_index}",
                        "hook": _clean(scene.get("hook")),
                        "background_key": _clean(scene.get("background_key")) or "studio_blue",
                        "camera_preset": _clean(scene.get("camera_preset")) or "medium_two_shot",
                        "shot_type": _normalize_shot_type(scene.get("shot_type"), default=_default_shot_type(scene_index)),
                        "camera_move": _normalize_camera_move(scene.get("camera_move"), default=_default_camera_move(scene_index)),
                        "transition_in": _normalize_transition(
                            scene.get("transition_in"),
                            default="cut" if scene_index == 1 else "crossfade",
                        ),
                        "transition_out": _normalize_transition(
                            scene.get("transition_out"),
                            default="fade_black" if scene_index == len(scenes_raw) else "crossfade",
                        ),
                        "mood": _normalize_mood(scene.get("mood"), default="neutral"),
                        "focus_character_id": _clean(scene.get("focus_character_id")),
                        "duration_ms": scene_duration_ms,
                        "turns": turns,
                        "visual_notes": _clean(scene.get("visual_notes")),
                    },
                )
            )
            global_ms += scene_duration_ms

        normalized_timeline = cast(
            CartoonTimeline,
            {
                "scenes": normalized_scenes,
                "total_duration_ms": global_ms,
                "scene_count": len(normalized_scenes),
                "speaker_count": len(speaker_ids),
                "generated_with": _clean(timeline.get("generated_with")) or "timeline_normalizer_v1",
            },
        )
        return normalized_timeline, notes


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


def _default_shot_type(scene_index: int) -> CartoonShotType:
    if scene_index <= 1:
        return "wide_establishing"
    if scene_index % 3 == 0:
        return "close_single"
    if scene_index % 2 == 0:
        return "over_shoulder"
    return "medium_two_shot"


def _default_camera_move(scene_index: int) -> CartoonCameraMove:
    moves: tuple[CartoonCameraMove, ...] = ("push_in", "pan_right", "static", "pan_left")
    return moves[(max(scene_index, 1) - 1) % len(moves)]


def _normalize_shot_type(value: object, *, default: CartoonShotType) -> CartoonShotType:
    raw = _clean(value).lower().replace(" ", "_")
    if raw in {"wide_establishing", "medium_two_shot", "close_single", "over_shoulder"}:
        return cast(CartoonShotType, raw)
    return default


def _normalize_camera_move(value: object, *, default: CartoonCameraMove) -> CartoonCameraMove:
    raw = _clean(value).lower().replace(" ", "_")
    if raw in {"static", "push_in", "pull_out", "pan_left", "pan_right"}:
        return cast(CartoonCameraMove, raw)
    return default


def _normalize_transition(value: object, *, default: CartoonTransitionType) -> CartoonTransitionType:
    raw = _clean(value).lower().replace(" ", "_")
    if raw in {"cut", "crossfade", "fade_black"}:
        return cast(CartoonTransitionType, raw)
    return default


def _normalize_mood(value: object, *, default: CartoonMood) -> CartoonMood:
    raw = _clean(value).lower().replace(" ", "_")
    if raw in {"neutral", "energetic", "tense", "warm", "inspiring"}:
        return cast(CartoonMood, raw)
    return default
