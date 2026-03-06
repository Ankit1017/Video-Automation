from __future__ import annotations

from dataclasses import dataclass
import base64
import json
import logging
from pathlib import Path
import shutil
import tempfile
from time import perf_counter
from typing import Any, cast

from main_app.contracts import (
    CartoonBackgroundStyle,
    CartoonCharacterSpec,
    CartoonDialogueTurn,
    CartoonFidelityPreset,
    CartoonOutputArtifact,
    CartoonPayload,
    CartoonQABundleMode,
    CartoonQualityTier,
    CartoonRenderProfile,
    CartoonRenderStyle,
    CartoonShowcaseAvatarMode,
    CartoonScene,
    CartoonStylePreset,
)
from main_app.services.cartoon_asset_runtime_service import (
    resolve_asset_runtime_version,
    resolve_pack_kind,
    resolve_pack_root,
)
from main_app.services.cartoon_character_asset_validator import CartoonCharacterAssetValidator
from main_app.services.cartoon_flat_asset_catalog_service import CartoonFlatAssetCatalogService
from main_app.services.cartoon_flat_asset_sprite_service import CartoonFlatAssetSpriteService
from main_app.services.cartoon_flat_asset_validator import CartoonFlatAssetValidator
from main_app.services.cartoon_lottie_cache_service import CartoonLottieCacheService
from main_app.services.cartoon_motion_planner_service import CartoonMotionPlannerService
from main_app.services.cartoon_render_profile_service import CartoonRenderProfileService
from main_app.services.cartoon_scene_renderer import CartoonSceneRenderer
from main_app.services.observability_service import ensure_request_id
from main_app.services.telemetry_service import ObservabilityEvent, TelemetryService


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _RenderTarget:
    key: str
    width: int
    height: int
    fps: int
    bitrate_kbps: int


@dataclass(frozen=True)
class _TimedSceneTurn:
    turn: CartoonDialogueTurn
    start_ms: int
    end_ms: int
    segment: dict[str, object] | None


