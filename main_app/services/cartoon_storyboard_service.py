from __future__ import annotations

import json
from typing import Protocol, cast

from main_app.contracts import (
    CartoonCameraMove,
    CartoonCharacterSpec,
    CartoonDialogueTurn,
    CartoonMood,
    CartoonScene,
    CartoonShortType,
    CartoonShotType,
    CartoonTimeline,
    CartoonTransitionType,
)
from main_app.models import GroqSettings


class _StoryboardLLMClient(Protocol):
    def call(
        self,
        *,
        settings: GroqSettings,
        messages: list[dict[str, str]],
        task: str,
        label: str,
        topic: str,
    ) -> tuple[str, bool]:
        ...


SHORT_TYPE_OPTIONS: tuple[CartoonShortType, ...] = (
    "educational_explainer",
    "debate_discussion",
    "story_sketch",
    "news_brief",
    "product_pitch",
    "case_study",
)


class CartoonStoryboardService:
    def __init__(self, llm_service: _StoryboardLLMClient) -> None:
        self._llm_service = llm_service

    def generate_timeline(
        self,
        *,
        topic: str,
        idea: str,
        short_type: CartoonShortType,
        character_roster: list[CartoonCharacterSpec],
        scene_count: int,
        settings: GroqSettings,
        language: str,
        use_hinglish_script: bool,
        timeline_schema_version: str = "v1",
    ) -> tuple[CartoonTimeline, str | None, list[str], int, int, str | None]:
        notes: list[str] = []
        schema_version = _normalize_timeline_schema_version(timeline_schema_version)
        prompt = self._build_prompt(
            topic=topic,
            idea=idea,
            short_type=short_type,
            character_roster=character_roster,
            scene_count=scene_count,
            language=language,
            use_hinglish_script=use_hinglish_script,
            timeline_schema_version=schema_version,
        )
        raw_text = ""
        cache_hits = 0
        total_calls = 1
        try:
            raw_text, cache_hit = self._llm_service.call(
                settings=settings,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You create scene-by-scene cartoon short storyboards. "
                            "Return strict JSON only."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                task="cartoon_storyboard",
                label=f"Cartoon Storyboard: {topic}",
                topic=topic,
            )
            cache_hits = 1 if cache_hit else 0
        except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
            notes.append(f"Storyboard LLM fallback used: {exc}")
            timeline = self._fallback_timeline(
                topic=topic,
                idea=idea,
                short_type=short_type,
                character_roster=character_roster,
                scene_count=scene_count,
                timeline_schema_version=schema_version,
            )
            return timeline, None, notes, cache_hits, total_calls, raw_text or None

        timeline, parse_error = self._parse_timeline(raw_text, timeline_schema_version=schema_version)
        if parse_error:
            notes.append(f"Storyboard parse fallback used: {parse_error}")
            timeline = self._fallback_timeline(
                topic=topic,
                idea=idea,
                short_type=short_type,
                character_roster=character_roster,
                scene_count=scene_count,
                timeline_schema_version=schema_version,
            )
            return timeline, None, notes, cache_hits, total_calls, raw_text or None

        return timeline, None, notes, cache_hits, total_calls, raw_text or None

    def _parse_timeline(self, raw_text: str, *, timeline_schema_version: str) -> tuple[CartoonTimeline, str | None]:
        cleaned = " ".join(str(raw_text or "").split()).strip()
        if not cleaned:
            return cast(CartoonTimeline, {}), "Empty storyboard payload."
        try:
            payload = json.loads(raw_text)
        except ValueError as exc:
            return cast(CartoonTimeline, {}), str(exc)
        if not isinstance(payload, dict):
            return cast(CartoonTimeline, {}), "Storyboard payload must be an object."
        scenes_raw = payload.get("scenes", [])
        if not isinstance(scenes_raw, list) or not scenes_raw:
            return cast(CartoonTimeline, {}), "Storyboard scenes missing."
        scenes: list[CartoonScene] = []
        for idx, scene in enumerate(scenes_raw, start=1):
            if not isinstance(scene, dict):
                continue
            turns_raw = scene.get("turns", [])
            turns: list[CartoonDialogueTurn] = []
            if isinstance(turns_raw, list):
                for turn_idx, turn in enumerate(turns_raw):
                    if not isinstance(turn, dict):
                        continue
                    text = _clean(turn.get("text"))
                    speaker_name = _clean(turn.get("speaker_name")) or _clean(turn.get("speaker"))
                    speaker_id = _clean(turn.get("speaker_id")) or speaker_name.lower().replace(" ", "_")
                    if not text or not speaker_id:
                        continue
                    turns.append(
                        cast(
                            CartoonDialogueTurn,
                            {
                                "turn_index": turn_idx,
                                "speaker_id": speaker_id,
                                "speaker_name": speaker_name or speaker_id.replace("_", " ").title(),
                                "text": text,
                                "emotion": _clean(turn.get("emotion")) or "neutral",
                                "estimated_duration_ms": _int_safe(turn.get("estimated_duration_ms"), default=max(2000, len(text) * 80)),
                            },
                        )
                    )
            if not turns:
                continue
            scenes.append(
                cast(
                    CartoonScene,
                    {
                        "scene_index": _int_safe(scene.get("scene_index"), default=idx),
                        "title": _clean(scene.get("title")) or f"Scene {idx}",
                        "hook": _clean(scene.get("hook")),
                        "background_key": _clean(scene.get("background_key")) or "studio_blue",
                        "camera_preset": _clean(scene.get("camera_preset")) or "medium_two_shot",
                        "shot_type": _normalize_shot_type(scene.get("shot_type"), default=_default_shot_type(idx)),
                        "camera_move": _normalize_camera_move(scene.get("camera_move"), default=_default_camera_move(idx)),
                        "transition_in": _normalize_transition(scene.get("transition_in"), default="cut"),
                        "transition_out": _normalize_transition(
                            scene.get("transition_out"),
                            default="crossfade" if idx < len(scenes_raw) else "fade_black",
                        ),
                        "mood": _normalize_mood(scene.get("mood"), default="neutral"),
                        "focus_character_id": _clean(scene.get("focus_character_id")),
                        "duration_ms": max(3000, sum(_int_safe(turn.get("estimated_duration_ms"), default=2500) for turn in turns)),
                        "turns": turns,
                        "visual_notes": _clean(scene.get("visual_notes")),
                        "camera_track": _camera_track_field(scene.get("camera_track")) if timeline_schema_version == "v2" else {},
                        "character_tracks": _character_tracks_field(scene.get("character_tracks")) if timeline_schema_version == "v2" else [],
                        "subtitle_track": _subtitle_track_field(scene.get("subtitle_track")) if timeline_schema_version == "v2" else {},
                    },
                )
            )
        if not scenes:
            return cast(CartoonTimeline, {}), "No valid scenes in storyboard."
        if timeline_schema_version == "v2":
            for scene in scenes:
                camera_track = scene.get("camera_track", {})
                character_tracks = scene.get("character_tracks", [])
                if not isinstance(camera_track, dict) or not isinstance(camera_track.get("keyframes", []), list) or not camera_track.get("keyframes", []):
                    return cast(CartoonTimeline, {}), "Storyboard v2 camera_track missing."
                if not isinstance(character_tracks, list) or not character_tracks:
                    return cast(CartoonTimeline, {}), "Storyboard v2 character_tracks missing."
        total_ms = sum(_int_safe(scene.get("duration_ms"), default=0) for scene in scenes)
        speaker_ids = {
            _clean(turn.get("speaker_id"))
            for scene in scenes
            for turn in cast(list[CartoonDialogueTurn], scene.get("turns", []))
            if _clean(turn.get("speaker_id"))
        }
        return (
            cast(
                CartoonTimeline,
                {
                    "scenes": scenes,
                    "total_duration_ms": total_ms,
                    "scene_count": len(scenes),
                    "speaker_count": len(speaker_ids),
                    "generated_with": "llm_storyboard_v2" if timeline_schema_version == "v2" else "llm_storyboard_v1",
                },
            ),
            None,
        )

    def _fallback_timeline(
        self,
        *,
        topic: str,
        idea: str,
        short_type: CartoonShortType,
        character_roster: list[CartoonCharacterSpec],
        scene_count: int,
        timeline_schema_version: str,
    ) -> CartoonTimeline:
        safe_topic = _clean(topic) or "Topic"
        safe_idea = _clean(idea) or f"A short on {safe_topic}."
        count = max(2, min(int(scene_count), 10))
        scenes: list[CartoonScene] = []
        roster = character_roster or []
        first = roster[0] if roster else cast(CartoonCharacterSpec, {"id": "ava", "name": "Ava"})
        second = roster[1] if len(roster) > 1 else first
        for idx in range(1, count + 1):
            opening = f"{first.get('name', 'Speaker')} introduces {safe_topic}."
            response = f"{second.get('name', 'Speaker')} adds practical insight for {short_type.replace('_', ' ')}."
            closing = f"{first.get('name', 'Speaker')} summarizes: {safe_idea}"
            turns: list[CartoonDialogueTurn] = [
                cast(
                    CartoonDialogueTurn,
                    {
                        "turn_index": 0,
                        "speaker_id": _clean(first.get("id")) or "speaker_a",
                        "speaker_name": _clean(first.get("name")) or "Speaker A",
                        "text": opening,
                        "emotion": "curious",
                        "estimated_duration_ms": 2800,
                    },
                ),
                cast(
                    CartoonDialogueTurn,
                    {
                        "turn_index": 1,
                        "speaker_id": _clean(second.get("id")) or "speaker_b",
                        "speaker_name": _clean(second.get("name")) or "Speaker B",
                        "text": response,
                        "emotion": "excited",
                        "estimated_duration_ms": 3000,
                    },
                ),
                cast(
                    CartoonDialogueTurn,
                    {
                        "turn_index": 2,
                        "speaker_id": _clean(first.get("id")) or "speaker_a",
                        "speaker_name": _clean(first.get("name")) or "Speaker A",
                        "text": closing,
                        "emotion": "neutral",
                        "estimated_duration_ms": 2500,
                    },
                ),
            ]
            scenes.append(
                cast(
                    CartoonScene,
                    {
                        "scene_index": idx,
                        "title": f"Scene {idx}",
                        "hook": safe_idea if idx == 1 else f"Progression {idx}",
                        "background_key": _background_for_short_type(short_type),
                        "camera_preset": "medium_two_shot",
                        "shot_type": _default_shot_type(idx),
                        "camera_move": _default_camera_move(idx),
                        "transition_in": "cut" if idx == 1 else "crossfade",
                        "transition_out": "fade_black" if idx == count else "crossfade",
                        "mood": _default_mood(short_type),
                        "focus_character_id": _clean(first.get("id")) if idx % 2 else _clean(second.get("id")),
                        "duration_ms": sum(_int_safe(turn.get("estimated_duration_ms"), default=2500) for turn in turns),
                        "turns": turns,
                        "visual_notes": f"Template: {short_type}",
                        "camera_track": _default_camera_track(scene_duration_ms=sum(_int_safe(turn.get("estimated_duration_ms"), default=2500) for turn in turns))
                        if timeline_schema_version == "v2"
                        else {},
                        "character_tracks": _default_character_tracks(
                            character_roster=character_roster,
                            scene_duration_ms=sum(_int_safe(turn.get("estimated_duration_ms"), default=2500) for turn in turns),
                        )
                        if timeline_schema_version == "v2"
                        else [],
                        "subtitle_track": {"y_norm": 0.9, "max_lines": 2, "style": "default"} if timeline_schema_version == "v2" else {},
                    },
                )
            )
        total_duration_ms = sum(_int_safe(scene.get("duration_ms"), default=0) for scene in scenes)
        speaker_ids = {
            _clean(turn.get("speaker_id"))
            for scene in scenes
            for turn in cast(list[CartoonDialogueTurn], scene.get("turns", []))
            if _clean(turn.get("speaker_id"))
        }
        return cast(
            CartoonTimeline,
            {
                "scenes": scenes,
                "total_duration_ms": total_duration_ms,
                "scene_count": len(scenes),
                "speaker_count": len(speaker_ids),
                "generated_with": "fallback_storyboard_v2" if timeline_schema_version == "v2" else "fallback_storyboard_v1",
            },
        )

    @staticmethod
    def _build_prompt(
        *,
        topic: str,
        idea: str,
        short_type: CartoonShortType,
        character_roster: list[CartoonCharacterSpec],
        scene_count: int,
        language: str,
        use_hinglish_script: bool,
        timeline_schema_version: str,
    ) -> str:
        characters = []
        for character in character_roster:
            characters.append(
                {
                    "id": _clean(character.get("id")),
                    "name": _clean(character.get("name")),
                    "role": _clean(character.get("role")),
                }
            )
        return (
            f"Topic: {_clean(topic)}\n"
            f"Idea: {_clean(idea)}\n"
            f"Short type: {short_type}\n"
            f"Scene count: {max(2, min(int(scene_count), 10))}\n"
            f"Language: {_clean(language) or 'en'}\n"
            f"Use Roman Hinglish script: {bool(use_hinglish_script)}\n"
            f"Timeline schema version: {timeline_schema_version}\n"
            f"Characters: {json.dumps(characters, ensure_ascii=False)}\n\n"
            "Return strict JSON object with this schema:\n"
            "{\n"
            '  "scenes": [\n'
            "    {\n"
            '      "scene_index": 1,\n'
            '      "title": "scene title",\n'
            '      "hook": "one-line hook",\n'
            '      "background_key": "studio_blue",\n'
            '      "camera_preset": "medium_two_shot",\n'
            '      "shot_type": "medium_two_shot",\n'
            '      "camera_move": "push_in",\n'
            '      "transition_in": "cut",\n'
            '      "transition_out": "crossfade",\n'
            '      "mood": "energetic",\n'
            '      "focus_character_id": "ava",\n'
            '      "visual_notes": "notes",\n'
            '      "camera_track": {"keyframes":[{"t_ms":0,"x":0,"y":0,"zoom":1.0,"rotation":0,"ease":"linear"}]},\n'
            '      "character_tracks": [{"character_id":"ava","keyframes":[{"t_ms":0,"x_norm":0.28,"y_norm":0.72,"scale":1.0,"rotation":0,"pose":"idle","emotion":"neutral","opacity":1.0,"z_index":1,"ease":"linear"}]}],\n'
            '      "subtitle_track": {"y_norm":0.9,"max_lines":2,"style":"default"},\n'
            '      "turns": [\n'
            "        {\n"
            '          "speaker_id": "ava",\n'
            '          "speaker_name": "Ava",\n'
            '          "text": "dialogue line",\n'
            '          "emotion": "neutral",\n'
            '          "estimated_duration_ms": 2400\n'
            "        }\n"
            "      ]\n"
            "    }\n"
            "  ]\n"
            "}\n"
            "Rules: 2-4 speakers, concise lines, educational but engaging. "
            "Use camera/transition metadata to create cinematic but readable pacing. "
            "When timeline schema version is v2, include non-empty camera_track and character_tracks for every scene."
        )


