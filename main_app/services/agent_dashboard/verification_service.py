from __future__ import annotations

from typing import Any

from main_app.contracts import VerificationIssue, VerificationSummary
from main_app.shared.slideshow.representation_normalizer import SUPPORTED_REPRESENTATIONS
from main_app.models import AgentAssetResult
from main_app.services.agent_dashboard.artifact_adapter import (
    ARTIFACT_AUDIO_OVERVIEW_AUDIO,
    ARTIFACT_AUDIO_OVERVIEW_PAYLOAD,
    ARTIFACT_CARTOON_OUTPUTS,
    ARTIFACT_CARTOON_PAYLOAD,
    ARTIFACT_FLASHCARDS_CARDS,
    ARTIFACT_MINDMAP_TREE,
    ARTIFACT_QUIZ_DATA,
    ARTIFACT_REPORT_TEXT,
    ARTIFACT_SLIDESHOW_SLIDES,
    ARTIFACT_TABLE_DATA,
    ARTIFACT_TOPIC_TEXT,
    ARTIFACT_VIDEO_AUDIO,
    ARTIFACT_VIDEO_PAYLOAD,
    legacy_result_to_artifact,
)
from main_app.services.agent_dashboard.error_codes import E_VERIFY_FAILED
from main_app.services.agent_dashboard.error_codes import (
    E_ARTIFACT_SCHEMA_MISMATCH,
    E_VERIFY_PROFILE_UNKNOWN,
)
from main_app.services.agent_dashboard.tool_registry import AgentToolDefinition


VERIFY_PROFILE_TEXT = "text_asset_verify"
VERIFY_PROFILE_STRUCTURED = "structured_asset_verify"
VERIFY_PROFILE_MEDIA = "media_asset_verify"


def verify_asset_result(*, result: AgentAssetResult, tool: AgentToolDefinition) -> VerificationSummary:
    profile, warning_issue = _verify_profile(tool)
    schema_issues = _schema_gate(result=result, tool=tool)
    if profile == VERIFY_PROFILE_TEXT:
        summary = _verify_text_asset(result=result, tool=tool)
    elif profile == VERIFY_PROFILE_MEDIA:
        summary = _verify_media_asset(result=result, tool=tool)
    else:
        summary = _verify_structured_asset(result=result, tool=tool)
    issues = summary.get("issues", []) if isinstance(summary.get("issues"), list) else []
    checks = summary.get("checks_run", []) if isinstance(summary.get("checks_run"), list) else []
    if warning_issue is not None:
        issues.append(warning_issue)
        checks.append("verify_profile_fallback")
    if schema_issues:
        issues.extend(schema_issues)
        checks.append("artifact_schema_gate")
    has_error = any(str(issue.get("severity", "")).lower() == "error" for issue in issues if isinstance(issue, dict))
    summary["issues"] = issues
    summary["checks_run"] = checks
    summary["status"] = "failed" if has_error else "passed"
    return summary


def verification_passed(summary: VerificationSummary) -> bool:
    return str(summary.get("status", "")).strip().lower() == "passed"


def verification_error_message(summary: VerificationSummary) -> str:
    issues = summary.get("issues", [])
    if not isinstance(issues, list):
        return "Verification failed."
    errors = [issue for issue in issues if isinstance(issue, dict) and str(issue.get("severity", "")).lower() == "error"]
    if not errors:
        return "Verification failed."
    messages = [str(issue.get("message", "")).strip() for issue in errors if str(issue.get("message", "")).strip()]
    return "Verification failed: " + "; ".join(messages[:3]) if messages else "Verification failed."