class CartoonExportService:
    def __init__(self, *, telemetry_service: TelemetryService | None = None) -> None:
        self._telemetry_service = telemetry_service
        self._profile_service = CartoonRenderProfileService()
        self._scene_renderer = CartoonSceneRenderer()
        self._motion_planner = CartoonMotionPlannerService()

    def build_cartoon_mp4s(
        self,
        *,
        topic: str,
        cartoon_payload: CartoonPayload,
        output_mode: str | None = None,
        render_profile: CartoonRenderProfile | None = None,
    ) -> tuple[dict[str, bytes], str | None]:
        request_id = ensure_request_id()
        started_at = perf_counter()
        profile = render_profile or self._profile_service.select_profile()
        selected_mode = _resolve_output_mode(output_mode=output_mode, payload=cartoon_payload)
        timeline_schema_version = _resolve_timeline_schema_version(payload=cartoon_payload)
        quality_tier = _resolve_quality_tier(payload=cartoon_payload, profile=profile)
        render_style = _resolve_render_style(payload=cartoon_payload)
        background_style = _resolve_background_style(payload=cartoon_payload, render_style=render_style)
        fidelity_preset = _resolve_fidelity_preset(payload=cartoon_payload)
        showcase_avatar_mode = _resolve_showcase_avatar_mode(payload=cartoon_payload, render_style=render_style)
        style_preset = _resolve_style_preset(payload=cartoon_payload)
        qa_bundle_mode = _resolve_qa_bundle_mode(payload=cartoon_payload)
        cinematic_mode = _bool_from_metadata(payload=cartoon_payload, key="cinematic_story_mode", default=True)
        pack_root = resolve_pack_root(payload=cast(dict[str, Any], cartoon_payload))
        asset_runtime_version = resolve_asset_runtime_version(pack_root=pack_root)
        asset_pack_kind = resolve_pack_kind(pack_root=pack_root, runtime_version=asset_runtime_version)
        targets = self._build_targets(
            profile=profile,
            output_mode=selected_mode,
            quality_tier=quality_tier,
            fidelity_preset=fidelity_preset,
            render_style=render_style,
            style_preset=style_preset,
        )
        render_root: Path | None = None
        outputs: dict[str, bytes] = {}
        output_artifacts: list[CartoonOutputArtifact] = []
        lottie_cache_service: CartoonLottieCacheService | None = None
        flat_catalog_service: CartoonFlatAssetCatalogService | None = None
        flat_sprite_service: CartoonFlatAssetSpriteService | None = None

        if self._telemetry_service is not None:
            with self._telemetry_service.context_scope(request_id=request_id):
                self._telemetry_service.record_event(
                    ObservabilityEvent(
                        event_name="cartoon.render.start",
                        component="export.cartoon",
                        status="started",
                        timestamp=_now_iso(),
                        attributes={
                            "topic": topic,
                            "output_mode": selected_mode,
                            "target_count": len(targets),
                            "profile_key": str(profile.get("profile_key", "unknown")),
                            "cinematic_mode": cinematic_mode,
                            "timeline_schema_version": timeline_schema_version,
                            "quality_tier": quality_tier,
                            "render_style": render_style,
                            "background_style": background_style,
                            "fidelity_preset": fidelity_preset,
                            "showcase_avatar_mode": showcase_avatar_mode,
                            "style_preset": style_preset,
                            "qa_bundle_mode": qa_bundle_mode,
                            "asset_runtime_version": asset_runtime_version,
                            "asset_pack_kind": asset_pack_kind,
                            "asset_pack_root": str(pack_root),
                        },
                    )
                )
                self._telemetry_service.record_metric(
                    name="cartoon_scene_count",
                    value=float(len(_timeline_scenes(cartoon_payload))),
                    attrs={"output_mode": selected_mode, "quality_tier": quality_tier},
                )
                if style_preset == "expected_showcase":
                    self._telemetry_service.record_event(
                        ObservabilityEvent(
                            event_name="cartoon.showcase.preset.applied",
                            component="export.cartoon",
                            status="ok",
                            timestamp=_now_iso(),
                            attributes={
                                "render_style": render_style,
                                "background_style": background_style,
                                "fidelity_preset": fidelity_preset,
                            },
                        )
                    )
                self._telemetry_service.record_event(
                    ObservabilityEvent(
                        event_name="cartoon.render.quality_tier",
                        component="export.cartoon",
                        status="ok",
                        timestamp=_now_iso(),
                        attributes={"quality_tier": quality_tier},
                    )
                )
                if asset_runtime_version == "v3_flat_assets_direct":
                    self._telemetry_service.record_event(
                        ObservabilityEvent(
                            event_name="cartoon.runtime.v3.selected",
                            component="export.cartoon",
                            status="ok",
                            timestamp=_now_iso(),
                            attributes={"pack_root": str(pack_root), "pack_kind": asset_pack_kind},
                        )
                    )

        try:
            try:
                from PIL import Image, ImageDraw, ImageFont  # type: ignore
                from moviepy.editor import AudioFileClip, ImageSequenceClip, concatenate_videoclips  # type: ignore
                from moviepy.video.fx.all import fadein, fadeout  # type: ignore
            except ImportError:
                return {}, "Cartoon export requires `moviepy` and `Pillow`."

            render_root = self._create_render_workdir()
            audio_path = render_root / "cartoon_audio.mp3"
            metadata = cartoon_payload.get("metadata", {})
            metadata_map = metadata if isinstance(metadata, dict) else {}
            metadata_map["asset_runtime_version"] = asset_runtime_version
            metadata_map["asset_pack_root"] = str(pack_root)
            metadata_map["asset_pack_kind"] = asset_pack_kind
            cartoon_payload["metadata"] = metadata_map
            pack_cache_fps = _pack_cache_fps_from_payload(cartoon_payload)
            timed_segments = _metadata_audio_segments(metadata_map.get("audio_segments"))
            audio_b64 = metadata_map.get("audio_b64")
            if isinstance(audio_b64, str):
                try:
                    audio_path.write_bytes(base64.b64decode(audio_b64.encode("utf-8"), validate=True))
                except (ValueError, OSError):
                    pass

            if timeline_schema_version == "v2":
                if self._telemetry_service is not None:
                    self._telemetry_service.record_event(
                        ObservabilityEvent(
                            event_name="cartoon.pack.validate.start",
                            component="export.cartoon",
                            status="started",
                            timestamp=_now_iso(),
                            attributes={
                                "pack_root": str(pack_root),
                                "asset_runtime_version": asset_runtime_version,
                            },
                        )
                    )
                if asset_runtime_version == "v3_flat_assets_direct":
                    flat_catalog_service = CartoonFlatAssetCatalogService(pack_root=pack_root)
                    flat_validator = CartoonFlatAssetValidator(pack_root=pack_root, catalog_service=flat_catalog_service)
                    validation_errors = flat_validator.validate_roster(
                        roster=cast(list[CartoonCharacterSpec], cartoon_payload.get("character_roster", [])),
                        timeline_schema_version=timeline_schema_version,
                    )
                    if validation_errors:
                        if self._telemetry_service is not None:
                            self._telemetry_service.record_metric(
                                name="cartoon_pack_validation_failures_total",
                                value=float(len(validation_errors)),
                                attrs={"timeline_schema_version": timeline_schema_version},
                            )
                            self._telemetry_service.record_event(
                                ObservabilityEvent(
                                    event_name="cartoon.pack.validate.end",
                                    component="export.cartoon",
                                    status="error",
                                    timestamp=_now_iso(),
                                    attributes={"errors": len(validation_errors)},
                                )
                            )
                        return {}, f"Flat-assets pack validation failed: {validation_errors[0]}"
                    motion_warnings = flat_validator.audit_roster_motion_quality(
                        roster=cast(list[CartoonCharacterSpec], cartoon_payload.get("character_roster", [])),
                        timeline_schema_version=timeline_schema_version,
                    )
                    motion_warning_summary = flat_validator.motion_quality_summary(
                        roster=cast(list[CartoonCharacterSpec], cartoon_payload.get("character_roster", [])),
                        timeline_schema_version=timeline_schema_version,
                    )
                    metadata = cartoon_payload.get("metadata", {})
                    metadata_map = metadata if isinstance(metadata, dict) else {}
                    metadata_map["pack_motion_warning_count"] = len(motion_warnings)
                    metadata_map["pack_motion_warning_summary"] = motion_warning_summary
                    metadata_map["flat_assets_catalog_summary"] = flat_validator.catalog_summary()
                    cartoon_payload["metadata"] = metadata_map
                    flat_sprite_service = CartoonFlatAssetSpriteService(
                        pack_root=pack_root,
                        catalog_service=flat_catalog_service,
                    )
                    if self._telemetry_service is not None:
                        self._telemetry_service.record_event(
                            ObservabilityEvent(
                                event_name="cartoon.flat_assets.catalog.loaded",
                                component="export.cartoon",
                                status="ok",
                                timestamp=_now_iso(),
                                attributes={
                                    "pack_root": str(pack_root),
                                    "summary": cast(Any, metadata_map.get("flat_assets_catalog_summary", {})),
                                },
                            )
                        )
                else:
                    lottie_cache_service = CartoonLottieCacheService(pack_root=pack_root)
                    pack_cache_resolution = _pack_cache_resolution_from_payload(cartoon_payload)
                    validator = CartoonCharacterAssetValidator(
                        pack_root=pack_root,
                        expected_cache_resolution=pack_cache_resolution,
                    )
                    validation_errors = validator.validate_roster(
                        roster=cast(list[CartoonCharacterSpec], cartoon_payload.get("character_roster", [])),
                        require_lottie_cache=True,
                        timeline_schema_version=timeline_schema_version,
                    )
                    if validation_errors:
                        if self._telemetry_service is not None:
                            self._telemetry_service.record_metric(
                                name="cartoon_pack_validation_failures_total",
                                value=float(len(validation_errors)),
                                attrs={"timeline_schema_version": timeline_schema_version},
                            )
                            self._telemetry_service.record_event(
                                ObservabilityEvent(
                                    event_name="cartoon.pack.validate.end",
                                    component="export.cartoon",
                                    status="error",
                                    timestamp=_now_iso(),
                                    attributes={"errors": len(validation_errors)},
                                )
                            )
                        return {}, f"Cartoon pack validation failed: {validation_errors[0]}"
                    motion_warnings = validator.audit_roster_motion_quality(
                        roster=cast(list[CartoonCharacterSpec], cartoon_payload.get("character_roster", [])),
                        timeline_schema_version=timeline_schema_version,
                    )
                    motion_warning_summary = validator.motion_quality_summary(
                        roster=cast(list[CartoonCharacterSpec], cartoon_payload.get("character_roster", [])),
                        timeline_schema_version=timeline_schema_version,
                    )
                    metadata = cartoon_payload.get("metadata", {})
                    metadata_map = metadata if isinstance(metadata, dict) else {}
                    metadata_map["pack_motion_warning_count"] = len(motion_warnings)
                    metadata_map["pack_motion_warning_summary"] = motion_warning_summary
                    cartoon_payload["metadata"] = metadata_map
                if self._telemetry_service is not None:
                    self._telemetry_service.record_metric(
                        name="cartoon_pack_motion_warnings_total",
                        value=float(len(motion_warnings)),
                        attrs={"timeline_schema_version": timeline_schema_version},
                    )
                    self._telemetry_service.record_event(
                        ObservabilityEvent(
                            event_name="cartoon.pack.audit.summary",
                            component="export.cartoon",
                            status="ok",
                            timestamp=_now_iso(),
                            attributes={
                                "warning_count": len(motion_warnings),
                                "character_count": len(motion_warning_summary),
                            },
                        )
                    )
                    self._telemetry_service.record_event(
                        ObservabilityEvent(
                            event_name="cartoon.pack.validate.end",
                            component="export.cartoon",
                            status="ok",
                            timestamp=_now_iso(),
                            attributes={"errors": 0, "motion_warnings": len(motion_warnings)},
                        )
                    )

            for target in targets:
                if self._telemetry_service is not None:
                    self._telemetry_service.record_event(
                        ObservabilityEvent(
                            event_name="cartoon.render.format.start",
                            component="export.cartoon",
                            status="started",
                            timestamp=_now_iso(),
                            attributes={
                                "format_key": target.key,
                                "width": target.width,
                                "height": target.height,
                                "fps": target.fps,
                                "quality_tier": quality_tier,
                                "render_style": render_style,
                                "background_style": background_style,
                                "fidelity_preset": fidelity_preset,
                                "bitrate_kbps": target.bitrate_kbps,
                                "showcase_avatar_mode": showcase_avatar_mode,
                                "style_preset": style_preset,
                                "asset_runtime_version": asset_runtime_version,
                            },
                        )
                    )
                clips: list[Any] = []
                clip_paths: list[Path] = []
                audio_clip = None
                try:
                    scenes = _timeline_scenes(cartoon_payload)
                    scene_cursor_ms = 0
                    for scene in scenes:
                        scene_idx = _int_safe(scene.get("scene_index"), default=0)
                        scene_duration_ms = max(1200, _int_safe(scene.get("duration_ms"), default=4000))
                        duration_sec = max(1.2, scene_duration_ms / 1000.0)
                        frame_total = max(2, int(round(duration_sec * float(target.fps)))) if cinematic_mode else 1
                        frame_paths: list[str] = []
                        scene_turns = _scene_turns(scene)
                        timed_turns, scene_start_ms = _build_scene_timed_turns(
                            scene_turns=scene_turns,
                            scene_index=scene_idx,
                            scene_duration_ms=scene_duration_ms,
                            audio_segments=timed_segments,
                            fallback_scene_start_ms=scene_cursor_ms,
                        )
                        scene_cursor_ms = max(
                            scene_cursor_ms + scene_duration_ms,
                            scene_start_ms + scene_duration_ms,
                            timed_turns[-1].end_ms if timed_turns else scene_start_ms + scene_duration_ms,
                        )
                        if self._telemetry_service is not None and timeline_schema_version == "v2":
                            self._telemetry_service.record_event(
                                ObservabilityEvent(
                                    event_name="cartoon.timeline.v2.scene",
                                    component="export.cartoon",
                                    status="ok",
                                    timestamp=_now_iso(),
                                    attributes={"scene_index": scene_idx, "frame_total": frame_total},
                                )
                            )
                        for frame_idx in range(frame_total):
                            frame_path = render_root / f"{target.key}_scene_{scene_idx:03d}_f{frame_idx:04d}.png"
                            if frame_total <= 1:
                                frame_time_ms = scene_start_ms
                            else:
                                frame_progress = frame_idx / max(frame_total - 1, 1)
                                frame_time_ms = scene_start_ms + int(round(float(scene_duration_ms - 1) * frame_progress))
                            active_timed_turn = _timed_turn_for_time(timed_turns=timed_turns, time_ms=frame_time_ms)
                            active_turn = active_timed_turn.turn if active_timed_turn is not None else _first_turn(scene)
                            active_mouth = _mouth_for_time(
                                segment=(active_timed_turn.segment if active_timed_turn is not None else None),
                                time_ms=frame_time_ms,
                            )
                            frame_plan = None
                            if timeline_schema_version == "v2":
                                frame_plan = self._motion_planner.plan_frame(
                                    scene=scene,
                                    character_roster=cast(list[CartoonCharacterSpec], cartoon_payload.get("character_roster", [])),
                                    scene_relative_ms=max(0, frame_time_ms - scene_start_ms),
                                    scene_duration_ms=scene_duration_ms,
                                    active_turn=active_turn,
                                    active_mouth=active_mouth,
                                )
                                if isinstance(frame_plan, dict):
                                    frame_plan["fps"] = target.fps
                                    frame_plan["cache_fps"] = pack_cache_fps
                                if self._telemetry_service is not None:
                                    self._telemetry_service.record_metric(
                                        name="cartoon.motion.plan.frames_total",
                                        value=1.0,
                                        attrs={"scene_index": str(scene_idx)},
                                    )
                            frame = self._scene_renderer.render_frame(
                                image_module=Image,
                                draw_module=ImageDraw,
                                font_module=ImageFont,
                                width=target.width,
                                height=target.height,
                                topic=topic,
                                scene=scene,
                                active_turn=active_turn,
                                active_mouth=active_mouth,
                                character_roster=cast(list[CartoonCharacterSpec], cartoon_payload.get("character_roster", [])),
                                frame_index=frame_idx,
                                frame_count=frame_total,
                                cinematic_mode=cinematic_mode,
                                frame_plan=frame_plan,
                                lottie_cache_service=lottie_cache_service,
                                flat_asset_sprite_service=flat_sprite_service,
                                timeline_schema_version=timeline_schema_version,
                                render_style=render_style,
                                background_style=background_style,
                                showcase_avatar_mode=showcase_avatar_mode,
                            )
                            frame.save(frame_path)
                            clip_paths.append(frame_path)
                            frame_paths.append(str(frame_path))
                        if not frame_paths:
                            continue
                        scene_clip = ImageSequenceClip(frame_paths, fps=target.fps if cinematic_mode else 1)
                        scene_clip = scene_clip.set_duration(duration_sec)
                        if cinematic_mode:
                            transition_in = _clean(scene.get("transition_in")).lower()
                            transition_out = _clean(scene.get("transition_out")).lower()
                            if transition_in in {"crossfade", "fade_black"}:
                                scene_clip = scene_clip.fx(fadein, 0.24)
                            if transition_out in {"crossfade", "fade_black"}:
                                scene_clip = scene_clip.fx(fadeout, 0.22)
                        clips.append(scene_clip)
                    if not clips:
                        output_artifacts.append(
                            cast(
                                CartoonOutputArtifact,
                                {
                                    "key": target.key,
                                    "format": "mp4",
                                    "status": "error",
                                    "bytes": 0,
                                    "path_hint": "",
                                    "mime": "video/mp4",
                                },
                            )
                        )
                        continue

                    merged = concatenate_videoclips(clips, method="compose")
                    if audio_path.exists():
                        audio_clip = AudioFileClip(str(audio_path))
                        merged = merged.set_audio(audio_clip)
                    output_path = render_root / f"{target.key}.mp4"
                    merged.write_videofile(
                        str(output_path),
                        fps=target.fps,
                        codec="libx264",
                        audio_codec="aac",
                        audio_bitrate="192k",
                        audio_fps=48_000,
                        bitrate=f"{max(600, int(target.bitrate_kbps))}k",
                        logger=None,
                    )
                    if output_path.exists():
                        payload = output_path.read_bytes()
                        outputs[target.key] = payload
                        output_artifacts.append(
                            cast(
                                CartoonOutputArtifact,
                                {
                                    "key": target.key,
                                    "format": "mp4",
                                    "status": "ok",
                                    "bytes": len(payload),
                                    "path_hint": output_path.name,
                                    "mime": "video/mp4",
                                },
                            )
                        )
                        if self._telemetry_service is not None:
                            self._telemetry_service.record_metric(
                                name="cartoon_export_output_bytes_total",
                                value=float(len(payload)),
                                attrs={"format_key": target.key},
                            )
                    else:
                        output_artifacts.append(
                            cast(
                                CartoonOutputArtifact,
                                {
                                    "key": target.key,
                                    "format": "mp4",
                                    "status": "error",
                                    "bytes": 0,
                                    "path_hint": "",
                                    "mime": "video/mp4",
                                },
                            )
                        )
                finally:
                    for clip in clips:
                        try:
                            clip.close()
                        except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
                            pass
                    if audio_clip is not None:
                        try:
                            audio_clip.close()
                        except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
                            pass
                    for path in clip_paths:
                        try:
                            path.unlink(missing_ok=True)
                        except OSError:
                            pass

                if self._telemetry_service is not None:
                    status = "ok" if target.key in outputs else "error"
                    self._telemetry_service.record_event(
                        ObservabilityEvent(
                            event_name="cartoon.render.format.end",
                            component="export.cartoon",
                            status=status,
                            timestamp=_now_iso(),
                            attributes={"format_key": target.key, "bytes": len(outputs.get(target.key, b""))},
                        )
                    )

            if self._telemetry_service is not None and lottie_cache_service is not None:
                self._telemetry_service.record_metric(
                    name="cartoon.sprite.cache_miss_total",
                    value=float(lottie_cache_service.cache_miss_count),
                    attrs={"timeline_schema_version": timeline_schema_version},
                )
            flat_diagnostics = flat_sprite_service.diagnostics() if flat_sprite_service is not None else {}
            if self._telemetry_service is not None and flat_sprite_service is not None:
                self._telemetry_service.record_metric(
                    name="cartoon.flat_assets.svg_rasterize.cache_hits",
                    value=float(flat_diagnostics.get("svg_raster_cache_hits", 0)),
                    attrs={"timeline_schema_version": timeline_schema_version},
                )
                self._telemetry_service.record_metric(
                    name="cartoon.flat_assets.svg_rasterize.cache_misses",
                    value=float(flat_diagnostics.get("svg_raster_cache_misses", 0)),
                    attrs={"timeline_schema_version": timeline_schema_version},
                )
                self._telemetry_service.record_metric(
                    name="cartoon.flat_assets.compose.total",
                    value=float(flat_diagnostics.get("compose_total", 0)),
                    attrs={"timeline_schema_version": timeline_schema_version},
                )
                self._telemetry_service.record_metric(
                    name="cartoon.flat_assets.compose.failures",
                    value=float(flat_diagnostics.get("compose_failures", 0)),
                    attrs={"timeline_schema_version": timeline_schema_version},
                )

            qa_bundle: dict[str, object] | None = None
            if qa_bundle_mode == "auto":
                qa_bundle = _build_qa_bundle(
                    payload=cartoon_payload,
                    profile=profile,
                    timeline_schema_version=timeline_schema_version,
                    quality_tier=quality_tier,
                    render_style=render_style,
                    background_style=background_style,
                    fidelity_preset=fidelity_preset,
                    showcase_avatar_mode=showcase_avatar_mode,
                    style_preset=style_preset,
                    selected_mode=selected_mode,
                    cinematic_mode=cinematic_mode,
                    targets=targets,
                    cache_miss_count=(lottie_cache_service.cache_miss_count if lottie_cache_service is not None else 0),
                    asset_runtime_version=asset_runtime_version,
                    asset_pack_root=pack_root,
                    asset_pack_kind=asset_pack_kind,
                    flat_catalog_summary=(
                        flat_catalog_service.summary()
                        if flat_catalog_service is not None
                        else cast(dict[str, object], metadata_map.get("flat_assets_catalog_summary", {}))
                    ),
                    flat_sprite_diagnostics=flat_diagnostics,
                )
                qa_bundle_bytes = json.dumps(qa_bundle, ensure_ascii=True, sort_keys=True, indent=2).encode("utf-8")
                output_artifacts.append(
                    cast(
                        CartoonOutputArtifact,
                        {
                            "key": "qa_bundle",
                            "format": "json",
                            "status": "ok",
                            "bytes": len(qa_bundle_bytes),
                            "path_hint": "qa_bundle.json",
                            "mime": "application/json",
                        },
                    )
                )
                metadata = cartoon_payload.get("metadata", {})
                metadata_map = metadata if isinstance(metadata, dict) else {}
                metadata_map["qa_bundle"] = cast(Any, qa_bundle)
                metadata_map["qa_bundle_mode"] = qa_bundle_mode
                metadata_map["qa_bundle_note"] = (
                    f"QA bundle generated ({len(targets)} target(s), "
                    f"{len(_timeline_scenes(cartoon_payload))} scene(s))."
                )
                cartoon_payload["metadata"] = metadata_map
                if self._telemetry_service is not None:
                    self._telemetry_service.record_event(
                        ObservabilityEvent(
                            event_name="cartoon.qa.bundle.generated",
                            component="export.cartoon",
                            status="ok",
                            timestamp=_now_iso(),
                            attributes={
                                "target_count": len(targets),
                                "scene_count": len(_timeline_scenes(cartoon_payload)),
                            },
                        )
                    )

            cartoon_payload["output_artifacts"] = output_artifacts
            cartoon_payload["render_profile"] = profile
            cartoon_payload["quality_tier"] = quality_tier
            cartoon_payload["timeline_schema_version"] = cast(Any, timeline_schema_version)
            cartoon_payload["render_style"] = render_style
            cartoon_payload["background_style"] = background_style
            cartoon_payload["fidelity_preset"] = fidelity_preset
            cartoon_payload["showcase_avatar_mode"] = showcase_avatar_mode
            cartoon_payload["style_preset"] = style_preset
            cartoon_payload["qa_bundle_mode"] = qa_bundle_mode
            metadata = cartoon_payload.get("metadata", {})
            if isinstance(metadata, dict):
                metadata["render_style"] = render_style
                metadata["background_style"] = background_style
                metadata["fidelity_preset"] = fidelity_preset
                metadata["showcase_avatar_mode"] = showcase_avatar_mode
                metadata["style_preset"] = style_preset
                metadata["qa_bundle_mode"] = qa_bundle_mode
                metadata["asset_runtime_version"] = asset_runtime_version
                metadata["asset_pack_root"] = str(pack_root)
                metadata["asset_pack_kind"] = asset_pack_kind
            duration_ms = max((perf_counter() - started_at) * 1000.0, 0.0)
            if self._telemetry_service is not None:
                with self._telemetry_service.context_scope(request_id=request_id):
                    self._telemetry_service.record_metric(
                        name="cartoon_render_duration_ms",
                        value=duration_ms,
                        attrs={
                            "output_mode": selected_mode,
                            "status": "ok" if outputs else "error",
                            "quality_tier": quality_tier,
                        },
                    )
                    self._telemetry_service.record_event(
                        ObservabilityEvent(
                            event_name="cartoon.render.end",
                            component="export.cartoon",
                            status="ok" if outputs else "error",
                            timestamp=_now_iso(),
                            attributes={
                                "duration_ms": round(duration_ms, 3),
                                "output_count": len(outputs),
                                "profile_key": str(profile.get("profile_key", "unknown")),
                                "cinematic_mode": cinematic_mode,
                                "quality_tier": quality_tier,
                                "render_style": render_style,
                                "background_style": background_style,
                                "fidelity_preset": fidelity_preset,
                                "showcase_avatar_mode": showcase_avatar_mode,
                                "style_preset": style_preset,
                                "qa_bundle_mode": qa_bundle_mode,
                                "asset_runtime_version": asset_runtime_version,
                            },
                        )
                    )
            if not outputs:
                return {}, "No cartoon video output was produced."
            return outputs, None
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            if self._telemetry_service is not None:
                with self._telemetry_service.context_scope(request_id=request_id):
                    self._telemetry_service.record_metric(
                        name="cartoon_render_failures_total",
                        value=1.0,
                        attrs={"error_type": type(exc).__name__},
                    )
                    self._telemetry_service.record_event(
                        ObservabilityEvent(
                            event_name="cartoon.export.error",
                            component="export.cartoon",
                            status="error",
                            timestamp=_now_iso(),
                            attributes={"error": str(exc), "error_type": type(exc).__name__},
                        )
                    )
            return outputs, f"Failed to export cartoon shorts: {exc}"
        finally:
            if render_root is not None:
                self._cleanup_render_workdir(render_root)

    def _build_targets(
        self,
        *,
        profile: CartoonRenderProfile,
        output_mode: str,
        quality_tier: CartoonQualityTier,
        fidelity_preset: CartoonFidelityPreset,
        render_style: CartoonRenderStyle,
        style_preset: CartoonStylePreset,
    ) -> list[_RenderTarget]:
        fps = _tier_adjusted_fps(_int_safe(profile.get("fps"), default=24), quality_tier=quality_tier)
        targets: list[_RenderTarget] = []
        shorts_width = max(360, _int_safe(profile.get("shorts_width"), default=1080))
        shorts_height = max(640, _int_safe(profile.get("shorts_height"), default=1920))
        widescreen_width = max(640, _int_safe(profile.get("widescreen_width"), default=1920))
        widescreen_height = max(360, _int_safe(profile.get("widescreen_height"), default=1080))

        if fidelity_preset == "hd_1080p30":
            shorts_width, shorts_height = 1080, 1920
            widescreen_width, widescreen_height = 1920, 1080
            fps = 30
        elif fidelity_preset == "uhd_4k30":
            shorts_width, shorts_height = 2160, 3840
            widescreen_width, widescreen_height = 3840, 2160
            fps = 30
        elif fidelity_preset == "auto_profile" and style_preset == "expected_showcase" and render_style == "character_showcase":
            shorts_width = max(shorts_width, 1080)
            shorts_height = max(shorts_height, 1920)
            widescreen_width = max(widescreen_width, 1920)
            widescreen_height = max(widescreen_height, 1080)
            fps = max(fps, 30)

        if output_mode in {"dual", "shorts_9_16"}:
            shorts_bitrate = _target_bitrate_kbps(
                width=shorts_width,
                height=shorts_height,
                fps=fps,
                quality_tier=quality_tier,
                fidelity_preset=fidelity_preset,
            )
            targets.append(
                _RenderTarget(
                    key="shorts_9_16",
                    width=shorts_width,
                    height=shorts_height,
                    fps=fps,
                    bitrate_kbps=shorts_bitrate,
                )
            )
        if output_mode in {"dual", "widescreen_16_9"}:
            widescreen_bitrate = _target_bitrate_kbps(
                width=widescreen_width,
                height=widescreen_height,
                fps=fps,
                quality_tier=quality_tier,
                fidelity_preset=fidelity_preset,
            )
            targets.append(
                _RenderTarget(
                    key="widescreen_16_9",
                    width=widescreen_width,
                    height=widescreen_height,
                    fps=fps,
                    bitrate_kbps=widescreen_bitrate,
                )
            )
        return targets

    @staticmethod
    def _create_render_workdir() -> Path:
        return Path(tempfile.mkdtemp(prefix="hatched_cartoon_render_"))

    @staticmethod
    def _cleanup_render_workdir(path: Path) -> None:
        try:
            shutil.rmtree(path, ignore_errors=True)
        except OSError as exc:
            logger.debug("cartoon render cleanup failed: %s", exc)


