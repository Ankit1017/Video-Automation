from __future__ import annotations

from typing import cast

from main_app.contracts import CartoonCharacterSpec, CartoonDialogueTurn, CartoonScene


class CartoonMotionPlannerService:
    def plan_frame(
        self,
        *,
        scene: CartoonScene,
        character_roster: list[CartoonCharacterSpec],
        scene_relative_ms: int,
        scene_duration_ms: int,
        active_turn: CartoonDialogueTurn | None,
        active_mouth: str,
    ) -> dict[str, object]:
        duration_ms = max(1, int(scene_duration_ms))
        time_ms = max(0, min(int(scene_relative_ms), duration_ms))
        active_speaker_id = _clean((active_turn or {}).get("speaker_id")).lower()

        camera = self._camera_state(scene=scene, time_ms=time_ms, duration_ms=duration_ms)
        planned_characters = self._character_states(
            scene=scene,
            character_roster=character_roster,
            time_ms=time_ms,
            duration_ms=duration_ms,
            active_speaker_id=active_speaker_id,
            active_mouth=active_mouth,
        )
        subtitle_track = scene.get("subtitle_track", {}) if isinstance(scene.get("subtitle_track"), dict) else {}
        return {
            "camera": camera,
            "characters": planned_characters,
            "subtitle_track": subtitle_track,
        }

    def _camera_state(self, *, scene: CartoonScene, time_ms: int, duration_ms: int) -> dict[str, float]:
        track = scene.get("camera_track", {})
        keyframes = track.get("keyframes", []) if isinstance(track, dict) else []
        if not isinstance(keyframes, list) or not keyframes:
            progress = float(time_ms) / float(max(1, duration_ms))
            shift_x, shift_y, zoom = _legacy_camera_transform(camera_move=_clean(scene.get("camera_move")), progress=progress)
            return {"x": shift_x, "y": shift_y, "zoom": zoom, "rotation": 0.0}
        return cast(dict[str, float], _interpolate_keyframes(keyframes=keyframes, t_ms=time_ms, defaults={"x": 0.0, "y": 0.0, "zoom": 1.0, "rotation": 0.0}))

    def _character_states(
        self,
        *,
        scene: CartoonScene,
        character_roster: list[CartoonCharacterSpec],
        time_ms: int,
        duration_ms: int,
        active_speaker_id: str,
        active_mouth: str,
    ) -> list[dict[str, object]]:
        tracks_raw = scene.get("character_tracks", [])
        tracks = [track for track in tracks_raw if isinstance(track, dict)] if isinstance(tracks_raw, list) else []
        track_by_id = {_clean(track.get("character_id")).lower(): track for track in tracks if _clean(track.get("character_id"))}

        planned: list[dict[str, object]] = []
        roster = [character for character in character_roster if isinstance(character, dict)]
        if not roster:
            roster = [{"id": "speaker_a", "name": "Speaker A"}, {"id": "speaker_b", "name": "Speaker B"}]
        for index, character in enumerate(roster):
            char_id = _clean(character.get("id")).lower() or f"speaker_{index + 1}"
            track = track_by_id.get(char_id, {})
            keyframes = track.get("keyframes", []) if isinstance(track, dict) else []
            if isinstance(keyframes, list) and keyframes:
                interp = _interpolate_keyframes(
                    keyframes=keyframes,
                    t_ms=time_ms,
                    defaults={
                        "x_norm": 0.2 + (index * 0.3),
                        "y_norm": 0.72,
                        "scale": _float_safe(character.get("default_scale"), default=1.0),
                        "rotation": 0.0,
                        "opacity": 1.0,
                        "z_index": _int_safe(character.get("z_layer"), default=index),
                    },
                )
                x_norm = _float_safe(interp.get("x_norm"), default=0.2 + (index * 0.3))
                y_norm = _float_safe(interp.get("y_norm"), default=0.72)
                scale = _float_safe(interp.get("scale"), default=_float_safe(character.get("default_scale"), default=1.0))
                rotation = _float_safe(interp.get("rotation"), default=0.0)
                opacity = _float_safe(interp.get("opacity"), default=1.0)
                z_index = _int_safe(interp.get("z_index"), default=_int_safe(character.get("z_layer"), default=index))
                emotion = _clean(interp.get("emotion")) or "neutral"
                pose = _clean(interp.get("pose")) or "idle"
            else:
                x_norm = 0.2 + (index * 0.3)
                y_norm = 0.72
                scale = _float_safe(character.get("default_scale"), default=1.0)
                rotation = 0.0
                opacity = 1.0
                z_index = _int_safe(character.get("z_layer"), default=index)
                emotion = "neutral"
                pose = "idle"

            is_active = bool(active_speaker_id and active_speaker_id == char_id)
            blink_now = ((time_ms // 480) % 9) == 0
            if blink_now:
                state = "blink"
                viseme = "X"
            elif is_active:
                state = "talk"
                viseme = _clean(active_mouth).upper() or "X"
            else:
                state = "idle"
                viseme = "X"

            planned.append(
                {
                    "character_id": char_id,
                    "name": _clean(character.get("name")) or f"Speaker {index + 1}",
                    "x_norm": max(0.02, min(x_norm, 0.98)),
                    "y_norm": max(0.05, min(y_norm, 0.98)),
                    "scale": max(0.2, scale * (1.08 if is_active else 1.0)),
                    "rotation": rotation,
                    "opacity": max(0.0, min(opacity, 1.0)),
                    "z_index": z_index,
                    "emotion": emotion,
                    "pose": pose,
                    "state": state,
                    "viseme": viseme,
                    "is_active": is_active,
                    "duration_ms": duration_ms,
                    "t_ms": time_ms,
                }
            )
        planned.sort(key=lambda item: _int_safe(item.get("z_index"), default=0))
        return planned


def _interpolate_keyframes(
    *,
    keyframes: list[object],
    t_ms: int,
    defaults: dict[str, float | int],
) -> dict[str, object]:
    frames = [frame for frame in keyframes if isinstance(frame, dict)]
    if not frames:
        return dict(defaults)
    frames.sort(key=lambda frame: _int_safe(frame.get("t_ms"), default=0))
    if t_ms <= _int_safe(frames[0].get("t_ms"), default=0):
        return {**defaults, **frames[0]}
    if t_ms >= _int_safe(frames[-1].get("t_ms"), default=0):
        return {**defaults, **frames[-1]}

    prev = frames[0]
    nxt = frames[-1]
    for idx in range(1, len(frames)):
        candidate = frames[idx]
        if _int_safe(candidate.get("t_ms"), default=0) >= t_ms:
            nxt = candidate
            prev = frames[idx - 1]
            break
    start_ms = _int_safe(prev.get("t_ms"), default=0)
    end_ms = max(start_ms + 1, _int_safe(nxt.get("t_ms"), default=start_ms + 1))
    raw_ratio = float(t_ms - start_ms) / float(end_ms - start_ms)
    eased_ratio = _ease(raw_ratio, _clean(nxt.get("ease")).lower() or "linear")

    out: dict[str, object] = dict(defaults)
    for key, value in prev.items():
        if key not in {"t_ms", "ease"}:
            out[key] = value
    for key, value in nxt.items():
        if key in {"t_ms", "ease"}:
            continue
        prev_value = prev.get(key, out.get(key))
        if isinstance(prev_value, (int, float)) and isinstance(value, (int, float)):
            interpolated = float(prev_value) + ((float(value) - float(prev_value)) * eased_ratio)
            if isinstance(prev_value, int) and isinstance(value, int):
                out[key] = int(round(interpolated))
            else:
                out[key] = interpolated
        else:
            out[key] = prev_value if eased_ratio < 0.5 else value
    return out


def _ease(ratio: float, ease_name: str) -> float:
    clamped = max(0.0, min(float(ratio), 1.0))
    if ease_name == "ease_in":
        return clamped * clamped
    if ease_name == "ease_out":
        return 1.0 - ((1.0 - clamped) * (1.0 - clamped))
    if ease_name == "ease_in_out":
        if clamped < 0.5:
            return 2.0 * clamped * clamped
        return 1.0 - (((-2.0 * clamped) + 2.0) ** 2) / 2.0
    return clamped


def _legacy_camera_transform(*, camera_move: str, progress: float) -> tuple[float, float, float]:
    move = _clean(camera_move).lower()
    if move == "push_in":
        return 0.0, -2.0, 1.0 + (0.08 * progress)
    if move == "pull_out":
        return 0.0, 1.0, 1.08 - (0.08 * progress)
    if move == "pan_left":
        return -24.0 * progress, 0.0, 1.0
    if move == "pan_right":
        return 24.0 * progress, 0.0, 1.0
    return 0.0, 0.0, 1.0


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