def _verify_text_asset(*, result: AgentAssetResult, tool: AgentToolDefinition) -> VerificationSummary:
    checks_run: list[str] = []
    issues: list[VerificationIssue] = []

    section_key = _primary_key_for_intent(tool.intent)
    primary_data = _section_data(result=result, key=section_key)
    checks_run.append("primary_section_present")
    if primary_data is None:
        issues.append(_issue("Primary artifact section is missing.", f"sections.{section_key}"))
        return _summary(checks_run=checks_run, issues=issues)

    checks_run.append("primary_text_non_empty")
    text = str(primary_data).strip()
    if not text:
        issues.append(_issue("Primary text content is empty.", f"sections.{section_key}.data"))
    checks_run.append("primary_text_min_length")
    if len(text) < 40:
        issues.append(_issue("Primary text content is too short.", f"sections.{section_key}.data"))
    return _summary(checks_run=checks_run, issues=issues)


def _verify_structured_asset(*, result: AgentAssetResult, tool: AgentToolDefinition) -> VerificationSummary:
    checks_run: list[str] = []
    issues: list[VerificationIssue] = []
    section_key = _primary_key_for_intent(tool.intent)
    primary_data = _section_data(result=result, key=section_key)

    checks_run.append("primary_section_present")
    if primary_data is None:
        issues.append(_issue("Primary artifact section is missing.", f"sections.{section_key}"))
        return _summary(checks_run=checks_run, issues=issues)

    intent = _normalize(tool.intent)
    if intent == "mindmap":
        checks_run.append("mindmap_root_name")
        if not isinstance(primary_data, dict) or not str(primary_data.get("name", "")).strip():
            issues.append(_issue("Mindmap root node must include `name`.", f"sections.{section_key}.data.name"))
    elif intent == "flashcards":
        checks_run.append("flashcards_cards_non_empty")
        cards = primary_data.get("cards", []) if isinstance(primary_data, dict) else []
        if not isinstance(cards, list) or not cards:
            issues.append(_issue("Flashcards list is empty.", f"sections.{section_key}.data.cards"))
        else:
            first = cards[0] if isinstance(cards[0], dict) else {}
            if not str(first.get("question", "")).strip() or not str(first.get("short_answer", "")).strip():
                issues.append(_issue("Flashcards must contain `question` and `short_answer`.", f"sections.{section_key}.data.cards[0]"))
    elif intent == "data table":
        checks_run.append("table_columns_rows")
        columns = primary_data.get("columns", []) if isinstance(primary_data, dict) else []
        rows = primary_data.get("rows", []) if isinstance(primary_data, dict) else []
        if not isinstance(columns, list) or not columns:
            issues.append(_issue("Data table columns are missing.", f"sections.{section_key}.data.columns"))
        if not isinstance(rows, list) or not rows:
            issues.append(_issue("Data table rows are missing.", f"sections.{section_key}.data.rows"))
    elif intent == "quiz":
        checks_run.append("quiz_questions")
        questions = primary_data.get("questions", []) if isinstance(primary_data, dict) else []
        if not isinstance(questions, list) or not questions:
            issues.append(_issue("Quiz questions are missing.", f"sections.{section_key}.data.questions"))
        else:
            first = questions[0] if isinstance(questions[0], dict) else {}
            options = first.get("options", []) if isinstance(first, dict) else []
            if not isinstance(options, list) or len(options) < 2:
                issues.append(_issue("Each quiz question needs at least two options.", f"sections.{section_key}.data.questions[0].options"))
    elif intent == "slideshow":
        checks_run.append("slideshow_slides")
        slides = primary_data.get("slides", []) if isinstance(primary_data, dict) else []
        if not isinstance(slides, list) or not slides:
            issues.append(_issue("Slideshow slides are missing.", f"sections.{section_key}.data.slides"))
        else:
            checks_run.append("slideshow_representation_contract")
            allowed = set(SUPPORTED_REPRESENTATIONS)
            for index, slide in enumerate(slides):
                if not isinstance(slide, dict):
                    issues.append(_issue("Each slide must be an object.", f"sections.{section_key}.data.slides[{index}]"))
                    continue
                representation = " ".join(str(slide.get("representation", "bullet")).split()).strip().lower()
                if representation not in allowed:
                    issues.append(
                        _issue(
                            f"Slide representation `{representation}` is not allowed.",
                            f"sections.{section_key}.data.slides[{index}].representation",
                        )
                    )
                    continue
                bullets = slide.get("bullets", [])
                if not isinstance(bullets, list) or not any(str(item).strip() for item in bullets):
                    issues.append(
                        _issue(
                            "Each slide must include non-empty bullets after normalization.",
                            f"sections.{section_key}.data.slides[{index}].bullets",
                        )
                    )
                layout_payload = slide.get("layout_payload", {})
                if not isinstance(layout_payload, dict):
                    issues.append(
                        _issue(
                            "Slide layout_payload must be an object.",
                            f"sections.{section_key}.data.slides[{index}].layout_payload",
                        )
                    )
                    continue
                _validate_slide_layout_payload(
                    representation=representation,
                    layout_payload=layout_payload,
                    issues=issues,
                    path_prefix=f"sections.{section_key}.data.slides[{index}].layout_payload",
                )
    return _summary(checks_run=checks_run, issues=issues)


