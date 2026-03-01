from __future__ import annotations

from typing import Protocol

from main_app.contracts import VideoPayload


class VideoExporter(Protocol):
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
    ) -> tuple[bytes | None, str | None]: ...
