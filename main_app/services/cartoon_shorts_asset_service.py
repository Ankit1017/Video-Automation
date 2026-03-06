from __future__ import annotations

from typing import cast

from main_app.contracts import (
    CartoonBackgroundStyle,
    CartoonCharacterSpec,
    CartoonFidelityPreset,
    CartoonOutputMode,
    CartoonPayload,
    CartoonQABundleMode,
    CartoonQualityTier,
    CartoonRenderStyle,
    CartoonShowcaseAvatarMode,
    CartoonShortType,
    CartoonStylePreset,
    CartoonTimelineSchemaVersion,
    CartoonTimeline,
)
from main_app.models import CartoonShortsGenerationResult, GroqSettings
from main_app.services.asset_history_service import AssetHistoryService
from main_app.services.cartoon_asset_runtime_service import (
    resolve_asset_runtime_version,
    resolve_pack_kind,
)
from main_app.services.cartoon_character_asset_validator import CartoonCharacterAssetValidator
from main_app.services.cartoon_character_pack_service import CartoonCharacterPackService
from main_app.services.cartoon_flat_asset_validator import CartoonFlatAssetValidator
from main_app.services.cartoon_storyboard_service import CartoonStoryboardService, SHORT_TYPE_OPTIONS
from main_app.services.cartoon_timeline_service import CartoonTimelineService