def _resolve_output_mode(*, output_mode: str | None, payload: CartoonPayload) -> str:
    raw = " ".join(str(output_mode or payload.get("output_mode", "dual")).split()).strip().lower()
    if raw in {"shorts_9_16", "widescreen_16_9", "dual"}:
        return raw
    return "dual"


def _resolve_timeline_schema_version(*, payload: CartoonPayload) -> str:
    metadata = payload.get("metadata", {})
    metadata_map = metadata if isinstance(metadata, dict) else {}
    candidates = [payload.get("timeline_schema_version"), metadata_map.get("timeline_schema_version")]
    for candidate in candidates:
        if _clean(candidate).lower() == "v2":
            return "v2"
    return "v1"


def _resolve_quality_tier(*, payload: CartoonPayload, profile: CartoonRenderProfile) -> CartoonQualityTier:
    metadata = payload.get("metadata", {})
    metadata_map = metadata if isinstance(metadata, dict) else {}
    raw = _clean(payload.get("quality_tier") or metadata_map.get("quality_tier") or "auto").lower()
    if raw == "auto":
        profile_key = _clean(profile.get("profile_key")).lower()
        if profile_key == "gpu_high":
            return cast(CartoonQualityTier, "high")
        if profile_key == "gpu_balanced":
            return cast(CartoonQualityTier, "balanced")
        return cast(CartoonQualityTier, "light")
    if raw in {"light", "balanced", "high"}:
        return cast(CartoonQualityTier, raw)
    return cast(CartoonQualityTier, "balanced")