def _verify_media_asset(*, result: AgentAssetResult, tool: AgentToolDefinition) -> VerificationSummary:
    checks_run: list[str] = []
    issues: list[VerificationIssue] = []
    intent = _normalize(tool.intent)

    if intent == "video":
        payload = _section_data(result=result, key=ARTIFACT_VIDEO_PAYLOAD)
        checks_run.append("video_payload_present")
        if payload is None:
            issues.append(_issue("Video payload section is missing.", f"sections.{ARTIFACT_VIDEO_PAYLOAD}"))
        else:
            slides = payload.get("slides", []) if isinstance(payload, dict) else []
            scripts = payload.get("slide_scripts", []) if isinstance(payload, dict) else []
            checks_run.append("video_slides_scripts_present")
            if not isinstance(slides, list) or not slides:
                issues.append(_issue("Video slides are missing.", f"sections.{ARTIFACT_VIDEO_PAYLOAD}.data.slides"))
            if not isinstance(scripts, list) or not scripts:
                issues.append(_issue("Video slide scripts are missing.", f"sections.{ARTIFACT_VIDEO_PAYLOAD}.data.slide_scripts"))
            checks_run.append("video_speaker_roster_present")
            speaker_roster = payload.get("speaker_roster", []) if isinstance(payload, dict) else []
            if not isinstance(speaker_roster, list) or len(speaker_roster) < 2:
                issues.append(
                    _issue(
                        "Video speaker_roster must include at least 2 speakers.",
                        f"sections.{ARTIFACT_VIDEO_PAYLOAD}.data.speaker_roster",
                    )
                )
            checks_run.append("video_conversation_timeline_present")
            timeline = payload.get("conversation_timeline", {}) if isinstance(payload, dict) else {}
            if not isinstance(timeline, dict):
                issues.append(
                    _issue(
                        "Video conversation_timeline must be an object.",
                        f"sections.{ARTIFACT_VIDEO_PAYLOAD}.data.conversation_timeline",
                    )
                )
            else:
                turns = timeline.get("turns", [])
                if not isinstance(turns, list) or not turns:
                    issues.append(
                        _issue(
                            "Video conversation_timeline.turns must be non-empty.",
                            f"sections.{ARTIFACT_VIDEO_PAYLOAD}.data.conversation_timeline.turns",
                        )
                    )
                else:
                    _validate_video_timeline_turns(
                        turns=turns,
                        issues=issues,
                        path_prefix=f"sections.{ARTIFACT_VIDEO_PAYLOAD}.data.conversation_timeline.turns",
                    )
                segments = timeline.get("audio_segments", [])
                if isinstance(segments, list) and segments:
                    _validate_video_timeline_segments(
                        segments=segments,
                        issues=issues,
                        path_prefix=f"sections.{ARTIFACT_VIDEO_PAYLOAD}.data.conversation_timeline.audio_segments",
                    )
                    if isinstance(turns, list) and turns and len(segments) < len(turns):
                        issues.append(
                            _issue(
                                "Audio segment count is lower than timeline turn count.",
                                f"sections.{ARTIFACT_VIDEO_PAYLOAD}.data.conversation_timeline.audio_segments",
                            )
                        )
        checks_run.append("video_audio_artifact")
        audio_data = _section_data(result=result, key=ARTIFACT_VIDEO_AUDIO)
        if audio_data is None and result.audio_bytes is None and not result.audio_error:
            issues.append(_issue("Video audio output is missing.", f"sections.{ARTIFACT_VIDEO_AUDIO}"))

    if intent == "cartoon_shorts":
        payload = _section_data(result=result, key=ARTIFACT_CARTOON_PAYLOAD)
        checks_run.append("cartoon_payload_present")
        if payload is None:
            issues.append(_issue("Cartoon shorts payload section is missing.", f"sections.{ARTIFACT_CARTOON_PAYLOAD}"))
        else:
            checks_run.append("cartoon_timeline_present")
            timeline = payload.get("timeline", {}) if isinstance(payload, dict) else {}
            metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}
            metadata_map = metadata if isinstance(metadata, dict) else {}
            timeline_schema_version = _clean_text(payload.get("timeline_schema_version") or metadata_map.get("timeline_schema_version") or "v1").lower()
            if not isinstance(timeline, dict):
                issues.append(_issue("Cartoon timeline must be an object.", f"sections.{ARTIFACT_CARTOON_PAYLOAD}.data.timeline"))
            else:
                scenes = timeline.get("scenes", [])
                if not isinstance(scenes, list) or not scenes:
                    issues.append(
                        _issue(
                            "Cartoon timeline.scenes must be non-empty.",
                            f"sections.{ARTIFACT_CARTOON_PAYLOAD}.data.timeline.scenes",
                        )
                    )
                else:
                    previous_scene_index = 0
                    for idx, scene in enumerate(scenes):
                        if not isinstance(scene, dict):
                            issues.append(_issue("Each scene must be an object.", f"sections.{ARTIFACT_CARTOON_PAYLOAD}.data.timeline.scenes[{idx}]"))
                            continue
                        scene_index = _safe_int(scene.get("scene_index"), default=-1)
                        if scene_index <= 0:
                            issues.append(
                                _issue(
                                    "Scene scene_index must be > 0.",
                                    f"sections.{ARTIFACT_CARTOON_PAYLOAD}.data.timeline.scenes[{idx}].scene_index",
                                )
                            )
                        if previous_scene_index > 0 and scene_index < previous_scene_index:
                            issues.append(
                                _issue(
                                    "Scene indices must be monotonic.",
                                    f"sections.{ARTIFACT_CARTOON_PAYLOAD}.data.timeline.scenes[{idx}].scene_index",
                                )
                            )
                        previous_scene_index = max(previous_scene_index, scene_index)
                        turns = scene.get("turns", [])
                        if not isinstance(turns, list) or not turns:
                            issues.append(
                                _issue(
                                    "Each scene must include turns.",
                                    f"sections.{ARTIFACT_CARTOON_PAYLOAD}.data.timeline.scenes[{idx}].turns",
                                )
                            )
                        else:
                            _validate_video_timeline_turns(
                                turns=turns,
                                issues=issues,
                                path_prefix=f"sections.{ARTIFACT_CARTOON_PAYLOAD}.data.timeline.scenes[{idx}].turns",
                            )
                        if timeline_schema_version == "v2":
                            _validate_cartoon_v2_scene(
                                scene=scene,
                                issues=issues,
                                path_prefix=f"sections.{ARTIFACT_CARTOON_PAYLOAD}.data.timeline.scenes[{idx}]",
                            )
            checks_run.append("cartoon_roster_present")
            character_roster = payload.get("character_roster", []) if isinstance(payload, dict) else []
            if not isinstance(character_roster, list) or len(character_roster) < 2:
                issues.append(
                    _issue(
                        "Cartoon character_roster must include at least 2 characters.",
                        f"sections.{ARTIFACT_CARTOON_PAYLOAD}.data.character_roster",
                    )
                )
            elif timeline_schema_version == "v2":
                checks_run.append("cartoon_v2_character_assets")
                for index, character in enumerate(character_roster):
                    if not isinstance(character, dict):
                        issues.append(
                            _issue(
                                "Each cartoon character must be an object.",
                                f"sections.{ARTIFACT_CARTOON_PAYLOAD}.data.character_roster[{index}]",
                            )
                        )
                        continue
                    _validate_cartoon_v2_character_assets(
                        character=character,
                        issues=issues,
                        path_prefix=f"sections.{ARTIFACT_CARTOON_PAYLOAD}.data.character_roster[{index}]",
                    )
        checks_run.append("cartoon_outputs_artifact_optional")
        _ = _section_data(result=result, key=ARTIFACT_CARTOON_OUTPUTS)

    if intent == "audio_overview":
        payload = _section_data(result=result, key=ARTIFACT_AUDIO_OVERVIEW_PAYLOAD)
        checks_run.append("audio_overview_payload_present")
        if payload is None:
            issues.append(_issue("Audio overview payload section is missing.", f"sections.{ARTIFACT_AUDIO_OVERVIEW_PAYLOAD}"))
        else:
            dialogue = payload.get("dialogue", []) if isinstance(payload, dict) else []
            if not isinstance(dialogue, list) or not dialogue:
                issues.append(_issue("Audio overview dialogue is missing.", f"sections.{ARTIFACT_AUDIO_OVERVIEW_PAYLOAD}.data.dialogue"))
        checks_run.append("audio_overview_audio_artifact")
        audio_data = _section_data(result=result, key=ARTIFACT_AUDIO_OVERVIEW_AUDIO)
        if audio_data is None and result.audio_bytes is None and not result.audio_error:
            issues.append(_issue("Audio overview MP3 output is missing.", f"sections.{ARTIFACT_AUDIO_OVERVIEW_AUDIO}"))

    return _summary(checks_run=checks_run, issues=issues)


