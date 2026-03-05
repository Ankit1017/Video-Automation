from __future__ import annotations

from typing import cast

from main_app.contracts import (
    CartoonCameraMove,
    CartoonCameraTrack,
    CartoonCharacterSpec,
    CartoonCharacterTrack,
    CartoonDialogueTurn,
    CartoonMood,
    CartoonScene,
    CartoonShotType,
    CartoonSubtitleTrack,
    CartoonTimeline,
    CartoonTransitionType,
)


class CartoonTimelineService:
    def normalize_timeline(
        self,
        *,
        timeline: CartoonTimeline | None,
        timeline_schema_version: str = "v1",
        character_roster: list[CartoonCharacterSpec] | None = None,
    ) -> tuple[CartoonTimeline, list[str]]:
        notes: list[str] = []
        schema_version = _normalize_schema_version(timeline_schema_version)
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
        roster_ids = {_clean(item.get("id")).lower() for item in (character_roster or []) if isinstance(item, dict) and _clean(item.get("id"))}
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

            normalized_scene = cast(
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

            if schema_version == "v2":
                camera_track, camera_note = _normalize_camera_track(scene.get("camera_track"), scene_duration_ms=scene_duration_ms)
                character_tracks, track_notes = _normalize_character_tracks(
                    scene.get("character_tracks"),
                    scene_duration_ms=scene_duration_ms,
                    roster_ids=roster_ids,
                )
                subtitle_track = _normalize_subtitle_track(scene.get("subtitle_track"))
                if camera_track is None:
                    notes.append(f"Scene {scene_index} ignored: {camera_note or 'camera_track missing.'}")
                    continue
                if not character_tracks:
                    notes.append(f"Scene {scene_index} ignored: character_tracks missing or invalid for v2 timeline.")
                    if track_notes:
                        notes.extend([f"Scene {scene_index}: {note}" for note in track_notes])
                    continue
                if track_notes:
                    notes.extend([f"Scene {scene_index}: {note}" for note in track_notes])
                normalized_scene["camera_track"] = camera_track
                normalized_scene["character_tracks"] = character_tracks
                if subtitle_track:
                    normalized_scene["subtitle_track"] = subtitle_track

            normalized_scenes.append(normalized_scene)
            global_ms += scene_duration_ms

        normalized_timeline = cast(
            CartoonTimeline,
            {
                "scenes": normalized_scenes,
                "total_duration_ms": global_ms,
                "scene_count": len(normalized_scenes),
                "speaker_count": len(speaker_ids),
                "generated_with": _clean(timeline.get("generated_with"))
                or ("timeline_normalizer_v2" if schema_version == "v2" else "timeline_normalizer_v1"),
            },
        )
        return normalized_timeline, notes


def _normalize_camera_track(value: object, *, scene_duration_ms: int) -> tuple[CartoonCameraTrack | None, str | None]:
    if not isinstance(value, dict):
        return None, "camera_track missing."
    keyframes_raw = value.get("keyframes", [])
    if not isinstance(keyframes_raw, list) or not keyframes_raw:
        return None, "camera_track.keyframes missing."
    keyframes: list[dict[str, object]] = []
    for raw in keyframes_raw:
        if not isinstance(raw, dict):
            continue
        keyframes.append(
            {
                "t_ms": max(0, min(_int_safe(raw.get("t_ms"), default=0), scene_duration_ms)),
                "x": _float_safe(raw.get("x"), default=0.0),
                "y": _float_safe(raw.get("y"), default=0.0),
                "zoom": max(0.2, _float_safe(raw.get("zoom"), default=1.0)),
                "rotation": _float_safe(raw.get("rotation"), default=0.0),
                "ease": _normalize_ease(raw.get("ease")),
            }
        )
    if not keyframes:
        return None, "camera_track.keyframes invalid."
    keyframes.sort(key=lambda item: _int_safe(item.get("t_ms"), default=0))
    if _int_safe(keyframes[0].get("t_ms"), default=0) > 0:
        first = dict(keyframes[0])
        first["t_ms"] = 0
        keyframes.insert(0, first)
    if _int_safe(keyframes[-1].get("t_ms"), default=0) < scene_duration_ms:
        last = dict(keyframes[-1])
        last["t_ms"] = scene_duration_ms
        keyframes.append(last)
    return cast(CartoonCameraTrack, {"keyframes": keyframes}), None


def _normalize_character_tracks(
    value: object,
    *,
    scene_duration_ms: int,
    roster_ids: set[str],
) -> tuple[list[CartoonCharacterTrack], list[str]]:
    if not isinstance(value, list) or not value:
        return [], []
    notes: list[str] = []
    tracks: list[CartoonCharacterTrack] = []
    seen_ids: set[str] = set()
    for raw_track in value:
        if not isinstance(raw_track, dict):
            continue
        character_id = _clean(raw_track.get("character_id")).lower()
        if not character_id:
            notes.append("character_track skipped: missing character_id.")
            continue
        if character_id in seen_ids:
            notes.append(f"character_track `{character_id}` duplicated; keeping first.")
            continue
        keyframes_raw = raw_track.get("keyframes", [])
        if not isinstance(keyframes_raw, list) or not keyframes_raw:
            notes.append(f"character_track `{character_id}` missing keyframes.")
            continue
        keyframes: list[dict[str, object]] = []
        for raw_keyframe in keyframes_raw:
            if not isinstance(raw_keyframe, dict):
                continue
            keyframes.append(
                {
                    "t_ms": max(0, min(_int_safe(raw_keyframe.get("t_ms"), default=0), scene_duration_ms)),
                    "x_norm": _clamp(_float_safe(raw_keyframe.get("x_norm"), default=0.5), low=0.0, high=1.0),
                    "y_norm": _clamp(_float_safe(raw_keyframe.get("y_norm"), default=0.7), low=0.0, high=1.0),
                    "scale": max(0.1, _float_safe(raw_keyframe.get("scale"), default=1.0)),
                    "rotation": _float_safe(raw_keyframe.get("rotation"), default=0.0),
                    "pose": _clean(raw_keyframe.get("pose")) or "idle",
                    "emotion": _clean(raw_keyframe.get("emotion")) or "neutral",
                    "opacity": _clamp(_float_safe(raw_keyframe.get("opacity"), default=1.0), low=0.0, high=1.0),
                    "z_index": _int_safe(raw_keyframe.get("z_index"), default=0),
                    "ease": _normalize_ease(raw_keyframe.get("ease")),
                }
            )
        if not keyframes:
            notes.append(f"character_track `{character_id}` keyframes invalid.")
            continue
        keyframes.sort(key=lambda item: _int_safe(item.get("t_ms"), default=0))
        if _int_safe(keyframes[0].get("t_ms"), default=0) > 0:
            first = dict(keyframes[0])
            first["t_ms"] = 0
            keyframes.insert(0, first)
        if _int_safe(keyframes[-1].get("t_ms"), default=0) < scene_duration_ms:
            last = dict(keyframes[-1])
            last["t_ms"] = scene_duration_ms
            keyframes.append(last)
        tracks.append(cast(CartoonCharacterTrack, {"character_id": character_id, "keyframes": keyframes}))
        seen_ids.add(character_id)
    if roster_ids:
        missing = sorted([char_id for char_id in roster_ids if char_id not in seen_ids])
        if missing:
            notes.append(f"No character_track provided for roster ids: {', '.join(missing)}.")
    return tracks, notes


def _normalize_subtitle_track(value: object) -> CartoonSubtitleTrack | None:
    if not isinstance(value, dict):
        return None
    return cast(
        CartoonSubtitleTrack,
        {
            "y_norm": _clamp(_float_safe(value.get("y_norm"), default=0.9), low=0.05, high=0.98),
            "max_lines": max(1, min(_int_safe(value.get("max_lines"), default=2), 4)),
            "style": _clean(value.get("style")) or "default",
        },
    )


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


def _float_safe(value: object, *, default: float) -> float:
    try:
        if isinstance(value, bool):
            return default
        if isinstance(value, (int, float, str)):
            return float(value)
        return float(str(value))
    except (TypeError, ValueError):
        return default


def _clamp(value: float, *, low: float, high: float) -> float:
    return max(low, min(float(value), high))


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


def _normalize_ease(value: object) -> str:
    raw = _clean(value).lower().replace(" ", "_")
    if raw in {"linear", "ease_in", "ease_out", "ease_in_out"}:
        return raw
    return "linear"


def _normalize_schema_version(value: object) -> str:
    raw = _clean(value).lower()
    if raw == "v2":
        return "v2"
    return "v1"