def _resolve_render_style(*, payload: CartoonPayload) -> CartoonRenderStyle:
    metadata = payload.get("metadata", {})
    metadata_map = metadata if isinstance(metadata, dict) else {}
    raw = _clean(payload.get("render_style") or metadata_map.get("render_style") or "scene").lower()
    if raw == "character_showcase":
        return cast(CartoonRenderStyle, "character_showcase")
    return cast(CartoonRenderStyle, "scene")


def _resolve_background_style(*, payload: CartoonPayload, render_style: CartoonRenderStyle) -> CartoonBackgroundStyle:
    metadata = payload.get("metadata", {})
    metadata_map = metadata if isinstance(metadata, dict) else {}
    raw = _clean(payload.get("background_style") or metadata_map.get("background_style") or "auto").lower()
    if raw == "auto":
        if render_style == "character_showcase":
            return cast(CartoonBackgroundStyle, "chroma_green")
        return cast(CartoonBackgroundStyle, "scene")
    if raw in {"scene", "chroma_green"}:
        return cast(CartoonBackgroundStyle, raw)
    return cast(CartoonBackgroundStyle, "scene")


def _resolve_fidelity_preset(*, payload: CartoonPayload) -> CartoonFidelityPreset:
    metadata = payload.get("metadata", {})
    metadata_map = metadata if isinstance(metadata, dict) else {}
    raw = _clean(payload.get("fidelity_preset") or metadata_map.get("fidelity_preset") or "auto_profile").lower()
    if raw in {"auto_profile", "hd_1080p30", "uhd_4k30"}:
        return cast(CartoonFidelityPreset, raw)
    return cast(CartoonFidelityPreset, "auto_profile")