def _summary(*, checks_run: list[str], issues: list[VerificationIssue]) -> VerificationSummary:
    has_error = any(str(issue.get("severity", "")).lower() == "error" for issue in issues)
    return {
        "status": "failed" if has_error else "passed",
        "issues": issues,
        "checks_run": checks_run,
    }


def _issue(message: str, path: str) -> VerificationIssue:
    return {
        "code": E_VERIFY_FAILED,
        "severity": "error",
        "message": message,
        "path": path,
    }


def _warning_issue(message: str, path: str) -> VerificationIssue:
    return {
        "code": E_VERIFY_PROFILE_UNKNOWN,
        "severity": "warning",
        "message": message,
        "path": path,
    }


def _validate_video_timeline_turns(*, turns: list[object], issues: list[VerificationIssue], path_prefix: str) -> None:
    previous_start = -1
    for index, turn in enumerate(turns):
        path = f"{path_prefix}[{index}]"
        if not isinstance(turn, dict):
            issues.append(_issue("Each timeline turn must be an object.", path))
            continue
        speaker = " ".join(str(turn.get("speaker", "")).split()).strip()
        text = " ".join(str(turn.get("text", "")).split()).strip()
        if not speaker:
            issues.append(_issue("Timeline turn speaker is required.", f"{path}.speaker"))
        if not text:
            issues.append(_issue("Timeline turn text is required.", f"{path}.text"))
        start_ms = _safe_int(turn.get("start_ms"), default=-1)
        end_ms = _safe_int(turn.get("end_ms"), default=-1)
        if start_ms < 0 or end_ms < 0:
            issues.append(_issue("Timeline turn start_ms/end_ms must be non-negative integers.", path))
            continue
        if end_ms < start_ms:
            issues.append(_issue("Timeline turn end_ms must be >= start_ms.", path))
        if previous_start > start_ms:
            issues.append(_issue("Timeline turns must be monotonic by start_ms.", path))
        previous_start = start_ms
        visual_ref = turn.get("visual_ref", {})
        if not isinstance(visual_ref, dict):
            issues.append(_issue("Timeline turn visual_ref must be an object.", f"{path}.visual_ref"))
            continue
        slide_index = _safe_int(visual_ref.get("slide_index"), default=-1)
        if slide_index <= 0:
            issues.append(_issue("Timeline turn visual_ref.slide_index must be > 0.", f"{path}.visual_ref.slide_index"))


