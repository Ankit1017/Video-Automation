from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path
import shutil
import tempfile
from time import perf_counter
from typing import Any, Literal, cast

from main_app.shared.slideshow.representation_normalizer import (
    is_progressive_representation,
    normalize_slide_representation,
)
from main_app.contracts import (
    DialogueAudioSegment,
    JSONValue,
    SlideContent,
    VideoConversationTimeline,
    VideoPayload,
    VideoRenderProfile,
)
from main_app.services.video_avatar_lipsync_service import VideoAvatarLipsyncService
from main_app.services.video_avatar_overlay_service import VideoAvatarOverlayService
from main_app.services.video_dialogue_audio_service import VideoDialogueAudioService
from main_app.services.video_render_profile_service import VideoRenderProfileService
from main_app.services.observability_service import ensure_request_id
from main_app.services.telemetry_service import ObservabilityEvent, TelemetryService
from main_app.services.text_sanitizer import sanitize_text


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _VideoTemplateStyle:
    key: str
    top_bg: tuple[int, int, int]
    bottom_bg: tuple[int, int, int]
    meta_color: tuple[int, int, int]
    section_color: tuple[int, int, int]
    title_color: tuple[int, int, int]
    bullet_color: tuple[int, int, int]
    code_box_fill: tuple[int, int, int]
    code_box_outline: tuple[int, int, int]
    code_text_color: tuple[int, int, int]
    accent_color: tuple[int, int, int]
    title_size: int
    meta_size: int
    bullet_size: int
    code_size: int