def _resolve_showcase_avatar_mode(*, payload: CartoonPayload, render_style: CartoonRenderStyle) -> CartoonShowcaseAvatarMode:
    metadata = payload.get("metadata", {})
    metadata_map = metadata if isinstance(metadata, dict) else {}
    raw = _clean(payload.get("showcase_avatar_mode") or metadata_map.get("showcase_avatar_mode") or "auto").lower()
    if raw in {"cache_sprite", "procedural_presenter"}:
        return cast(CartoonShowcaseAvatarMode, raw)
    if _clean(render_style) != "character_showcase":
        return cast(CartoonShowcaseAvatarMode, "cache_sprite")
    warning_count = _int_safe(metadata_map.get("pack_motion_warning_count"), default=0)
    if warning_count > 0:
        return cast(CartoonShowcaseAvatarMode, "procedural_presenter")
    return cast(CartoonShowcaseAvatarMode, "cache_sprite")


def _resolve_style_preset(*, payload: CartoonPayload) -> CartoonStylePreset:
    metadata = payload.get("metadata", {})
    metadata_map = metadata if isinstance(metadata, dict) else {}
    raw = _clean(payload.get("style_preset") or metadata_map.get("style_preset") or "default_scene").lower()
    if raw in {"default_scene", "expected_showcase"}:
        return cast(CartoonStylePreset, raw)
    return cast(CartoonStylePreset, "default_scene")