def _validate_video_timeline_segments(*, segments: list[object], issues: list[VerificationIssue], path_prefix: str) -> None:
    previous_start = -1
    for index, segment in enumerate(segments):
        path = f"{path_prefix}[{index}]"
        if not isinstance(segment, dict):
            issues.append(_issue("Each audio segment must be an object.", path))
            continue
        segment_ref = " ".join(str(segment.get("segment_ref", "")).split()).strip()
        if not segment_ref:
            issues.append(_issue("Audio segment segment_ref is required.", f"{path}.segment_ref"))
        start_ms = _safe_int(segment.get("start_ms"), default=-1)
        end_ms = _safe_int(segment.get("end_ms"), default=-1)
        if start_ms < 0 or end_ms < 0:
            issues.append(_issue("Audio segment start_ms/end_ms must be non-negative integers.", path))
            continue
        if end_ms < start_ms:
            issues.append(_issue("Audio segment end_ms must be >= start_ms.", path))
        if previous_start > start_ms:
            issues.append(_issue("Audio segments must be monotonic by start_ms.", path))
        previous_start = start_ms


def _validate_cartoon_v2_scene(*, scene: dict[str, Any], issues: list[VerificationIssue], path_prefix: str) -> None:
    camera_track = scene.get("camera_track", {})
    if not isinstance(camera_track, dict):
        issues.append(_issue("cartoon v2 scene.camera_track must be an object.", f"{path_prefix}.camera_track"))
    else:
        camera_keyframes = camera_track.get("keyframes", [])
        if not isinstance(camera_keyframes, list) or not camera_keyframes:
            issues.append(_issue("cartoon v2 scene.camera_track.keyframes must be non-empty.", f"{path_prefix}.camera_track.keyframes"))
        else:
            _validate_monotonic_keyframes(
                keyframes=camera_keyframes,
                issues=issues,
                path_prefix=f"{path_prefix}.camera_track.keyframes",
            )

    character_tracks = scene.get("character_tracks", [])
    if not isinstance(character_tracks, list) or not character_tracks:
        issues.append(_issue("cartoon v2 scene.character_tracks must be non-empty.", f"{path_prefix}.character_tracks"))
        return
    for index, track in enumerate(character_tracks):
        track_path = f"{path_prefix}.character_tracks[{index}]"
        if not isinstance(track, dict):
            issues.append(_issue("cartoon v2 character_track must be an object.", track_path))
            continue
        character_id = _clean_text(track.get("character_id"))
        if not character_id:
            issues.append(_issue("cartoon v2 character_track.character_id is required.", f"{track_path}.character_id"))
        keyframes = track.get("keyframes", [])
        if not isinstance(keyframes, list) or not keyframes:
            issues.append(_issue("cartoon v2 character_track.keyframes must be non-empty.", f"{track_path}.keyframes"))
            continue
        _validate_monotonic_keyframes(keyframes=keyframes, issues=issues, path_prefix=f"{track_path}.keyframes")


