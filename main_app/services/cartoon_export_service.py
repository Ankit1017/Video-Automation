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
    CartoonCharacterSpec,
    CartoonDialogueTurn,
    CartoonOutputArtifact,
    CartoonPayload,
    CartoonRenderProfile,
    CartoonScene,
)
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


class CartoonExportService:
    def __init__(self, *, telemetry_service: TelemetryService | None = None) -> None:
        self._telemetry_service = telemetry_service
        self._profile_service = CartoonRenderProfileService()
        self._scene_renderer = CartoonSceneRenderer()

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
        cinematic_mode = _bool_from_metadata(payload=cartoon_payload, key="cinematic_story_mode", default=True)
        targets = self._build_targets(profile=profile, output_mode=selected_mode)
        render_root: Path | None = None
        outputs: dict[str, bytes] = {}
        output_artifacts: list[CartoonOutputArtifact] = []

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
                        },
                    )
                )
                self._telemetry_service.record_metric(
                    name="cartoon_scene_count",
                    value=float(len(_timeline_scenes(cartoon_payload))),
                    attrs={"output_mode": selected_mode},
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
            audio_b64 = metadata_map.get("audio_b64")
            if isinstance(audio_b64, str):
                try:
                    audio_path.write_bytes(base64.b64decode(audio_b64.encode("utf-8"), validate=True))
                except (ValueError, OSError):
                    pass

            for target in targets:
                if self._telemetry_service is not None:
                    self._telemetry_service.record_event(
                        ObservabilityEvent(
                            event_name="cartoon.render.format.start",
                            component="export.cartoon",
                            status="started",
                            timestamp=_now_iso(),
                            attributes={"format_key": target.key, "width": target.width, "height": target.height, "fps": target.fps},
                        )
                    )
                clips: list[Any] = []
                clip_paths: list[Path] = []
                audio_clip = None
                try:
                    scenes = _timeline_scenes(cartoon_payload)
                    for scene in scenes:
                        scene_idx = _int_safe(scene.get("scene_index"), default=0)
                        duration_sec = max(1.2, _int_safe(scene.get("duration_ms"), default=4000) / 1000.0)
                        frame_total = max(2, int(round(duration_sec * float(target.fps)))) if cinematic_mode else 1
                        frame_paths: list[str] = []
                        scene_turns = _scene_turns(scene)
                        for frame_idx in range(frame_total):
                            frame_path = render_root / f"{target.key}_scene_{scene_idx:03d}_f{frame_idx:04d}.png"
                            active_turn = _turn_for_progress(scene_turns=scene_turns, progress=frame_idx / max(frame_total - 1, 1))
                            frame = self._scene_renderer.render_frame(
                                image_module=Image,
                                draw_module=ImageDraw,
                                font_module=ImageFont,
                                width=target.width,
                                height=target.height,
                                topic=topic,
                                scene=scene,
                                active_turn=active_turn,
                                character_roster=cast(list[CartoonCharacterSpec], cartoon_payload.get("character_roster", [])),
                                frame_index=frame_idx,
                                frame_count=frame_total,
                                cinematic_mode=cinematic_mode,
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

            cartoon_payload["output_artifacts"] = output_artifacts
            cartoon_payload["render_profile"] = profile
            duration_ms = max((perf_counter() - started_at) * 1000.0, 0.0)
            if self._telemetry_service is not None:
                with self._telemetry_service.context_scope(request_id=request_id):
                    self._telemetry_service.record_metric(
                        name="cartoon_render_duration_ms",
                        value=duration_ms,
                        attrs={"output_mode": selected_mode, "status": "ok" if outputs else "error"},
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

    def _build_targets(self, *, profile: CartoonRenderProfile, output_mode: str) -> list[_RenderTarget]:
        fps = max(12, _int_safe(profile.get("fps"), default=24))
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