def _resolve_qa_bundle_mode(*, payload: CartoonPayload) -> CartoonQABundleMode:
    metadata = payload.get("metadata", {})
    metadata_map = metadata if isinstance(metadata, dict) else {}
    raw = _clean(payload.get("qa_bundle_mode") or metadata_map.get("qa_bundle_mode") or "auto").lower()
    if raw in {"off", "auto"}:
        return cast(CartoonQABundleMode, raw)
    return cast(CartoonQABundleMode, "auto")


def _tier_adjusted_fps(base_fps: int, *, quality_tier: CartoonQualityTier) -> int:
    safe = max(12, int(base_fps))
    if quality_tier == "light":
        return max(12, min(24, int(round(safe * 0.7))))
    if quality_tier == "high":
        return max(safe, 30)
    return max(16, safe)


def _target_bitrate_kbps(
    *,
    width: int,
    height: int,
    fps: int,
    quality_tier: CartoonQualityTier,
    fidelity_preset: CartoonFidelityPreset,
) -> int:
    if fidelity_preset == "hd_1080p30":
        return 6_500
    if fidelity_preset == "uhd_4k30":
        return 18_000
    pixels = max(1, int(width) * int(height))
    base = int((pixels / 1_000_000.0) * max(12, int(fps)) * 220)
    if quality_tier == "light":
        base = int(base * 0.75)
    elif quality_tier == "high":
        base = int(base * 1.2)
    return max(900, min(base, 22_000))