def _validate_monotonic_keyframes(*, keyframes: list[object], issues: list[VerificationIssue], path_prefix: str) -> None:
    previous_t = -1
    for index, keyframe in enumerate(keyframes):
        keyframe_path = f"{path_prefix}[{index}]"
        if not isinstance(keyframe, dict):
            issues.append(_issue("Keyframe must be an object.", keyframe_path))
            continue
        t_ms = _safe_int(keyframe.get("t_ms"), default=-1)
        if t_ms < 0:
            issues.append(_issue("Keyframe t_ms must be >= 0.", f"{keyframe_path}.t_ms"))
            continue
        if previous_t > t_ms:
            issues.append(_issue("Keyframes must be monotonic by t_ms.", keyframe_path))
        previous_t = t_ms


def _validate_cartoon_v2_character_assets(
    *,
    character: dict[str, Any],
    issues: list[VerificationIssue],
    path_prefix: str,
) -> None:
    if _clean_text(character.get("asset_mode")).lower() != "lottie_cache":
        issues.append(_issue("cartoon v2 character asset_mode must be `lottie_cache`.", f"{path_prefix}.asset_mode"))
    if not _clean_text(character.get("lottie_source")):
        issues.append(_issue("cartoon v2 character lottie_source is required.", f"{path_prefix}.lottie_source"))
    if not _clean_text(character.get("cache_root")):
        issues.append(_issue("cartoon v2 character cache_root is required.", f"{path_prefix}.cache_root"))
    state_map = character.get("state_map", {})
    if not isinstance(state_map, dict) or not state_map:
        issues.append(_issue("cartoon v2 character state_map must be a non-empty object.", f"{path_prefix}.state_map"))


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _safe_int(value: object, *, default: int) -> int:
    try:
        if isinstance(value, bool):
            return default
        if isinstance(value, (int, float, str)):
            return int(value)
        return int(str(value))
    except (TypeError, ValueError):
        return default