class CartoonShortsAssetService:
    def __init__(
        self,
        *,
        storyboard_service: CartoonStoryboardService,
        timeline_service: CartoonTimelineService,
        character_pack_service: CartoonCharacterPackService,
        history_service: AssetHistoryService | None = None,
    ) -> None:
        self._storyboard_service = storyboard_service
        self._timeline_service = timeline_service
        self._character_pack_service = character_pack_service
        self._history_service = history_service

    def generate(
        self,
        *,
        topic: str,
        idea: str,
        short_type: str,
        scene_count: int,
        speaker_count: int,
        output_mode: str,
        language: str,
        use_hinglish_script: bool,
        manual_timeline: CartoonTimeline | None = None,
        timeline_schema_version: str = "v1",
        quality_tier: str = "auto",
        render_style: str = "scene",
        background_style: str = "auto",
        fidelity_preset: str = "auto_profile",
        showcase_avatar_mode: str = "auto",
        style_preset: str = "default_scene",
        qa_bundle_mode: str = "auto",
        settings: GroqSettings,
    ) -> CartoonShortsGenerationResult:
        topic_clean = _clean(topic)
        idea_clean = _clean(idea)
        short_type_clean = _normalize_short_type(short_type)
        output_mode_clean = _normalize_output_mode(output_mode)
        timeline_schema_version_clean = _normalize_timeline_schema_version(timeline_schema_version)
        quality_tier_clean = _normalize_quality_tier(quality_tier)
        render_style_clean = _normalize_render_style(render_style)
        background_style_clean = _normalize_background_style(background_style)
        fidelity_preset_clean = _normalize_fidelity_preset(fidelity_preset)
        showcase_avatar_mode_clean = _normalize_showcase_avatar_mode(showcase_avatar_mode)
        style_preset_clean = _normalize_style_preset(style_preset)
        qa_bundle_mode_clean = _normalize_qa_bundle_mode(qa_bundle_mode)
        notes: list[str] = []

        character_roster = self._character_pack_service.load_roster(speaker_count=speaker_count)
        pack_root = self._character_pack_service.pack_root_path()
        asset_runtime_version = resolve_asset_runtime_version(pack_root=pack_root)
        asset_pack_kind = resolve_pack_kind(pack_root=pack_root, runtime_version=asset_runtime_version)
        pack_metadata = self._character_pack_service.pack_metadata()
        cache_hits = 0
        total_calls = 0
        debug_raw = None
        parse_error = None
        motion_warnings: list[str] = []

        if manual_timeline is not None:
            timeline, normalize_notes = self._timeline_service.normalize_timeline(
                timeline=manual_timeline,
                timeline_schema_version=timeline_schema_version_clean,
                character_roster=character_roster,
            )
            notes.extend(normalize_notes)
            notes.append("Timeline source: manual_editor")
        else:
            generated_timeline, stage_error, stage_notes, stage_cache_hits, stage_calls, raw_text = self._storyboard_service.generate_timeline(
                topic=topic_clean,
                idea=idea_clean,
                short_type=short_type_clean,
                character_roster=character_roster,
                scene_count=scene_count,
                settings=settings,
                language=language,
                use_hinglish_script=use_hinglish_script,
                timeline_schema_version=timeline_schema_version_clean,
            )
            cache_hits += stage_cache_hits
            total_calls += stage_calls
            debug_raw = raw_text
            notes.extend(stage_notes)
            if stage_error:
                parse_error = stage_error
            timeline, normalize_notes = self._timeline_service.normalize_timeline(
                timeline=generated_timeline,
                timeline_schema_version=timeline_schema_version_clean,
                character_roster=character_roster,
            )
            notes.extend(normalize_notes)
            notes.append("Timeline source: generated_storyboard")

        if not isinstance(timeline.get("scenes", []), list) or not timeline.get("scenes", []):
            parse_error = parse_error or "Cartoon timeline has no scenes."

        if timeline_schema_version_clean == "v2":
            if asset_runtime_version == "v3_flat_assets_direct":
                validator = CartoonFlatAssetValidator(pack_root=pack_root)
                asset_errors = validator.validate_roster(
                    roster=character_roster,
                    timeline_schema_version=timeline_schema_version_clean,
                )
                if asset_errors:
                    parse_error = parse_error or f"Flat-assets validation failed ({len(asset_errors)} issues)."
                    notes.extend(asset_errors[:60])
                motion_warnings = validator.audit_roster_motion_quality(
                    roster=character_roster,
                    timeline_schema_version=timeline_schema_version_clean,
                )
                motion_warning_summary = validator.motion_quality_summary(
                    roster=character_roster,
                    timeline_schema_version=timeline_schema_version_clean,
                )
                flat_catalog_summary = validator.catalog_summary()
            else:
                validator = CartoonCharacterAssetValidator(
                    pack_root=pack_root,
                    expected_cache_resolution=_clean(pack_metadata.get("cache_resolution")),
                )
                asset_errors = validator.validate_roster(
                    roster=character_roster,
                    require_lottie_cache=True,
                    timeline_schema_version=timeline_schema_version_clean,
                )
                if asset_errors:
                    parse_error = parse_error or f"Character asset validation failed ({len(asset_errors)} issues)."
                    notes.extend(asset_errors[:60])
                motion_warnings = validator.audit_roster_motion_quality(
                    roster=character_roster,
                    timeline_schema_version=timeline_schema_version_clean,
                )
                motion_warning_summary = validator.motion_quality_summary(
                    roster=character_roster,
                    timeline_schema_version=timeline_schema_version_clean,
                )
                flat_catalog_summary = {}
            notes.extend(motion_warnings[:20])
            if len(motion_warnings) > 20:
                notes.append(f"Motion quality warnings truncated: {len(motion_warnings) - 20} additional warning(s).")
            notes.append("Timeline schema version: v2")
        else:
            motion_warning_summary = {}
            flat_catalog_summary = {}
            notes.append("Timeline schema version: v1")
        notes.append(
            (
                "Resolved asset runtime: "
                f"asset_runtime_version={asset_runtime_version}, "
                f"asset_pack_kind={asset_pack_kind}, "
                f"asset_pack_root={pack_root}"
            )
        )
        notes.append(
            (
                "Resolved render config: "
                f"style_preset={style_preset_clean}, "
                f"timeline_schema_version={timeline_schema_version_clean}, "
                f"quality_tier={quality_tier_clean}, "
                f"render_style={render_style_clean}, "
                f"background_style={background_style_clean}, "
                f"fidelity_preset={fidelity_preset_clean}, "
                f"showcase_avatar_mode={showcase_avatar_mode_clean}, "
                f"qa_bundle_mode={qa_bundle_mode_clean}"
            )
        )

        script_markdown = self._script_markdown(
            topic=topic_clean,
            short_type=short_type_clean,
            timeline=timeline,
            character_roster=character_roster,
        )
        payload = cast(
            CartoonPayload,
            {
                "topic": topic_clean,
                "title": f"Cartoon Shorts: {topic_clean}",
                "short_type": short_type_clean,
                "output_mode": output_mode_clean,
                "language": _clean(language) or "en",
                "hinglish_script": bool(use_hinglish_script),
                "character_roster": character_roster,
                "timeline": timeline,
                "output_artifacts": [],
                "script_markdown": script_markdown,
                "timeline_schema_version": timeline_schema_version_clean,
                "quality_tier": quality_tier_clean,
                "render_style": render_style_clean,
                "background_style": background_style_clean,
                "fidelity_preset": fidelity_preset_clean,
                "showcase_avatar_mode": showcase_avatar_mode_clean,
                "style_preset": style_preset_clean,
                "qa_bundle_mode": qa_bundle_mode_clean,
                "metadata": {
                    "idea": idea_clean,
                    "scene_count_requested": max(2, min(int(scene_count), 10)),
                    "speaker_count_requested": max(2, min(int(speaker_count), 4)),
                    "pack": pack_metadata,
                    "timeline_schema_version": timeline_schema_version_clean,
                    "quality_tier": quality_tier_clean,
                    "render_style": render_style_clean,
                    "background_style": background_style_clean,
                    "fidelity_preset": fidelity_preset_clean,
                    "showcase_avatar_mode": showcase_avatar_mode_clean,
                    "style_preset": style_preset_clean,
                    "qa_bundle_mode": qa_bundle_mode_clean,
                    "pack_motion_warning_count": len(motion_warnings),
                    "pack_motion_warning_summary": motion_warning_summary,
                    "asset_runtime_version": asset_runtime_version,
                    "asset_pack_root": str(pack_root),
                    "asset_pack_kind": asset_pack_kind,
                    "flat_assets_catalog_summary": flat_catalog_summary,
                },
            },
        )

        result = CartoonShortsGenerationResult(
            cartoon_payload=payload if not parse_error else payload,
            parse_error=parse_error,
            parse_notes=notes,
            cache_hits=cache_hits,
            total_calls=total_calls,
            debug_raw=debug_raw,
        )
        self._record_history(
            topic=topic_clean,
            idea=idea_clean,
            short_type=short_type_clean,
            output_mode=output_mode_clean,
            scene_count=scene_count,
            speaker_count=speaker_count,
            language=language,
            use_hinglish_script=use_hinglish_script,
            timeline_schema_version=timeline_schema_version_clean,
            quality_tier=quality_tier_clean,
            render_style=render_style_clean,
            background_style=background_style_clean,
            fidelity_preset=fidelity_preset_clean,
            showcase_avatar_mode=showcase_avatar_mode_clean,
            style_preset=style_preset_clean,
            qa_bundle_mode=qa_bundle_mode_clean,
            result=result,
            model=settings.normalized_model,
        )
        return result

    def _record_history(
        self,
        *,
        topic: str,
        idea: str,
        short_type: CartoonShortType,
        output_mode: CartoonOutputMode,
        scene_count: int,
        speaker_count: int,
        language: str,
        use_hinglish_script: bool,
        timeline_schema_version: CartoonTimelineSchemaVersion,
        quality_tier: CartoonQualityTier,
        render_style: CartoonRenderStyle,
        background_style: CartoonBackgroundStyle,
        fidelity_preset: CartoonFidelityPreset,
        showcase_avatar_mode: CartoonShowcaseAvatarMode,
        style_preset: CartoonStylePreset,
        qa_bundle_mode: CartoonQABundleMode,
        result: CartoonShortsGenerationResult,
        model: str,
    ) -> None:
        if self._history_service is None:
            return
        payload = result.cartoon_payload if isinstance(result.cartoon_payload, dict) else {}
        self._history_service.record_generation(
            asset_type="cartoon_shorts",
            topic=topic,
            title=f"Cartoon Shorts: {topic}",
            model=model,
            request_payload={
                "topic": topic,
                "idea": idea,
                "short_type": short_type,
                "output_mode": output_mode,
                "scene_count": max(2, min(int(scene_count), 10)),
                "speaker_count": max(2, min(int(speaker_count), 4)),
                "language": _clean(language) or "en",
                "hinglish_script": bool(use_hinglish_script),
                "timeline_schema_version": timeline_schema_version,
                "quality_tier": quality_tier,
                "render_style": render_style,
                "background_style": background_style,
                "fidelity_preset": fidelity_preset,
                "showcase_avatar_mode": showcase_avatar_mode,
                "style_preset": style_preset,
                "qa_bundle_mode": qa_bundle_mode,
            },
            result_payload=payload,
            status="error" if result.parse_error else "success",
            cache_hit=result.cache_hits > 0,
            parse_note=" ".join(result.parse_notes).strip(),
            error=result.parse_error or "",
            raw_text=result.debug_raw or "",
        )

    @staticmethod
    def _script_markdown(
        *,
        topic: str,
        short_type: CartoonShortType,
        timeline: CartoonTimeline,
        character_roster: list[CartoonCharacterSpec],
    ) -> str:
        lines: list[str] = [f"# Cartoon Shorts Script: {topic}", ""]
        lines.append(f"- Short Type: `{short_type}`")
        lines.append(f"- Speakers: {len(character_roster)}")
        lines.append("")
        for character in character_roster:
            lines.append(f"- {character.get('name', 'Speaker')} ({character.get('role', 'role')})")
        lines.append("")
        scenes = timeline.get("scenes", []) if isinstance(timeline.get("scenes"), list) else []
        for scene in scenes:
            if not isinstance(scene, dict):
                continue
            scene_index = _int_safe(scene.get("scene_index"), default=0)
            lines.append(f"## Scene {scene_index}: {_clean(scene.get('title')) or 'Untitled'}")
            hook = _clean(scene.get("hook"))
            if hook:
                lines.append(hook)
            turns = scene.get("turns", [])
            if isinstance(turns, list):
                for turn in turns:
                    if not isinstance(turn, dict):
                        continue
                    speaker = _clean(turn.get("speaker_name")) or "Speaker"
                    text = _clean(turn.get("text"))
                    if text:
                        lines.append(f"- **{speaker}:** {text}")
            lines.append("")
        return "\n".join(lines)