def _pack_root_from_payload(payload: CartoonPayload) -> Path:
    return resolve_pack_root(payload=cast(dict[str, Any], payload))


def _pack_cache_fps_from_payload(payload: CartoonPayload) -> int:
    metadata = payload.get("metadata", {})
    metadata_map = metadata if isinstance(metadata, dict) else {}
    pack = metadata_map.get("pack")
    if isinstance(pack, dict):
        return max(1, _int_safe(pack.get("cache_fps"), default=24))
    return 24


def _pack_cache_resolution_from_payload(payload: CartoonPayload) -> str:
    metadata = payload.get("metadata", {})
    metadata_map = metadata if isinstance(metadata, dict) else {}
    pack = metadata_map.get("pack")
    if isinstance(pack, dict):
        return _clean(pack.get("cache_resolution"))
    return ""


def _timeline_scenes(payload: CartoonPayload) -> list[CartoonScene]:
    timeline = payload.get("timeline", {})
    if not isinstance(timeline, dict):
        return []
    scenes = timeline.get("scenes", [])
    if not isinstance(scenes, list):
        return []
    return [scene for scene in scenes if isinstance(scene, dict)]


def _build_qa_bundle(
    *,
    payload: CartoonPayload,
    profile: CartoonRenderProfile,
    timeline_schema_version: str,
    quality_tier: CartoonQualityTier,
    render_style: CartoonRenderStyle,
    background_style: CartoonBackgroundStyle,
    fidelity_preset: CartoonFidelityPreset,
    showcase_avatar_mode: CartoonShowcaseAvatarMode,
    style_preset: CartoonStylePreset,
    selected_mode: str,
    cinematic_mode: bool,
    targets: list[_RenderTarget],
    cache_miss_count: int,
    asset_runtime_version: str,
    asset_pack_root: Path,
    asset_pack_kind: str,
    flat_catalog_summary: dict[str, object],
    flat_sprite_diagnostics: dict[str, int],
) -> dict[str, object]:
    scenes = _timeline_scenes(payload)
    metadata = payload.get("metadata", {})
    metadata_map = metadata if isinstance(metadata, dict) else {}
    scene_summaries: list[dict[str, object]] = []
    for scene in scenes:
        scene_index = _int_safe(scene.get("scene_index"), default=0)
        duration_ms = max(0, _int_safe(scene.get("duration_ms"), default=0))
        per_target_frames: dict[str, int] = {}
        for target in targets:
            if cinematic_mode:
                frame_total = max(2, int(round((max(1, duration_ms) / 1000.0) * float(target.fps))))
            else:
                frame_total = 1
            per_target_frames[target.key] = frame_total
        scene_summaries.append(
            {
                "scene_index": scene_index,
                "duration_ms": duration_ms,
                "turn_count": len(_scene_turns(scene)),
                "frame_count_by_target": per_target_frames,
            }
        )
    return {
        "generated_at": _now_iso(),
        "topic": _clean(payload.get("topic")),
        "output_mode": selected_mode,
        "timeline_schema_version": timeline_schema_version,
        "quality_tier": quality_tier,
        "render_style": render_style,
        "background_style": background_style,
        "fidelity_preset": fidelity_preset,
        "showcase_avatar_mode": showcase_avatar_mode,
        "style_preset": style_preset,
        "profile_key": _clean(profile.get("profile_key")),
        "target_count": len(targets),
        "targets": [
            {
                "key": target.key,
                "width": target.width,
                "height": target.height,
                "fps": target.fps,
                "bitrate_kbps": target.bitrate_kbps,
            }
            for target in targets
        ],
        "scene_count": len(scene_summaries),
        "scenes": scene_summaries,
        "cache_miss_count": max(0, int(cache_miss_count)),
        "asset_runtime_version": asset_runtime_version,
        "asset_pack_root": str(asset_pack_root),
        "asset_pack_kind": asset_pack_kind,
        "flat_assets_catalog_summary": flat_catalog_summary,
        "flat_sprite_diagnostics": flat_sprite_diagnostics,
        "pack_motion_warning_count": max(0, _int_safe(metadata_map.get("pack_motion_warning_count"), default=0)),
        "pack_motion_warning_summary": metadata_map.get("pack_motion_warning_summary", {}),
    }


def _first_turn(scene: CartoonScene) -> CartoonDialogueTurn | None:
    turns = scene.get("turns", [])
    if not isinstance(turns, list):
        return None
    for turn in turns:
        if isinstance(turn, dict):
            return cast(CartoonDialogueTurn, turn)
    return None


def _scene_turns(scene: CartoonScene) -> list[CartoonDialogueTurn]:
    turns = scene.get("turns", [])
    if not isinstance(turns, list):
        return []
    return [cast(CartoonDialogueTurn, turn) for turn in turns if isinstance(turn, dict)]