def _verify_profile(tool: AgentToolDefinition) -> tuple[str, VerificationIssue | None]:
    spec = tool.execution_spec if isinstance(tool.execution_spec, dict) else {}
    profile = " ".join(str(spec.get("verify_profile", "")).split()).strip().lower()
    if profile in {VERIFY_PROFILE_TEXT, VERIFY_PROFILE_STRUCTURED, VERIFY_PROFILE_MEDIA}:
        return profile, None
    intent = _normalize(tool.intent)
    if intent in {"topic", "report"}:
        inferred = VERIFY_PROFILE_TEXT
    elif intent in {"video", "cartoon_shorts", "audio_overview"}:
        inferred = VERIFY_PROFILE_MEDIA
    else:
        inferred = VERIFY_PROFILE_STRUCTURED
    if profile:
        return inferred, _warning_issue(
            f"Unknown verify profile `{profile}`. Fallback `{inferred}` was applied.",
            "execution_spec.verify_profile",
        )
    return inferred, None


def _section_data(*, result: AgentAssetResult, key: str) -> Any:
    artifact = result.artifact if isinstance(result.artifact, dict) else legacy_result_to_artifact(result)
    sections = artifact.get("sections", [])
    if not isinstance(sections, list):
        return None
    for section in sections:
        if not isinstance(section, dict):
            continue
        section_key = " ".join(str(section.get("key", "")).split()).strip()
        if section_key == key:
            return section.get("data")
    return None


def _primary_key_for_intent(intent: str) -> str:
    normalized = _normalize(intent)
    mapping = {
        "topic": ARTIFACT_TOPIC_TEXT,
        "mindmap": ARTIFACT_MINDMAP_TREE,
        "flashcards": ARTIFACT_FLASHCARDS_CARDS,
        "data table": ARTIFACT_TABLE_DATA,
        "quiz": ARTIFACT_QUIZ_DATA,
        "slideshow": ARTIFACT_SLIDESHOW_SLIDES,
        "video": ARTIFACT_VIDEO_PAYLOAD,
        "cartoon_shorts": ARTIFACT_CARTOON_PAYLOAD,
        "audio_overview": ARTIFACT_AUDIO_OVERVIEW_PAYLOAD,
        "report": ARTIFACT_REPORT_TEXT,
    }
    return mapping.get(normalized, f"artifact.{normalized}.primary")