class VideoExportService:
    _WIDTH = 1280
    _HEIGHT = 720
    _FPS = 24
    _ANIMATION_STYLES = {"none", "smooth", "youtube_dynamic"}
    _TEMPLATES: dict[str, _VideoTemplateStyle] = {
        "standard": _VideoTemplateStyle(
            key="standard",
            top_bg=(18, 37, 70),
            bottom_bg=(7, 13, 26),
            meta_color=(214, 233, 255),
            section_color=(163, 203, 255),
            title_color=(255, 255, 255),
            bullet_color=(235, 242, 252),
            code_box_fill=(13, 24, 45),
            code_box_outline=(72, 96, 134),
            code_text_color=(212, 227, 244),
            accent_color=(66, 134, 244),
            title_size=44,
            meta_size=22,
            bullet_size=28,
            code_size=18,
        ),
        "youtube": _VideoTemplateStyle(
            key="youtube",
            top_bg=(25, 28, 34),
            bottom_bg=(8, 10, 14),
            meta_color=(240, 240, 240),
            section_color=(255, 92, 92),
            title_color=(255, 255, 255),
            bullet_color=(242, 242, 242),
            code_box_fill=(17, 20, 27),
            code_box_outline=(226, 51, 51),
            code_text_color=(238, 238, 238),
            accent_color=(235, 52, 52),
            title_size=46,
            meta_size=22,
            bullet_size=29,
            code_size=18,
        ),
    }

    def __init__(self, *, telemetry_service: TelemetryService | None = None) -> None:
        self._telemetry_service = telemetry_service
        self._render_profile_service = VideoRenderProfileService()
        self._dialogue_audio_service = VideoDialogueAudioService()
        self._avatar_lipsync_service = VideoAvatarLipsyncService()
        self._avatar_overlay_service = VideoAvatarOverlayService()

    def build_video_mp4(
        self,
        *,
        topic: str,
        video_payload: VideoPayload,
        audio_bytes: bytes,
        template_key: str | None = None,
        animation_style: str | None = None,
        render_mode: str | None = None,
        render_profile: dict[str, object] | None = None,
        allow_fallback: bool | None = None,
    ) -> tuple[bytes | None, str | None]:
        request_id = ensure_request_id()
        started_at = perf_counter()
        if self._telemetry_service is not None:
            with self._telemetry_service.context_scope(request_id=request_id):
                self._telemetry_service.record_event(
                    ObservabilityEvent(
                        event_name="export.video.start",
                        component="export.video_mp4",
                        status="started",
                        timestamp=_now_iso(),
                        attributes={
                            "topic": topic,
                            "template_key": template_key or "",
                            "animation_style": animation_style or "",
                            "render_mode": render_mode or str(video_payload.get("render_mode", "")),
                        },
                    )
                )
        if not audio_bytes:
            return None, "Audio is required before building full video."

        slides = video_payload.get("slides", [])
        if not isinstance(slides, list) or not slides:
            return None, "No slides found in video payload."

        try:
            from PIL import Image, ImageDraw, ImageFont  # type: ignore
            self._ensure_pillow_resample_compat(image_module=Image)
            from moviepy.editor import AudioFileClip, ImageClip, concatenate_videoclips, vfx  # type: ignore
        except ImportError:
            return None, "Video export requires `moviepy` and `Pillow`. Install dependencies and retry."

        selected_template_key = self._resolve_template_key(template_key=template_key, video_payload=video_payload)
        selected_animation_style = self._resolve_animation_style(
            animation_style=animation_style,
            video_payload=video_payload,
            selected_template_key=selected_template_key,
        )
        selected_render_mode = self._resolve_render_mode(render_mode=render_mode, video_payload=video_payload)
        raw_metadata = video_payload.get("metadata", {})
        metadata = cast(dict[str, JSONValue], raw_metadata if isinstance(raw_metadata, dict) else {})
        video_payload["metadata"] = metadata
        avatar_subtitles = bool(
            metadata.get("avatar_enable_subtitles", True)
        )
        avatar_style_pack = " ".join(
            str(metadata.get("avatar_style_pack", "default")).split()
        ).strip().lower() or "default"
        should_allow_fallback = (
            bool(allow_fallback)
            if allow_fallback is not None
            else bool(metadata.get("avatar_allow_fallback", _env_flag("VIDEO_AVATAR_ALLOW_FALLBACK", True)))
        )
        selected_profile = self._coerce_render_profile(render_profile) if render_profile is not None else self._render_profile_service.select_profile()
        video_payload["render_profile"] = selected_profile
        video_payload["render_mode"] = selected_render_mode
        applied_width = _safe_int(selected_profile.get("width"), default=self._WIDTH)
        applied_height = _safe_int(selected_profile.get("height"), default=self._HEIGHT)
        applied_fps = _safe_int(selected_profile.get("fps"), default=self._FPS)
        previous_width = self._WIDTH
        previous_height = self._HEIGHT
        previous_fps = self._FPS
        self._WIDTH = max(640, applied_width)
        self._HEIGHT = max(360, applied_height)
        self._FPS = max(15, applied_fps)
        metadata["render_mode_requested"] = selected_render_mode
        metadata["render_profile_key"] = str(selected_profile.get("profile_key", "unknown"))
        metadata["render_resolution"] = f"{self._WIDTH}x{self._HEIGHT}"
        metadata["render_fps"] = self._FPS
        metadata["avatar_allow_fallback"] = should_allow_fallback

        if self._telemetry_service is not None:
            self._telemetry_service.record_metric(
                name="video_render_profile_selected_total",
                value=1.0,
                attrs={"profile_key": str(selected_profile.get("profile_key", "unknown"))},
            )
        template = self._TEMPLATES[selected_template_key]

        audio_clip = None
        video_clip = None
        all_visual_clips: list[Any] = []
        render_root: Path | None = None
        fallback_used = False
        try:
            render_root = self._create_render_workdir()
            audio_path = render_root / "narration.mp3"
            output_path = render_root / "rendered_video.mp4"
            audio_path.write_bytes(audio_bytes)

            audio_clip = AudioFileClip(self._moviepy_path(audio_path))
            audio_duration = max(float(audio_clip.duration or 0.0), 1.0)
            slide_durations = self._compute_slide_durations(
                slides=slides,
                slide_scripts=video_payload.get("slide_scripts"),
                audio_duration=audio_duration,
            )
            if self._telemetry_service is not None:
                self._telemetry_service.record_event(
                    ObservabilityEvent(
                        event_name="video.conversation_timeline.start",
                        component="export.video_mp4",
                        status="started",
                        timestamp=_now_iso(),
                        attributes={"slide_count": len(slides)},
                    )
                )
            timeline_map = self._timeline_turns_by_slide(video_payload=video_payload)
            flat_timeline = [
                turn
                for turns in timeline_map.values()
                for turn in turns
            ]
            if self._telemetry_service is not None:
                timeline_payload_ref = self._telemetry_service.attach_payload(
                    payload={"timeline_turns": flat_timeline},
                    kind="video_conversation_timeline",
                )
                self._telemetry_service.record_event(
                    ObservabilityEvent(
                        event_name="video.conversation_timeline.end",
                        component="export.video_mp4",
                        status="ok",
                        timestamp=_now_iso(),
                        attributes={"turn_count": len(flat_timeline)},
                        payload_ref=timeline_payload_ref,
                    )
                )
            if self._telemetry_service is not None:
                self._telemetry_service.record_event(
                    ObservabilityEvent(
                        event_name="video.dialogue_audio.start",
                        component="export.video_mp4",
                        status="started",
                        timestamp=_now_iso(),
                        attributes={"mode": selected_render_mode},
                    )
                )
            segment_timing = self._dialogue_audio_service.build_segment_timing(
                timeline=cast(VideoConversationTimeline | None, video_payload.get("conversation_timeline")),
            )
            segment_lookup = {
                str(segment.get("segment_ref", "")).strip(): segment
                for segment in segment_timing
                if str(segment.get("segment_ref", "")).strip()
            }
            if self._telemetry_service is not None:
                dialogue_payload_ref = self._telemetry_service.attach_payload(
                    payload={"segment_timing": segment_timing},
                    kind="video_dialogue_audio_segments",
                )
                self._telemetry_service.record_event(
                    ObservabilityEvent(
                        event_name="video.dialogue_audio.end",
                        component="export.video_mp4",
                        status="ok",
                        timestamp=_now_iso(),
                        attributes={"segment_count": len(segment_timing)},
                        payload_ref=dialogue_payload_ref,
                    )
                )
            render_mode_in_use = selected_render_mode

            try:
                for index, (slide, duration) in enumerate(zip(slides, slide_durations, strict=False), start=1):
                    if render_mode_in_use == "avatar_conversation":
                        slide_clips = self._build_avatar_slide_clips(
                            slide=slide if isinstance(slide, dict) else {},
                            topic=topic,
                            index=index,
                            total=len(slides),
                            duration=float(duration),
                            path_prefix=render_root / f"slide_{index:03d}",
                            image_module=Image,
                            draw_module=ImageDraw,
                            font_module=ImageFont,
                            image_clip_cls=ImageClip,
                            moviepy_vfx=vfx,
                            template=template,
                            animation_style=selected_animation_style,
                            timeline_turns=timeline_map.get(index, []),
                            segment_lookup=segment_lookup,
                            speaker_roster=cast(list[dict[str, str]], video_payload.get("speaker_roster", [])),
                            subtitles_enabled=avatar_subtitles,
                            avatar_style_pack=avatar_style_pack,
                            render_profile=selected_profile,
                        )
                        if self._telemetry_service is not None:
                            self._telemetry_service.record_event(
                                ObservabilityEvent(
                                    event_name="video.avatar_overlay.end",
                                    component="export.video_mp4",
                                    status="ok",
                                    timestamp=_now_iso(),
                                    attributes={
                                        "slide_index": index,
                                        "turns": len(timeline_map.get(index, [])),
                                    },
                                )
                            )
                    else:
                        slide_clips = self._build_slide_clips(
                            slide=slide if isinstance(slide, dict) else {},
                            topic=topic,
                            index=index,
                            total=len(slides),
                            duration=float(duration),
                            path_prefix=render_root / f"slide_{index:03d}",
                            image_module=Image,
                            draw_module=ImageDraw,
                            font_module=ImageFont,
                            image_clip_cls=ImageClip,
                            moviepy_vfx=vfx,
                            template=template,
                            animation_style=selected_animation_style,
                        )
                    all_visual_clips.extend(slide_clips)
            except (OSError, RuntimeError, ValueError, TypeError) as avatar_exc:
                if render_mode_in_use == "avatar_conversation" and should_allow_fallback:
                    render_mode_in_use = "classic_slides"
                    fallback_used = True
                    all_visual_clips.clear()
                    if self._telemetry_service is not None:
                        self._telemetry_service.record_metric(
                            name="video_avatar_fallback_total",
                            value=1.0,
                            attrs={"reason": type(avatar_exc).__name__},
                        )
                        payload_ref = self._telemetry_service.attach_payload(
                            payload={"error": str(avatar_exc), "topic": topic},
                            kind="video_avatar_fallback",
                        )
                        self._telemetry_service.record_event(
                            ObservabilityEvent(
                                event_name="video.avatar_fallback",
                                component="export.video_mp4",
                                status="degraded",
                                timestamp=_now_iso(),
                                attributes={"reason": type(avatar_exc).__name__},
                                payload_ref=payload_ref,
                            )
                        )
                    for index, (slide, duration) in enumerate(zip(slides, slide_durations, strict=False), start=1):
                        slide_clips = self._build_slide_clips(
                            slide=slide if isinstance(slide, dict) else {},
                            topic=topic,
                            index=index,
                            total=len(slides),
                            duration=float(duration),
                            path_prefix=render_root / f"slide_{index:03d}",
                            image_module=Image,
                            draw_module=ImageDraw,
                            font_module=ImageFont,
                            image_clip_cls=ImageClip,
                            moviepy_vfx=vfx,
                            template=template,
                            animation_style=selected_animation_style,
                        )
                        all_visual_clips.extend(slide_clips)
                else:
                    raise

            transition_sec = self._transition_seconds(animation_style=selected_animation_style)
            stitched_clips: list[Any] = []
            for idx, clip in enumerate(all_visual_clips):
                if idx > 0 and transition_sec > 0:
                    clip = clip.crossfadein(min(transition_sec, max(float(clip.duration), 0.0) / 2.0))
                stitched_clips.append(clip)

            video_clip = concatenate_videoclips(
                stitched_clips,
                method="compose",
                padding=(-transition_sec if transition_sec > 0 else 0),
            )
            video_clip = video_clip.set_audio(audio_clip)
            video_clip.write_videofile(
                self._moviepy_path(output_path),
                fps=self._FPS,
                codec="libx264",
                audio_codec="aac",
                logger=None,
            )

            if not output_path.exists():
                return None, "Video rendering failed: output file was not produced."
            video_bytes = output_path.read_bytes()
            metadata["render_mode_used"] = render_mode_in_use
            metadata["avatar_fallback_used"] = fallback_used
            metadata["video_output_bytes"] = len(video_bytes)
            metadata["timeline_turn_count"] = len(flat_timeline)
            metadata["timeline_segment_count"] = len(segment_timing)
            if self._telemetry_service is not None:
                with self._telemetry_service.context_scope(request_id=request_id):
                    duration_ms = max((perf_counter() - started_at) * 1000.0, 0.0)
                    payload_ref = self._telemetry_service.attach_payload(
                        payload={
                            "topic": topic,
                            "template_key": selected_template_key,
                            "animation_style": selected_animation_style,
                            "slide_count": len(slides),
                            "render_mode": render_mode_in_use,
                            "render_profile_key": str(selected_profile.get("profile_key", "unknown")),
                            "avatar_fallback_used": fallback_used,
                        },
                        kind="video_export",
                    )
                    self._telemetry_service.record_metric(
                        name="export_video_duration_ms",
                        value=duration_ms,
                        attrs={
                            "status": "ok",
                            "template_key": selected_template_key,
                            "animation_style": selected_animation_style,
                        },
                    )
                    self._telemetry_service.record_metric(
                        name="export_video_bytes_total",
                        value=float(len(video_bytes)),
                        attrs={
                            "status": "ok",
                            "template_key": selected_template_key,
                            "animation_style": selected_animation_style,
                        },
                    )
                    if render_mode_in_use == "avatar_conversation":
                        self._telemetry_service.record_metric(
                            name="video_avatar_pipeline_duration_ms",
                            value=duration_ms,
                            attrs={"profile_key": str(selected_profile.get("profile_key", "unknown"))},
                        )
                    self._telemetry_service.record_event(
                        ObservabilityEvent(
                            event_name="export.video.end",
                            component="export.video_mp4",
                            status="ok",
                            timestamp=_now_iso(),
                            attributes={
                                "duration_ms": round(duration_ms, 3),
                                "bytes": len(video_bytes),
                                "slide_count": len(slides),
                                "template_key": selected_template_key,
                                "animation_style": selected_animation_style,
                                "render_mode": render_mode_in_use,
                                "profile_key": str(selected_profile.get("profile_key", "unknown")),
                            },
                            payload_ref=payload_ref,
                        )
                    )
            return video_bytes, None
        except (OSError, ValueError, RuntimeError, TypeError) as exc:
            if self._telemetry_service is not None:
                with self._telemetry_service.context_scope(request_id=request_id):
                    duration_ms = max((perf_counter() - started_at) * 1000.0, 0.0)
                    self._telemetry_service.record_metric(
                        name="export_video_duration_ms",
                        value=duration_ms,
                        attrs={"status": "error"},
                    )
                    self._telemetry_service.record_event(
                        ObservabilityEvent(
                            event_name="export.video.end",
                            component="export.video_mp4",
                            status="error",
                            timestamp=_now_iso(),
                            attributes={
                                "duration_ms": round(duration_ms, 3),
                                "error": str(exc),
                            },
                        )
                    )
            return None, f"Failed to render video: {exc}"
        finally:
            self._WIDTH = previous_width
            self._HEIGHT = previous_height
            self._FPS = previous_fps
            for clip in all_visual_clips:
                try:
                    clip.close()
                except (AttributeError, OSError, RuntimeError, ValueError) as exc:
                    logger.debug("Video image clip close failed: %s", exc)
            if video_clip is not None:
                try:
                    video_clip.close()
                except (AttributeError, OSError, RuntimeError, ValueError) as exc:
                    logger.debug("Video clip close failed: %s", exc)
            if audio_clip is not None:
                try:
                    audio_clip.close()
                except (AttributeError, OSError, RuntimeError, ValueError) as exc:
                    logger.debug("Audio clip close failed: %s", exc)
            if render_root is not None:
                self._cleanup_render_workdir(render_root)

    @staticmethod
    def _ensure_pillow_resample_compat(*, image_module: Any) -> None:
        # Pillow 10 removed Image.ANTIALIAS, but older moviepy versions still reference it.
        if hasattr(image_module, "ANTIALIAS"):
            return

        resampling = getattr(image_module, "Resampling", None)
        if resampling is not None:
            lanczos = getattr(resampling, "LANCZOS", None)
            if lanczos is not None:
                image_module.ANTIALIAS = lanczos
                return

        fallback_lanczos = getattr(image_module, "LANCZOS", None)
        if fallback_lanczos is not None:
            image_module.ANTIALIAS = fallback_lanczos

    def _build_slide_clips(
        self,
        *,
        slide: SlideContent | dict[str, Any],
        topic: str,
        index: int,
        total: int,
        duration: float,
        path_prefix: Path,
        image_module: Any,
        draw_module: Any,
        font_module: Any,
        image_clip_cls: Any,
        moviepy_vfx: Any,
        template: _VideoTemplateStyle,
        animation_style: str,
    ) -> list[Any]:
        clips: list[Any] = []
        slide_map = cast(dict[str, Any], slide if isinstance(slide, dict) else {})
        normalized_slide, _ = normalize_slide_representation(slide_map)
        has_code = bool(
            sanitize_text(normalized_slide.get("code_snippet", ""), keep_citations=False, preserve_newlines=True)
        )
        if self._should_use_progressive_reveal(slide=normalized_slide, animation_style=animation_style):
            reveal_steps = self._reveal_steps(slide=normalized_slide)
            ratios = self._segment_ratios(count=len(reveal_steps))
            for pos, (revealed_bullets, ratio) in enumerate(zip(reveal_steps, ratios, strict=False)):
                stage_duration = max(0.9, duration * ratio)
                image_path = path_prefix.with_name(f"{path_prefix.name}_stage_{pos+1:02d}.png")
                self._render_slide_image(
                    slide=normalized_slide,
                    topic=topic,
                    index=index,
                    total=total,
                    path=image_path,
                    image_module=image_module,
                    draw_module=draw_module,
                    font_module=font_module,
                    template=template,
                    revealed_bullets=revealed_bullets,
                    code_emphasis=has_code and pos == len(reveal_steps) - 1,
                )
                clip = image_clip_cls(self._moviepy_path(image_path)).set_duration(stage_duration)
                clip = self._apply_motion(
                    clip=clip,
                    duration=stage_duration,
                    animation_style=animation_style,
                    moviepy_vfx=moviepy_vfx,
                )
                clips.append(clip)
            return clips

        image_path = path_prefix.with_suffix(".png")
        self._render_slide_image(
            slide=normalized_slide,
            topic=topic,
            index=index,
            total=total,
            path=image_path,
            image_module=image_module,
            draw_module=draw_module,
            font_module=font_module,
            template=template,
            revealed_bullets=None,
            code_emphasis=False,
        )
        clip = image_clip_cls(self._moviepy_path(image_path)).set_duration(duration)
        clip = self._apply_motion(
            clip=clip,
            duration=duration,
            animation_style=animation_style,
            moviepy_vfx=moviepy_vfx,
        )
        clips.append(clip)
        return clips

    def _build_avatar_slide_clips(
        self,
        *,
        slide: SlideContent | dict[str, Any],
        topic: str,
        index: int,
        total: int,
        duration: float,
        path_prefix: Path,
        image_module: Any,
        draw_module: Any,
        font_module: Any,
        image_clip_cls: Any,
        moviepy_vfx: Any,
        template: _VideoTemplateStyle,
        animation_style: str,
        timeline_turns: list[dict[str, object]],
        segment_lookup: dict[str, DialogueAudioSegment],
        speaker_roster: list[dict[str, str]],
        subtitles_enabled: bool,
        avatar_style_pack: str,
        render_profile: VideoRenderProfile,
    ) -> list[Any]:
        if not timeline_turns:
            return self._build_slide_clips(
                slide=slide,
                topic=topic,
                index=index,
                total=total,
                duration=duration,
                path_prefix=path_prefix,
                image_module=image_module,
                draw_module=draw_module,
                font_module=font_module,
                image_clip_cls=image_clip_cls,
                moviepy_vfx=moviepy_vfx,
                template=template,
                animation_style=animation_style,
            )

        clips: list[Any] = []
        last_speaker = ""
        for turn_pos, turn in enumerate(timeline_turns):
            turn_text = " ".join(str(turn.get("text", "")).split()).strip()
            speaker = " ".join(str(turn.get("speaker", "Speaker")).split()).strip() or "Speaker"
            visual_ref = _as_dict(turn.get("visual_ref"))
            reveal_index = _safe_int(visual_ref.get("item_index"), default=-1)
            revealed_bullets = reveal_index + 1 if reveal_index >= 0 else None
            duration_ms = max(650, _safe_int(turn.get("estimated_duration_ms"), default=0))
            if duration_ms <= 0:
                start_ms = _safe_int(turn.get("start_ms"), default=0)
                end_ms = _safe_int(turn.get("end_ms"), default=start_ms + int(duration * 1000))
                duration_ms = max(650, end_ms - start_ms)
            turn_duration = max(0.65, float(duration_ms) / 1000.0)

            image_path = path_prefix.with_name(f"{path_prefix.name}_avatar_{turn_pos+1:02d}.png")
            self._render_slide_image(
                slide=cast(dict[str, Any], slide if isinstance(slide, dict) else {}),
                topic=topic,
                index=index,
                total=total,
                path=image_path,
                image_module=image_module,
                draw_module=draw_module,
                font_module=font_module,
                template=template,
                revealed_bullets=revealed_bullets,
                code_emphasis=False,
            )
            image = image_module.open(image_path).convert("RGBA")
            segment_ref = " ".join(str(turn.get("segment_ref", "")).split()).strip()
            segment_row = segment_lookup.get(
                segment_ref,
                cast(
                    DialogueAudioSegment,
                    {
                        "segment_ref": segment_ref,
                        "speaker": speaker,
                        "start_ms": _safe_int(turn.get("start_ms"), default=0),
                        "end_ms": _safe_int(turn.get("end_ms"), default=duration_ms),
                        "duration_ms": duration_ms,
                        "text": turn_text,
                        "cache_hit": False,
                    },
                ),
            )
            synthetic_segment = cast(
                DialogueAudioSegment,
                {
                "segment_ref": segment_ref,
                "speaker": speaker,
                "start_ms": _safe_int(segment_row.get("start_ms", turn.get("start_ms")), default=0),
                "end_ms": _safe_int(segment_row.get("end_ms", turn.get("end_ms")), default=duration_ms),
                "duration_ms": _safe_int(segment_row.get("duration_ms"), default=duration_ms),
                "text": turn_text,
                "cache_hit": bool(segment_row.get("cache_hit", False)),
                },
            )
            mouth_cues, lipsync_warning = self._avatar_lipsync_service.build_mouth_cues(
                segment=synthetic_segment,
                segment_audio_wav=None,
            )
            turn["mouth_cues"] = mouth_cues
            if lipsync_warning and self._telemetry_service is not None:
                self._telemetry_service.record_event(
                    ObservabilityEvent(
                        event_name="video.avatar_lipsync.segment",
                        component="export.video_mp4",
                        status="degraded",
                        timestamp=_now_iso(),
                        attributes={
                            "slide_index": index,
                            "segment_ref": segment_ref,
                            "warning": lipsync_warning,
                        },
                    )
                )
            self._avatar_overlay_service.apply_overlay(
                image=image,
                draw_module=draw_module,
                font_module=font_module,
                speaker_roster=speaker_roster,
                active_speaker=speaker,
                last_speaker=last_speaker,
                subtitle_text=turn_text,
                subtitles_enabled=subtitles_enabled,
                style_pack=avatar_style_pack,
                render_profile=render_profile,
            )
            image.save(image_path)
            last_speaker = speaker
            clip = image_clip_cls(self._moviepy_path(image_path)).set_duration(turn_duration)
            clip = self._apply_motion(
                clip=clip,
                duration=turn_duration,
                animation_style=animation_style,
                moviepy_vfx=moviepy_vfx,
            )
            clips.append(clip)
            if self._telemetry_service is not None:
                self._telemetry_service.record_metric(
                    name="video_avatar_segment_duration_ms",
                    value=float(duration_ms),
                    attrs={"slide_index": str(index), "speaker": speaker},
                )
        if self._telemetry_service is not None:
            self._telemetry_service.record_metric(
                name="video_avatar_segments_total",
                value=float(len(clips)),
                attrs={"slide_index": str(index)},
            )
        return clips

    @staticmethod
    def _timeline_turns_by_slide(*, video_payload: VideoPayload) -> dict[int, list[dict[str, object]]]:
        timeline = _as_dict(video_payload.get("conversation_timeline"))
        turns = timeline.get("turns", [])
        mapping: dict[int, list[dict[str, object]]] = {}
        if not isinstance(turns, list):
            return mapping
        for turn in turns:
            if not isinstance(turn, dict):
                continue
            slide_index = _safe_int(turn.get("slide_index"), default=1)
            mapping.setdefault(slide_index, []).append(cast(dict[str, object], turn))
        return mapping

    @staticmethod
    def _resolve_render_mode(
        *,
        render_mode: str | None,
        video_payload: VideoPayload,
    ) -> Literal["avatar_conversation", "classic_slides"]:
        explicit = " ".join(str(render_mode or "").split()).strip().lower()
        if explicit in {"avatar_conversation", "classic_slides"}:
            return cast(Literal["avatar_conversation", "classic_slides"], explicit)
        payload_mode = " ".join(str(video_payload.get("render_mode", "")).split()).strip().lower()
        if payload_mode in {"avatar_conversation", "classic_slides"}:
            return cast(Literal["avatar_conversation", "classic_slides"], payload_mode)
        env_mode = " ".join(str(os.getenv("VIDEO_RENDER_MODE_DEFAULT", "avatar_conversation")).split()).strip().lower()
        if env_mode in {"avatar_conversation", "classic_slides"}:
            return cast(Literal["avatar_conversation", "classic_slides"], env_mode)
        return "avatar_conversation"

    @staticmethod
    def _coerce_render_profile(raw: dict[str, object] | None) -> VideoRenderProfile:
        profile = raw if isinstance(raw, dict) else {}
        return cast(
            VideoRenderProfile,
            {
                "profile_key": " ".join(str(profile.get("profile_key", "gpu_balanced")).split()).strip() or "gpu_balanced",
                "width": max(640, _safe_int(profile.get("width"), default=1280)),
                "height": max(360, _safe_int(profile.get("height"), default=720)),
                "fps": max(15, _safe_int(profile.get("fps"), default=24)),
                "avatar_scale": _safe_float(profile.get("avatar_scale"), default=0.92),
                "animation_level": " ".join(str(profile.get("animation_level", "medium")).split()).strip() or "medium",
                "gpu_available": bool(profile.get("gpu_available", False)),
                "gpu_memory_mb": max(0, _safe_int(profile.get("gpu_memory_mb"), default=0)),
            },
        )

    @staticmethod
    def _should_use_progressive_reveal(*, slide: SlideContent | dict[str, Any], animation_style: str) -> bool:
        slide_map = cast(dict[str, Any], slide if isinstance(slide, dict) else {})
        normalized_slide, _ = normalize_slide_representation(slide_map)
        representation = " ".join(str(normalized_slide.get("representation", "bullet")).split()).strip().lower()
        return animation_style == "youtube_dynamic" and is_progressive_representation(representation)

    def _apply_motion(self, *, clip: Any, duration: float, animation_style: str, moviepy_vfx: Any) -> Any:
        if animation_style == "none":
            return clip

        if animation_style == "smooth":
            start_zoom = 1.0
            end_zoom = 1.05
        else:
            start_zoom = 1.01
            end_zoom = 1.11

        safe_duration = max(duration, 0.05)
        animated = clip.resize(lambda t: start_zoom + (end_zoom - start_zoom) * (float(t) / safe_duration))
        animated = animated.fx(
            moviepy_vfx.crop,
            x_center=self._WIDTH / 2,
            y_center=self._HEIGHT / 2,
            width=self._WIDTH,
            height=self._HEIGHT,
        )
        return animated

    @staticmethod
    def _reveal_steps(*, slide: SlideContent | dict[str, Any]) -> list[int]:
        representation = " ".join(str(slide.get("representation", "bullet")).split()).strip().lower()
        layout_payload = slide.get("layout_payload", {})
        payload = layout_payload if isinstance(layout_payload, dict) else {}
        if representation == "timeline":
            events = payload.get("events", [])
            bullet_count = len(events) if isinstance(events, list) else 0
        elif representation == "process_flow":
            step_items = payload.get("steps", [])
            bullet_count = len(step_items) if isinstance(step_items, list) else 0
        else:
            bullets = slide.get("bullets", [])
            bullet_count = len(bullets) if isinstance(bullets, list) else 0
        if bullet_count <= 1:
            return [max(1, bullet_count)]
        if bullet_count == 2:
            return [1, 2]
        near_full = max(2, bullet_count - 1)
        reveal_steps = [1, near_full, bullet_count]
        deduped: list[int] = []
        for value in reveal_steps:
            if value not in deduped:
                deduped.append(value)
        return deduped

    @staticmethod
    def _segment_ratios(*, count: int) -> list[float]:
        if count <= 1:
            return [1.0]
        if count == 2:
            return [0.42, 0.58]
        if count == 3:
            return [0.24, 0.31, 0.45]
        equal = 1.0 / float(count)
        return [equal for _ in range(count)]

    @staticmethod
    def _transition_seconds(*, animation_style: str) -> float:
        if animation_style == "none":
            return 0.0
        if animation_style == "smooth":
            return 0.28
        return 0.18

    def _compute_slide_durations(
        self,
        *,
        slides: list[SlideContent],
        slide_scripts: Any,
        audio_duration: float,
    ) -> list[float]:
        raw_hints = self._duration_hints_from_scripts(slides=slides, slide_scripts=slide_scripts)
        if not raw_hints:
            per_slide = audio_duration / max(len(slides), 1)
            return [max(2.0, per_slide) for _ in slides]

        total_hint = float(sum(raw_hints))
        if total_hint <= 0:
            per_slide = audio_duration / max(len(slides), 1)
            return [max(2.0, per_slide) for _ in slides]

        scale = audio_duration / total_hint
        durations = [max(2.0, value * scale) for value in raw_hints]
        drift = audio_duration - float(sum(durations))
        if durations:
            durations[-1] = max(2.0, durations[-1] + drift)
        return durations

    @staticmethod
    def _duration_hints_from_scripts(*, slides: list[SlideContent], slide_scripts: Any) -> list[float]:
        scripts = slide_scripts if isinstance(slide_scripts, list) else []
        hints: list[float] = []
        by_index: dict[int, float] = {}

        for pos, script in enumerate(scripts):
            if not isinstance(script, dict):
                continue
            raw_index = script.get("slide_index", pos + 1)
            try:
                slide_index = int(raw_index) - 1
            except (TypeError, ValueError):
                slide_index = pos
            raw_duration = script.get("estimated_duration_sec", 0)
            try:
                duration = float(raw_duration)
            except (TypeError, ValueError):
                duration = 0.0
            if duration <= 0:
                turns = script.get("dialogue", [])
                if isinstance(turns, list):
                    word_count = 0
                    for turn in turns:
                        if isinstance(turn, dict):
                            word_count += len(str(turn.get("text", "")).split())
                    duration = max(6.0, (word_count / 150.0) * 60.0)
                else:
                    duration = 6.0
            by_index[slide_index] = max(3.0, duration)

        for idx, slide in enumerate(slides):
            hint = by_index.get(idx)
            if hint is not None:
                hints.append(hint)
                continue
            slide_dict = slide if isinstance(slide, dict) else {}
            bullet_count = len(slide_dict.get("bullets", [])) if isinstance(slide_dict.get("bullets"), list) else 0
            base = 5.0 + float(bullet_count) * 1.2
            if str(slide_dict.get("code_snippet", "")).strip():
                base += 3.0
            hints.append(max(4.0, base))
        return hints

    def _render_slide_image(
        self,
        *,
        slide: dict[str, Any],
        topic: str,
        index: int,
        total: int,
        path: Path,
        image_module: Any,
        draw_module: Any,
        font_module: Any,
        template: _VideoTemplateStyle,
        revealed_bullets: int | None,
        code_emphasis: bool,
    ) -> None:
        image = image_module.new("RGB", (self._WIDTH, self._HEIGHT), color=template.top_bg)
        draw = draw_module.Draw(image)

        self._draw_gradient_background(
            image=image,
            image_module=image_module,
            top=template.top_bg,
            bottom=template.bottom_bg,
        )

        title_font, title_size = self._load_font(
            font_module=font_module,
            preferred_size=template.title_size,
            bold=True,
            mono=False,
            min_size=30,
        )
        meta_font, _ = self._load_font(
            font_module=font_module,
            preferred_size=template.meta_size,
            bold=False,
            mono=False,
            min_size=18,
        )
        bullet_font, bullet_size = self._load_font(
            font_module=font_module,
            preferred_size=template.bullet_size,
            bold=False,
            mono=False,
            min_size=20,
        )
        code_font, _ = self._load_font(
            font_module=font_module,
            preferred_size=template.code_size,
            bold=False,
            mono=True,
            min_size=14,
        )

        section = sanitize_text(slide.get("section", "Section"), keep_citations=False)
        title = sanitize_text(slide.get("title", f"Slide {index}"), keep_citations=False) or f"Slide {index}"
        safe_topic = sanitize_text(topic, keep_citations=False)

        draw.rectangle(((0, 0), (self._WIDTH, 10)), fill=template.accent_color)
        draw.text((60, 30), f"{safe_topic}  |  {index}/{total}", fill=template.meta_color, font=meta_font)
        draw.text((60, 68), section, fill=template.section_color, font=meta_font)

        title_lines, title_font = self._fit_wrapped_lines(
            draw=draw,
            text=title,
            font_module=font_module,
            preferred_size=title_size,
            min_size=30,
            max_width=self._WIDTH - 120,
            max_lines=2,
            bold=True,
            mono=False,
        )
        y = 118
        for line in title_lines:
            draw.text((60, y), line, fill=template.title_color, font=title_font)
            y += self._line_height(draw=draw, font=title_font, text=line) + 8

        y += 6
        y = self._draw_representation_body(
            draw=draw,
            slide=slide,
            start_y=y,
            bullet_font=bullet_font,
            bullet_size=bullet_size,
            meta_font=meta_font,
            template=template,
            revealed_bullets=revealed_bullets,
        )

        code_text = sanitize_text(slide.get("code_snippet", ""), keep_citations=False, preserve_newlines=True)
        if code_text:
            code_box_top = max(y + 8, 420)
            code_box_bottom = self._HEIGHT - 44
            outline_color = template.accent_color if code_emphasis else template.code_box_outline
            outline_width = 3 if code_emphasis else 2
            draw.rounded_rectangle(
                ((60, code_box_top), (self._WIDTH - 60, code_box_bottom)),
                radius=18,
                fill=template.code_box_fill,
                outline=outline_color,
                width=outline_width,
            )
            code_lines = code_text.splitlines()[:10]
            code_y = code_box_top + 14
            for line in code_lines:
                clean_line = line.rstrip()
                draw.text((80, code_y), clean_line[:105], fill=template.code_text_color, font=code_font)
                code_y += 24

        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path, format="PNG")

    def _draw_representation_body(
        self,
        *,
        draw: Any,
        slide: dict[str, Any],
        start_y: int,
        bullet_font: Any,
        bullet_size: int,
        meta_font: Any,
        template: _VideoTemplateStyle,
        revealed_bullets: int | None,
    ) -> int:
        normalized_slide, _ = normalize_slide_representation(slide if isinstance(slide, dict) else {})
        representation = " ".join(str(normalized_slide.get("representation", "bullet")).split()).strip().lower()
        layout_payload = normalized_slide.get("layout_payload", {})
        payload = layout_payload if isinstance(layout_payload, dict) else {}

        if representation in {"two_column", "comparison"}:
            left_title = sanitize_text(payload.get("left_title", "Left"), keep_citations=False)
            right_title = sanitize_text(payload.get("right_title", "Right"), keep_citations=False)
            left_key = "left_items" if representation == "two_column" else "left_points"
            right_key = "right_items" if representation == "two_column" else "right_points"
            left_items = self._as_text_list(payload.get(left_key), max_items=4)
            right_items = self._as_text_list(payload.get(right_key), max_items=4)
            if not left_items and not right_items:
                fallback = self._as_text_list(normalized_slide.get("bullets", []), max_items=6)
                midpoint = max(1, len(fallback) // 2)
                left_items = fallback[:midpoint]
                right_items = fallback[midpoint:]
            draw.text((70, start_y), left_title or "Left", fill=template.section_color, font=meta_font)
            draw.text((680, start_y), right_title or "Right", fill=template.section_color, font=meta_font)
            left_y = start_y + 34
            right_y = start_y + 34
            left_y = self._draw_bullet_lines(
                draw=draw,
                items=left_items,
                x=70,
                y=left_y,
                max_width=520,
                bullet_font=bullet_font,
                bullet_size=bullet_size,
                color=template.bullet_color,
            )
            right_y = self._draw_bullet_lines(
                draw=draw,
                items=right_items,
                x=680,
                y=right_y,
                max_width=530,
                bullet_font=bullet_font,
                bullet_size=bullet_size,
                color=template.bullet_color,
            )
            return max(left_y, right_y)

        if representation == "timeline":
            events = payload.get("events", [])
            parsed_events: list[dict[str, str]] = []
            if isinstance(events, list):
                for event in events[:5]:
                    if not isinstance(event, dict):
                        continue
                    label = sanitize_text(event.get("label", ""), keep_citations=False)
                    detail = sanitize_text(event.get("detail", ""), keep_citations=False)
                    if not label and not detail:
                        continue
                    parsed_events.append({"label": label or "Milestone", "detail": detail})
            if not parsed_events:
                fallback = self._as_text_list(normalized_slide.get("bullets", []), max_items=5)
                parsed_events = [{"label": f"Milestone {idx + 1}", "detail": text} for idx, text in enumerate(fallback)]

            visible = len(parsed_events) if revealed_bullets is None else max(0, min(len(parsed_events), int(revealed_bullets)))
            y = start_y + 8
            for event in parsed_events[:visible]:
                draw.ellipse(((70, y + 10), (84, y + 24)), fill=template.accent_color)
                draw.text((100, y), event["label"], fill=template.section_color, font=meta_font)
                detail_lines = self._wrap_text_to_width(
                    draw=draw,
                    text=event["detail"],
                    font=bullet_font,
                    max_width=self._WIDTH - 200,
                )[:2]
                line_y = y + 28
                for line in detail_lines:
                    draw.text((100, line_y), line, fill=template.bullet_color, font=bullet_font)
                    line_y += int(bullet_size * 1.1)
                y = line_y + 10
            if visible < len(parsed_events):
                hidden = len(parsed_events) - visible
                draw.text((100, y), f"... {hidden} more milestone(s)", fill=template.meta_color, font=meta_font)
            return y + 12

        if representation == "process_flow":
            steps = payload.get("steps", [])
            parsed_steps: list[dict[str, str]] = []
            if isinstance(steps, list):
                for step in steps[:5]:
                    if not isinstance(step, dict):
                        continue
                    title = sanitize_text(step.get("title", ""), keep_citations=False)
                    detail = sanitize_text(step.get("detail", ""), keep_citations=False)
                    if not title and not detail:
                        continue
                    parsed_steps.append({"title": title or "Step", "detail": detail})
            if not parsed_steps:
                fallback = self._as_text_list(normalized_slide.get("bullets", []), max_items=5)
                parsed_steps = [{"title": f"Step {idx + 1}", "detail": text} for idx, text in enumerate(fallback)]

            visible = len(parsed_steps) if revealed_bullets is None else max(0, min(len(parsed_steps), int(revealed_bullets)))
            y = start_y + 8
            for idx, step in enumerate(parsed_steps[:visible], start=1):
                box_height = 70
                draw.rounded_rectangle(
                    ((70, y), (self._WIDTH - 70, y + box_height)),
                    radius=12,
                    fill=template.code_box_fill,
                    outline=template.code_box_outline,
                    width=2,
                )
                draw.text((90, y + 8), f"{idx}. {step['title']}", fill=template.section_color, font=meta_font)
                detail_lines = self._wrap_text_to_width(
                    draw=draw,
                    text=step["detail"],
                    font=bullet_font,
                    max_width=self._WIDTH - 180,
                )[:2]
                line_y = y + 34
                for line in detail_lines:
                    draw.text((95, line_y), line, fill=template.bullet_color, font=bullet_font)
                    line_y += int(bullet_size * 1.05)
                y += box_height + 10
            if visible < len(parsed_steps):
                hidden = len(parsed_steps) - visible
                draw.text((90, y + 2), f"... {hidden} more step(s)", fill=template.meta_color, font=meta_font)
            return y + 12

        if representation == "metric_cards":
            cards = payload.get("cards", [])
            parsed_cards: list[dict[str, str]] = []
            if isinstance(cards, list):
                for card in cards[:4]:
                    if not isinstance(card, dict):
                        continue
                    label = sanitize_text(card.get("label", ""), keep_citations=False)
                    value = sanitize_text(card.get("value", ""), keep_citations=False)
                    context = sanitize_text(card.get("context", ""), keep_citations=False)
                    if not label and not value and not context:
                        continue
                    parsed_cards.append({"label": label or "Metric", "value": value, "context": context})
            if not parsed_cards:
                fallback = self._as_text_list(normalized_slide.get("bullets", []), max_items=4)
                parsed_cards = [{"label": f"Metric {idx + 1}", "value": text, "context": ""} for idx, text in enumerate(fallback)]

            card_w = 550
            card_h = 110
            positions = [(70, start_y + 8), (660, start_y + 8), (70, start_y + 136), (660, start_y + 136)]
            for idx, card in enumerate(parsed_cards[:4]):
                x, y = positions[idx]
                draw.rounded_rectangle(
                    ((x, y), (x + card_w, y + card_h)),
                    radius=12,
                    fill=template.code_box_fill,
                    outline=template.code_box_outline,
                    width=2,
                )
                draw.text((x + 14, y + 10), card["label"], fill=template.meta_color, font=meta_font)
                value_lines = self._wrap_text_to_width(
                    draw=draw,
                    text=card["value"],
                    font=bullet_font,
                    max_width=card_w - 28,
                )[:2]
                line_y = y + 40
                for line in value_lines:
                    draw.text((x + 14, line_y), line, fill=template.title_color, font=bullet_font)
                    line_y += int(bullet_size * 1.05)
                if card["context"]:
                    draw.text((x + 14, y + card_h - 24), card["context"][:80], fill=template.bullet_color, font=meta_font)
            return start_y + 264

        bullets = self._as_text_list(normalized_slide.get("bullets", []), max_items=6)
        total_bullets = len(bullets)
        visible_bullets = total_bullets if revealed_bullets is None else max(0, min(total_bullets, int(revealed_bullets)))
        y = self._draw_bullet_lines(
            draw=draw,
            items=bullets[:visible_bullets],
            x=70,
            y=start_y,
            max_width=self._WIDTH - 140,
            bullet_font=bullet_font,
            bullet_size=bullet_size,
            color=template.bullet_color,
        )
        if visible_bullets < total_bullets:
            hidden = total_bullets - visible_bullets
            draw.text((70, y + 2), f"... {hidden} more point(s)", fill=template.meta_color, font=meta_font)
        return y

    def _draw_bullet_lines(
        self,
        *,
        draw: Any,
        items: list[str],
        x: int,
        y: int,
        max_width: int,
        bullet_font: Any,
        bullet_size: int,
        color: tuple[int, int, int],
    ) -> int:
        line_y = int(y)
        for bullet in items:
            bullet_text = sanitize_text(bullet, keep_citations=False)
            if not bullet_text:
                continue
            wrapped = self._wrap_text_to_width(
                draw=draw,
                text=bullet_text,
                font=bullet_font,
                max_width=max_width,
            )[:2]
            for idx_line, line in enumerate(wrapped):
                prefix = "- " if idx_line == 0 else "  "
                draw.text((x, line_y), prefix + line, fill=color, font=bullet_font)
                line_y += int(bullet_size * 1.18)
            line_y += 6
        return line_y

    @staticmethod
    def _as_text_list(value: Any, *, max_items: int) -> list[str]:
        if not isinstance(value, list):
            return []
        cleaned: list[str] = []
        for item in value:
            text = sanitize_text(item, keep_citations=False)
            if not text:
                continue
            cleaned.append(text)
            if len(cleaned) >= max_items:
                break
        return cleaned

    @staticmethod
    def _draw_gradient_background(
        *,
        image: Any,
        image_module: Any,
        top: tuple[int, int, int],
        bottom: tuple[int, int, int],
    ) -> None:
        width, height = image.size
        gradient = image_module.new("RGB", (width, height), color=0)
        pixels = gradient.load()
        for y in range(height):
            blend = float(y) / float(max(height - 1, 1))
            r = int(top[0] * (1.0 - blend) + bottom[0] * blend)
            g = int(top[1] * (1.0 - blend) + bottom[1] * blend)
            b = int(top[2] * (1.0 - blend) + bottom[2] * blend)
            for x in range(width):
                pixels[x, y] = (r, g, b)
        image.paste(gradient)

    @classmethod
    def _create_render_workdir(cls) -> Path:
        configured = " ".join(str(os.getenv("VIDEO_RENDER_TMP_DIR", "")).split()).strip()
        candidates: list[Path] = []
        if configured:
            candidates.append(Path(configured))
        candidates.append(Path.cwd() / ".cache" / "video_render")
        candidates.append(Path(tempfile.gettempdir()))

        for root in candidates:
            try:
                root.mkdir(parents=True, exist_ok=True)
                workdir = Path(tempfile.mkdtemp(prefix="video_render_", dir=str(root)))
                if workdir.exists() and workdir.is_dir():
                    return workdir
            except (OSError, RuntimeError, ValueError):
                continue

        return Path(tempfile.mkdtemp(prefix="video_render_"))

    @staticmethod
    def _cleanup_render_workdir(path: Path) -> None:
        try:
            shutil.rmtree(path, ignore_errors=True)
        except (OSError, RuntimeError, ValueError) as exc:
            logger.debug("Failed to cleanup render workdir `%s`: %s", path, exc)

    @staticmethod
    def _moviepy_path(path: Path) -> str:
        normalized = path.resolve()
        if os.name == "nt":
            return normalized.as_posix()
        return str(normalized)

    @classmethod
    def _resolve_template_key(cls, *, template_key: str | None, video_payload: VideoPayload) -> str:
        requested = " ".join(str(template_key or "").split()).strip().lower()
        if requested in cls._TEMPLATES:
            return requested
        payload_key = " ".join(str(video_payload.get("video_template", "")).split()).strip().lower()
        if payload_key in cls._TEMPLATES:
            return payload_key
        return "standard"

    @classmethod
    def _resolve_animation_style(
        cls,
        *,
        animation_style: str | None,
        video_payload: VideoPayload,
        selected_template_key: str,
    ) -> str:
        del animation_style, video_payload, selected_template_key
        # Static-first policy: keep slide visuals stable (no zoom/crossfade motion).
        return "none"

    @staticmethod
    def _font_candidates(*, bold: bool, mono: bool) -> list[str]:
        if mono:
            return [
                r"C:\Windows\Fonts\consola.ttf",
                r"C:\Windows\Fonts\cour.ttf",
                "Consolas.ttf",
                "DejaVuSansMono.ttf",
                "/System/Library/Fonts/Menlo.ttc",
                "/System/Library/Fonts/SFNSMono.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            ]
        if bold:
            return [
                r"C:\Windows\Fonts\arialbd.ttf",
                r"C:\Windows\Fonts\segoeuib.ttf",
                "Arial Bold.ttf",
                "DejaVuSans-Bold.ttf",
                "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                "/System/Library/Fonts/Supplemental/Helvetica Bold.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            ]
        return [
            r"C:\Windows\Fonts\arial.ttf",
            r"C:\Windows\Fonts\segoeui.ttf",
            "Arial.ttf",
            "DejaVuSans.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/System/Library/Fonts/Supplemental/Helvetica.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]

    @classmethod
    def _load_font(
        cls,
        *,
        font_module: Any,
        preferred_size: int,
        bold: bool,
        mono: bool,
        min_size: int,
    ) -> tuple[object, int]:
        font_candidates = cls._font_candidates(bold=bold, mono=mono)
        size = int(preferred_size)
        while size >= int(min_size):
            for candidate in font_candidates:
                try:
                    return font_module.truetype(candidate, size), size
                except (OSError, AttributeError, RuntimeError):
                    continue
            size -= 1
        return font_module.load_default(), int(min_size)

    @staticmethod
    def _measure_text(*, draw: Any, text: str, font: Any) -> tuple[int, int]:
        try:
            left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
            return max(1, right - left), max(1, bottom - top)
        except AttributeError:
            width, height = draw.textsize(text, font=font)
            return max(1, int(width)), max(1, int(height))

    @classmethod
    def _line_height(cls, *, draw: Any, font: Any, text: str = "Ag") -> int:
        _, height = cls._measure_text(draw=draw, text=text, font=font)
        return max(1, int(height))

    @classmethod
    def _wrap_text_to_width(cls, *, draw: Any, text: str, font: Any, max_width: int) -> list[str]:
        words = [item for item in str(text).split() if item]
        if not words:
            return []

        lines: list[str] = []
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            width, _ = cls._measure_text(draw=draw, text=candidate, font=font)
            if width <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
        return lines

    @classmethod
    def _fit_wrapped_lines(
        cls,
        *,
        draw: Any,
        text: str,
        font_module: Any,
        preferred_size: int,
        min_size: int,
        max_width: int,
        max_lines: int,
        bold: bool,
        mono: bool,
    ) -> tuple[list[str], object]:
        size = int(preferred_size)
        while size >= int(min_size):
            font, _ = cls._load_font(
                font_module=font_module,
                preferred_size=size,
                bold=bold,
                mono=mono,
                min_size=size,
            )
            wrapped = cls._wrap_text_to_width(
                draw=draw,
                text=text,
                font=font,
                max_width=max_width,
            )
            if wrapped and len(wrapped) <= max_lines:
                return wrapped, font
            size -= 1

        final_font, _ = cls._load_font(
            font_module=font_module,
            preferred_size=min_size,
            bold=bold,
            mono=mono,
            min_size=min_size,
        )
        wrapped = cls._wrap_text_to_width(draw=draw, text=text, font=final_font, max_width=max_width)
        if not wrapped:
            return [text], final_font
        return wrapped[:max_lines], final_font


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _as_dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _safe_int(value: object, *, default: int) -> int:
    try:
        if isinstance(value, bool):
            return default
        if isinstance(value, (int, float, str)):
            return int(value)
        return int(str(value))
    except (TypeError, ValueError):
        return default


def _safe_float(value: object, *, default: float) -> float:
    try:
        if isinstance(value, bool):
            return default
        if isinstance(value, (int, float, str)):
            return float(value)
        return float(str(value))
    except (TypeError, ValueError):
        return default


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = " ".join(raw.split()).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default