def _clean(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _normalize_short_type(value: str) -> CartoonShortType:
    raw = _clean(value).lower().replace(" ", "_")
    if raw in SHORT_TYPE_OPTIONS:
        return cast(CartoonShortType, raw)
    return "educational_explainer"


def _normalize_output_mode(value: str) -> CartoonOutputMode:
    raw = _clean(value).lower()
    if raw in {"dual", "shorts_9_16", "widescreen_16_9"}:
        return cast(CartoonOutputMode, raw)
    return "dual"


def _normalize_timeline_schema_version(value: str) -> CartoonTimelineSchemaVersion:
    raw = _clean(value).lower()
    if raw == "v2":
        return cast(CartoonTimelineSchemaVersion, "v2")
    return cast(CartoonTimelineSchemaVersion, "v1")


def _normalize_quality_tier(value: str) -> CartoonQualityTier:
    raw = _clean(value).lower()
    if raw in {"auto", "light", "balanced", "high"}:
        return cast(CartoonQualityTier, raw)
    return cast(CartoonQualityTier, "auto")


def _normalize_render_style(value: str) -> CartoonRenderStyle:
    raw = _clean(value).lower()
    if raw in {"scene", "character_showcase"}:
        return cast(CartoonRenderStyle, raw)
    return cast(CartoonRenderStyle, "scene")


def _normalize_background_style(value: str) -> CartoonBackgroundStyle:
    raw = _clean(value).lower()
    if raw in {"auto", "scene", "chroma_green"}:
        return cast(CartoonBackgroundStyle, raw)
    return cast(CartoonBackgroundStyle, "auto")


def _normalize_fidelity_preset(value: str) -> CartoonFidelityPreset:
    raw = _clean(value).lower()
    if raw in {"auto_profile", "hd_1080p30", "uhd_4k30"}:
        return cast(CartoonFidelityPreset, raw)
    return cast(CartoonFidelityPreset, "auto_profile")


def _normalize_showcase_avatar_mode(value: str) -> CartoonShowcaseAvatarMode:
    raw = _clean(value).lower()
    if raw in {"auto", "cache_sprite", "procedural_presenter"}:
        return cast(CartoonShowcaseAvatarMode, raw)
    return cast(CartoonShowcaseAvatarMode, "auto")


def _normalize_style_preset(value: str) -> CartoonStylePreset:
    raw = _clean(value).lower()
    if raw in {"default_scene", "expected_showcase"}:
        return cast(CartoonStylePreset, raw)
    return cast(CartoonStylePreset, "default_scene")


def _normalize_qa_bundle_mode(value: str) -> CartoonQABundleMode:
    raw = _clean(value).lower()
    if raw in {"off", "auto"}:
        return cast(CartoonQABundleMode, raw)
    return cast(CartoonQABundleMode, "auto")


def _int_safe(value: object, *, default: int) -> int:
    try:
        if isinstance(value, bool):
            return default
        if isinstance(value, (int, float, str)):
            return int(value)
        return int(str(value))
    except (TypeError, ValueError):
        return default