def _normalize(value: str) -> str:
    return " ".join(str(value).split()).strip().lower()


def _validate_slide_layout_payload(
    *,
    representation: str,
    layout_payload: dict[str, Any],
    issues: list[VerificationIssue],
    path_prefix: str,
) -> None:
    if representation == "bullet":
        items = layout_payload.get("items", [])
        if not isinstance(items, list):
            issues.append(_issue("Bullet layout requires `items` list.", f"{path_prefix}.items"))
        return
    if representation == "two_column":
        _require_text_field(layout_payload, "left_title", issues, path_prefix)
        _require_text_field(layout_payload, "right_title", issues, path_prefix)
        _require_list_field(layout_payload, "left_items", issues, path_prefix)
        _require_list_field(layout_payload, "right_items", issues, path_prefix)
        return
    if representation == "timeline":
        events = layout_payload.get("events", [])
        if not isinstance(events, list) or not events:
            issues.append(_issue("Timeline layout requires non-empty `events` list.", f"{path_prefix}.events"))
        return
    if representation == "comparison":
        _require_text_field(layout_payload, "left_title", issues, path_prefix)
        _require_text_field(layout_payload, "right_title", issues, path_prefix)
        _require_list_field(layout_payload, "left_points", issues, path_prefix)
        _require_list_field(layout_payload, "right_points", issues, path_prefix)
        return
    if representation == "process_flow":
        steps = layout_payload.get("steps", [])
        if not isinstance(steps, list) or not steps:
            issues.append(_issue("Process flow layout requires non-empty `steps` list.", f"{path_prefix}.steps"))
        return
    if representation == "metric_cards":
        cards = layout_payload.get("cards", [])
        if not isinstance(cards, list) or not cards:
            issues.append(_issue("Metric cards layout requires non-empty `cards` list.", f"{path_prefix}.cards"))


def _require_text_field(
    payload: dict[str, Any],
    key: str,
    issues: list[VerificationIssue],
    path_prefix: str,
) -> None:
    value = payload.get(key)
    if not str(value or "").strip():
        issues.append(_issue(f"Missing `{key}` text value.", f"{path_prefix}.{key}"))


def _require_list_field(
    payload: dict[str, Any],
    key: str,
    issues: list[VerificationIssue],
    path_prefix: str,
) -> None:
    value = payload.get(key)
    if not isinstance(value, list) or not value:
        issues.append(_issue(f"Missing non-empty `{key}` list.", f"{path_prefix}.{key}"))


def _schema_gate(*, result: AgentAssetResult, tool: AgentToolDefinition) -> list[VerificationIssue]:
    intent = _normalize(tool.intent)
    section_key = _primary_key_for_intent(intent)
    primary_data = _section_data(result=result, key=section_key)
    issues: list[VerificationIssue] = []
    if primary_data is None:
        issues.append(
            {
                "code": E_ARTIFACT_SCHEMA_MISMATCH,
                "severity": "error",
                "message": "Primary artifact data is missing for schema validation.",
                "path": f"sections.{section_key}",
            }
        )
        return issues
    if intent in {"mindmap", "flashcards", "data table", "quiz", "slideshow", "video", "audio_overview"} and not isinstance(primary_data, dict):
        issues.append(
            {
                "code": E_ARTIFACT_SCHEMA_MISMATCH,
                "severity": "error",
                "message": "Primary artifact data must be an object for this intent.",
                "path": f"sections.{section_key}.data",
            }
        )
    if intent in {"topic", "report"} and not isinstance(primary_data, str):
        issues.append(
            {
                "code": E_ARTIFACT_SCHEMA_MISMATCH,
                "severity": "error",
                "message": "Primary artifact data must be text for this intent.",
                "path": f"sections.{section_key}.data",
            }
        )
    return issues