def _camera_track_field(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        keyframes = value.get("keyframes", [])
        if isinstance(keyframes, list):
            normalized_keyframes = [frame for frame in keyframes if isinstance(frame, dict)]
            return {"keyframes": normalized_keyframes}
    return {}


def _character_tracks_field(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    output: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        keyframes = item.get("keyframes", [])
        normalized_keyframes = [frame for frame in keyframes if isinstance(frame, dict)] if isinstance(keyframes, list) else []
        output.append({"character_id": _clean(item.get("character_id")), "keyframes": normalized_keyframes})
    return output


def _subtitle_track_field(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {
        "y_norm": _float_safe(value.get("y_norm"), default=0.9),
        "max_lines": max(1, _int_safe(value.get("max_lines"), default=2)),
        "style": _clean(value.get("style")) or "default",
    }


def _default_camera_track(*, scene_duration_ms: int) -> dict[str, object]:
    safe_duration = max(1000, int(scene_duration_ms))
    return {
        "keyframes": [
            {"t_ms": 0, "x": 0.0, "y": 0.0, "zoom": 1.0, "rotation": 0.0, "ease": "linear"},
            {"t_ms": safe_duration, "x": 12.0, "y": -2.0, "zoom": 1.04, "rotation": 0.0, "ease": "ease_in_out"},
        ]
    }


def _default_character_tracks(
    *,
    character_roster: list[CartoonCharacterSpec],
    scene_duration_ms: int,
) -> list[dict[str, object]]:
    safe_duration = max(1000, int(scene_duration_ms))
    roster = [character for character in character_roster if isinstance(character, dict)]
    if not roster:
        roster = [{"id": "ava"}, {"id": "noah"}]
    output: list[dict[str, object]] = []
    slot_count = max(1, len(roster))
    for index, character in enumerate(roster):
        char_id = _clean(character.get("id")) or f"speaker_{index + 1}"
        x_norm = 0.2 + ((0.6 / max(1, slot_count - 1)) * index) if slot_count > 1 else 0.5
        output.append(
            {
                "character_id": char_id,
                "keyframes": [
                    {
                        "t_ms": 0,
                        "x_norm": x_norm,
                        "y_norm": 0.72,
                        "scale": _float_safe(character.get("default_scale"), default=1.0),
                        "rotation": 0.0,
                        "pose": "idle",
                        "emotion": "neutral",
                        "opacity": 1.0,
                        "z_index": _int_safe(character.get("z_layer"), default=index),
                        "ease": "linear",
                    },
                    {
                        "t_ms": safe_duration,
                        "x_norm": x_norm,
                        "y_norm": 0.72,
                        "scale": _float_safe(character.get("default_scale"), default=1.0),
                        "rotation": 0.0,
                        "pose": "idle",
                        "emotion": "neutral",
                        "opacity": 1.0,
                        "z_index": _int_safe(character.get("z_layer"), default=index),
                        "ease": "ease_in_out",
                    },
                ],
            }
        )
    return output


def _normalize_timeline_schema_version(value: object) -> str:
    if _clean(value).lower() == "v2":
        return "v2"
    return "v1"


def _background_for_short_type(short_type: CartoonShortType) -> str:
    mapping: dict[CartoonShortType, str] = {
        "educational_explainer": "classroom_warm",
        "debate_discussion": "studio_blue",
        "story_sketch": "city_evening",
        "news_brief": "news_desk",
        "product_pitch": "product_stage",
        "case_study": "case_boardroom",
    }
    return mapping.get(short_type, "studio_blue")


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


def _default_mood(short_type: CartoonShortType) -> CartoonMood:
    mapping: dict[CartoonShortType, CartoonMood] = {
        "educational_explainer": "warm",
        "debate_discussion": "tense",
        "story_sketch": "inspiring",
        "news_brief": "neutral",
        "product_pitch": "energetic",
        "case_study": "inspiring",
    }
    return mapping.get(short_type, "neutral")


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