def _build_scene_timed_turns(
    *,
    scene_turns: list[CartoonDialogueTurn],
    scene_index: int,
    scene_duration_ms: int,
    audio_segments: list[dict[str, object]],
    fallback_scene_start_ms: int,
) -> tuple[list[_TimedSceneTurn], int]:
    if not scene_turns:
        return [], max(0, int(fallback_scene_start_ms))

    scene_prefix = f"scene_{max(0, int(scene_index)):02d}_"
    scene_segments = [segment for segment in audio_segments if _clean(segment.get("segment_ref")).startswith(scene_prefix)]
    segment_by_ref = {_clean(segment.get("segment_ref")): segment for segment in scene_segments}

    turn_starts = [
        _int_safe(turn.get("start_ms"), default=-1)
        for turn in scene_turns
        if _int_safe(turn.get("start_ms"), default=-1) >= 0
    ]
    segment_starts = [_int_safe(segment.get("start_ms"), default=-1) for segment in scene_segments if _int_safe(segment.get("start_ms"), default=-1) >= 0]
    if segment_starts:
        scene_start_ms = min(segment_starts)
    elif turn_starts:
        scene_start_ms = min(turn_starts)
    else:
        scene_start_ms = max(0, int(fallback_scene_start_ms))

    cursor = scene_start_ms
    timed_turns: list[_TimedSceneTurn] = []
    for position, turn in enumerate(scene_turns):
        segment_ref = _turn_segment_ref(scene_index=scene_index, turn=turn, fallback_turn_index=position)
        segment = segment_by_ref.get(segment_ref)

        if segment is not None:
            start_ms = _int_safe(segment.get("start_ms"), default=cursor)
            end_ms = _int_safe(segment.get("end_ms"), default=start_ms + max(120, _int_safe(segment.get("duration_ms"), default=1200)))
        else:
            start_ms = _int_safe(turn.get("start_ms"), default=cursor)
            end_ms = _int_safe(
                turn.get("end_ms"),
                default=start_ms + max(1200, _int_safe(turn.get("estimated_duration_ms"), default=1800)),
            )

        if start_ms < cursor:
            start_ms = cursor
        if end_ms <= start_ms:
            end_ms = start_ms + max(120, _int_safe(turn.get("estimated_duration_ms"), default=1200))
        cursor = end_ms
        timed_turns.append(
            _TimedSceneTurn(
                turn=turn,
                start_ms=start_ms,
                end_ms=end_ms,
                segment=segment,
            )
        )

    scene_floor_end = scene_start_ms + max(1200, int(scene_duration_ms))
    if timed_turns and timed_turns[-1].end_ms < scene_floor_end:
        last = timed_turns[-1]
        timed_turns[-1] = _TimedSceneTurn(
            turn=last.turn,
            start_ms=last.start_ms,
            end_ms=scene_floor_end,
            segment=last.segment,
        )
    return timed_turns, scene_start_ms


def _timed_turn_for_time(*, timed_turns: list[_TimedSceneTurn], time_ms: int) -> _TimedSceneTurn | None:
    if not timed_turns:
        return None
    for timed in timed_turns:
        if timed.start_ms <= time_ms < timed.end_ms:
            return timed
    if time_ms < timed_turns[0].start_ms:
        return timed_turns[0]
    return timed_turns[-1]


def _turn_segment_ref(*, scene_index: int, turn: CartoonDialogueTurn, fallback_turn_index: int) -> str:
    safe_scene = max(0, int(scene_index))
    safe_turn = max(0, _int_safe(turn.get("turn_index"), default=fallback_turn_index))
    return f"scene_{safe_scene:02d}_turn_{safe_turn:02d}"


def _metadata_audio_segments(raw_segments: object) -> list[dict[str, object]]:
    if not isinstance(raw_segments, list):
        return []
    normalized: list[dict[str, object]] = []
    for raw in raw_segments:
        if not isinstance(raw, dict):
            continue
        start_ms = max(0, _int_safe(raw.get("start_ms"), default=0))
        end_ms = max(start_ms + 1, _int_safe(raw.get("end_ms"), default=start_ms + max(1, _int_safe(raw.get("duration_ms"), default=1))))
        normalized.append(
            {
                "segment_ref": _clean(raw.get("segment_ref")),
                "speaker": _clean(raw.get("speaker")),
                "text": _clean(raw.get("text")),
                "start_ms": start_ms,
                "end_ms": end_ms,
                "duration_ms": max(1, end_ms - start_ms),
                "mouth_cues": _normalize_mouth_cues(raw.get("mouth_cues")),
            }
        )
    normalized.sort(key=lambda segment: _int_safe(segment.get("start_ms"), default=0))
    return normalized


def _normalize_mouth_cues(raw_cues: object) -> list[dict[str, object]]:
    if not isinstance(raw_cues, list):
        return []
    cues: list[dict[str, object]] = []
    for raw in raw_cues:
        if not isinstance(raw, dict):
            continue
        start_ms = max(0, _int_safe(raw.get("start_ms"), default=0))
        end_ms = max(start_ms + 1, _int_safe(raw.get("end_ms"), default=start_ms + 1))
        mouth = _clean(raw.get("mouth")).upper() or "X"
        cues.append({"start_ms": start_ms, "end_ms": end_ms, "mouth": mouth})
    cues.sort(key=lambda cue: _int_safe(cue.get("start_ms"), default=0))
    return cues


def _mouth_for_time(*, segment: dict[str, object] | None, time_ms: int) -> str:
    if not isinstance(segment, dict):
        return ""
    cues = segment.get("mouth_cues")
    if not isinstance(cues, list) or not cues:
        return ""
    segment_start_ms = _int_safe(segment.get("start_ms"), default=0)
    rel_time_ms = max(0, int(time_ms) - segment_start_ms)
    for cue in cues:
        if not isinstance(cue, dict):
            continue
        cue_start_ms = max(0, _int_safe(cue.get("start_ms"), default=0))
        cue_end_ms = max(cue_start_ms + 1, _int_safe(cue.get("end_ms"), default=cue_start_ms + 1))
        if cue_start_ms <= rel_time_ms < cue_end_ms:
            return _clean(cue.get("mouth")).upper() or "X"
    last = cues[-1]
    if isinstance(last, dict):
        return _clean(last.get("mouth")).upper() or "X"
    return ""


def _turn_for_progress(*, scene_turns: list[CartoonDialogueTurn], progress: float) -> CartoonDialogueTurn | None:
    if not scene_turns:
        return None
    safe_progress = min(max(float(progress), 0.0), 1.0)
    index = int(round(safe_progress * (len(scene_turns) - 1)))
    return scene_turns[max(0, min(index, len(scene_turns) - 1))]


def _int_safe(value: object, *, default: int) -> int:
    try:
        if isinstance(value, bool):
            return default
        if isinstance(value, (int, float, str)):
            return int(value)
        return int(str(value))
    except (TypeError, ValueError):
        return default


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _clean(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _bool_from_metadata(*, payload: CartoonPayload, key: str, default: bool) -> bool:
    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        return default
    value = metadata.get(key)
    if isinstance(value, bool):
        return value
    text = _clean(value).lower()
    if text in {"true", "1", "yes", "on"}:
        return True
    if text in {"false", "0", "no", "off"}:
        return False
    return default
