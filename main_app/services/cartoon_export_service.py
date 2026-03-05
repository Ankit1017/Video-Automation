from __future__ import annotations

from dataclasses import dataclass
import base64
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
    CartoonOutputArtifact,
    CartoonPayload,
    CartoonQualityTier,
    CartoonRenderProfile,
    CartoonRenderStyle,
    CartoonScene,
)
from main_app.services.cartoon_character_asset_validator import CartoonCharacterAssetValidator
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
        cinematic_mode = _bool_from_metadata(payload=cartoon_payload, key="cinematic_story_mode", default=True)
        targets = self._build_targets(profile=profile, output_mode=selected_mode, quality_tier=quality_tier)
        render_root: Path | None = None
        outputs: dict[str, bytes] = {}
        output_artifacts: list[CartoonOutputArtifact] = []
        lottie_cache_service: CartoonLottieCacheService | None = None

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
                        },
                    )
                )
                self._telemetry_service.record_metric(
                    name="cartoon_scene_count",
                    value=float(len(_timeline_scenes(cartoon_payload))),
                    attrs={"output_mode": selected_mode, "quality_tier": quality_tier},
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
            timed_segments = _metadata_audio_segments(metadata_map.get("audio_segments"))
            audio_b64 = metadata_map.get("audio_b64")
            if isinstance(audio_b64, str):
                try:
                    audio_path.write_bytes(base64.b64decode(audio_b64.encode("utf-8"), validate=True))
                except (ValueError, OSError):
                    pass

            if timeline_schema_version == "v2":
                pack_root = _pack_root_from_payload(cartoon_payload)
                lottie_cache_service = CartoonLottieCacheService(pack_root=pack_root)
                if self._telemetry_service is not None:
                    self._telemetry_service.record_event(
                        ObservabilityEvent(
                            event_name="cartoon.pack.validate.start",
                            component="export.cartoon",
                            status="started",
                            timestamp=_now_iso(),
                            attributes={"pack_root": str(pack_root)},
                        )
                    )
                validator = CartoonCharacterAssetValidator(pack_root=pack_root)
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
                if self._telemetry_service is not None:
                    self._telemetry_service.record_event(
                        ObservabilityEvent(
                            event_name="cartoon.pack.validate.end",
                            component="export.cartoon",
                            status="ok",
                            timestamp=_now_iso(),
                            attributes={"errors": 0},
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
                                timeline_schema_version=timeline_schema_version,
                                render_style=render_style,
                                background_style=background_style,
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

            cartoon_payload["output_artifacts"] = output_artifacts
            cartoon_payload["render_profile"] = profile
            cartoon_payload["quality_tier"] = quality_tier
            cartoon_payload["timeline_schema_version"] = cast(Any, timeline_schema_version)
            cartoon_payload["render_style"] = render_style
            cartoon_payload["background_style"] = background_style
            metadata = cartoon_payload.get("metadata", {})
            if isinstance(metadata, dict):
                metadata["render_style"] = render_style
                metadata["background_style"] = background_style
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
    ) -> list[_RenderTarget]:
        fps = _tier_adjusted_fps(_int_safe(profile.get("fps"), default=24), quality_tier=quality_tier)
        targets: list[_RenderTarget] = []
        if output_mode in {"dual", "shorts_9_16"}:
            targets.append(
                _RenderTarget(
                    key="shorts_9_16",
                    width=max(360, _int_safe(profile.get("shorts_width"), default=1080)),
                    height=max(640, _int_safe(profile.get("shorts_height"), default=1920)),
                    fps=fps,
                )
            )
        if output_mode in {"dual", "widescreen_16_9"}:
            targets.append(
                _RenderTarget(
                    key="widescreen_16_9",
                    width=max(640, _int_safe(profile.get("widescreen_width"), default=1920)),
                    height=max(360, _int_safe(profile.get("widescreen_height"), default=1080)),
                    fps=fps,
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


def _tier_adjusted_fps(base_fps: int, *, quality_tier: CartoonQualityTier) -> int:
    safe = max(12, int(base_fps))
    if quality_tier == "light":
        return max(12, min(24, int(round(safe * 0.7))))
    if quality_tier == "high":
        return max(safe, 30)
    return max(16, safe)


def _pack_root_from_payload(payload: CartoonPayload) -> Path:
    metadata = payload.get("metadata", {})
    metadata_map = metadata if isinstance(metadata, dict) else {}
    pack = metadata_map.get("pack")
    if isinstance(pack, dict):
        pack_root = _clean(pack.get("pack_root"))
        if pack_root:
            return Path(pack_root)
    return Path(__file__).resolve().parents[1] / "assets" / "cartoon_packs" / "default"


def _timeline_scenes(payload: CartoonPayload) -> list[CartoonScene]:
    timeline = payload.get("timeline", {})
    if not isinstance(timeline, dict):
        return []
    scenes = timeline.get("scenes", [])
    if not isinstance(scenes, list):
        return []
    return [scene for scene in scenes if isinstance(scene, dict)]


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
