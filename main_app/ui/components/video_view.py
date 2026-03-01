from __future__ import annotations

from dataclasses import dataclass
from html import escape
import json
import re
from typing import Any, Callable, cast

import streamlit as st

from main_app.contracts import VideoPayload, VideoSlideScript
from main_app.services.slide_deck_exporter import SlideDeckExporter
from main_app.ui.components.slideshow_view import SlideshowRenderConfig, render_slideshow_view


VideoSynthesizeFn = Callable[[VideoPayload, str, bool], tuple[bytes | None, str | None]]
VideoBuildFn = Callable[[str, VideoPayload, bytes], tuple[bytes | None, str | None]]


@dataclass(frozen=True)
class VideoRenderConfig:
    slideshow: SlideshowRenderConfig
    language_select_key: str
    slow_checkbox_key: str
    regenerate_audio_key: str
    audio_state_bytes_key: str
    audio_state_error_key: str
    download_script_md_key: str
    download_script_json_key: str
    download_audio_key: str
    download_audio_disabled_key: str
    regenerate_video_key: str
    video_state_bytes_key: str
    video_state_error_key: str
    download_video_key: str
    download_video_disabled_key: str


def render_video_view(
    *,
    topic: str,
    video_payload: VideoPayload,
    config: VideoRenderConfig,
    slide_exporter: SlideDeckExporter,
    synthesize_audio_fn: VideoSynthesizeFn,
    build_video_fn: VideoBuildFn,
    initial_audio_bytes: bytes | None = None,
    initial_audio_error: str = "",
    initial_video_bytes: bytes | None = None,
    initial_video_error: str = "",
) -> None:
    slides = video_payload.get("slides", [])
    slide_scripts = video_payload.get("slide_scripts", [])
    speaker_roster = video_payload.get("speaker_roster", [])
    if not isinstance(slides, list) or not slides:
        st.warning("No slides available in video payload.")
        return
    if not isinstance(slide_scripts, list):
        slide_scripts = []
    if not isinstance(speaker_roster, list):
        speaker_roster = []

    if config.audio_state_bytes_key not in st.session_state:
        st.session_state[config.audio_state_bytes_key] = initial_audio_bytes
    if config.audio_state_error_key not in st.session_state:
        st.session_state[config.audio_state_error_key] = str(initial_audio_error or "")
    if config.video_state_bytes_key not in st.session_state:
        st.session_state[config.video_state_bytes_key] = initial_video_bytes
    if config.video_state_error_key not in st.session_state:
        st.session_state[config.video_state_error_key] = str(initial_video_error or "")
    if config.language_select_key not in st.session_state:
        st.session_state[config.language_select_key] = "en"
    if config.slow_checkbox_key not in st.session_state:
        st.session_state[config.slow_checkbox_key] = False

    total_turns = sum(
        len(script.get("dialogue", []))
        for script in slide_scripts
        if isinstance(script, dict) and isinstance(script.get("dialogue"), list)
    )
    st.caption(
        f"Slides: {len(slides)} | Speakers: {len(speaker_roster)} | Narration turns: {total_turns}"
    )

    render_slideshow_view(
        topic=topic,
        slides=cast(list[dict[str, Any]], [slide for slide in slides if isinstance(slide, dict)]),
        config=config.slideshow,
        slide_exporter=slide_exporter,
    )

    current_idx = int(st.session_state.get(config.slideshow.state_index_key, 0))
    current_script = _script_for_slide_index(slide_scripts=slide_scripts, slide_index=current_idx)
    st.markdown("---")
    st.markdown("#### Slide Narration Script")
    if not current_script:
        st.caption("No narration script mapped to the current slide.")
    else:
        summary = str(current_script.get("summary", "")).strip()
        if summary:
            st.caption(summary)

        dialogue = current_script.get("dialogue", [])
        with st.container(border=True):
            if isinstance(dialogue, list):
                for turn in dialogue:
                    if not isinstance(turn, dict):
                        continue
                    speaker = " ".join(str(turn.get("speaker", "Speaker")).split()).strip() or "Speaker"
                    text = " ".join(str(turn.get("text", "")).split()).strip()
                    if not text:
                        continue
                    st.markdown(
                        (
                            '<div style="border:1px solid #dbeafe;background:#f8fbff;'
                            'border-radius:12px;padding:10px 12px;margin-bottom:8px;">'
                            f'<p style="margin:0 0 4px 0;font-weight:700;color:#1e3a8a;">{escape(speaker)}</p>'
                            f'<p style="margin:0;color:#111827;line-height:1.45;">{escape(text)}</p>'
                            "</div>"
                        ),
                        unsafe_allow_html=True,
                    )

    st.markdown("#### Narrated Audio")
    controls_col_1, controls_col_2, controls_col_3 = st.columns([0.3, 0.3, 0.4], vertical_alignment="bottom")
    with controls_col_1:
        st.selectbox(
            "Audio Language",
            options=["en", "hi", "es", "fr", "de", "ja"],
            key=config.language_select_key,
        )
    with controls_col_2:
        st.checkbox("Slow narration", key=config.slow_checkbox_key)
    with controls_col_3:
        if st.button("Regenerate Narrated Audio", key=config.regenerate_audio_key, width="stretch"):
            with st.spinner("Synthesizing multi-voice narration..."):
                audio_bytes, audio_error = synthesize_audio_fn(
                    video_payload,
                    str(st.session_state[config.language_select_key]),
                    bool(st.session_state[config.slow_checkbox_key]),
                )
            st.session_state[config.audio_state_bytes_key] = audio_bytes
            st.session_state[config.audio_state_error_key] = str(audio_error or "")
            if audio_error:
                st.warning(audio_error)
            else:
                st.success("Narrated audio generated.")
                st.session_state[config.video_state_bytes_key] = None
                st.session_state[config.video_state_error_key] = ""
            st.rerun()

    audio_bytes = st.session_state.get(config.audio_state_bytes_key)
    audio_error = str(st.session_state.get(config.audio_state_error_key, "")).strip()
    if audio_bytes:
        st.audio(audio_bytes, format="audio/mp3")
    elif audio_error:
        st.warning(audio_error)
    else:
        st.caption("No audio generated yet. Click `Regenerate Narrated Audio`.")

    st.markdown("#### Full Video")
    video_col_1, video_col_2 = st.columns([0.38, 0.62], vertical_alignment="bottom")
    with video_col_1:
        if st.button("Build Full Video (MP4)", key=config.regenerate_video_key, width="stretch"):
            if not audio_bytes:
                st.warning("Generate audio first, then build full video.")
            else:
                with st.spinner("Rendering full MP4 video from slides + audio..."):
                    video_bytes, video_error = build_video_fn(topic, video_payload, audio_bytes)
                st.session_state[config.video_state_bytes_key] = video_bytes
                st.session_state[config.video_state_error_key] = str(video_error or "")
                if video_error:
                    st.warning(video_error)
                else:
                    st.success("Full video rendered.")
                st.rerun()
    with video_col_2:
        if st.session_state.get(config.video_state_bytes_key):
            st.caption("Video ready. You can play it below or download MP4.")
        else:
            st.caption("Render MP4 from the current slides and narration audio.")

    video_bytes = st.session_state.get(config.video_state_bytes_key)
    video_error = str(st.session_state.get(config.video_state_error_key, "")).strip()
    if video_bytes:
        st.video(video_bytes)
    elif video_error:
        st.warning(video_error)

    safe_topic = re.sub(r"[^a-zA-Z0-9_-]+", "_", topic.strip())[:60].strip("_") or "video"
    script_markdown = _video_scripts_to_markdown(topic=topic, payload=video_payload)
    dl_col_1, dl_col_2, dl_col_3, dl_col_4 = st.columns(4)
    with dl_col_1:
        st.download_button(
            "Download Video Script (.md)",
            data=script_markdown,
            file_name=f"{safe_topic}_video_script.md",
            mime="text/markdown",
            key=config.download_script_md_key,
            width="stretch",
        )
    with dl_col_2:
        st.download_button(
            "Download Video JSON",
            data=json.dumps(video_payload, ensure_ascii=False, indent=2),
            file_name=f"{safe_topic}_video_payload.json",
            mime="application/json",
            key=config.download_script_json_key,
            width="stretch",
        )
    with dl_col_3:
        if audio_bytes:
            st.download_button(
                "Download Narrated Audio (.mp3)",
                data=audio_bytes,
                file_name=f"{safe_topic}_video_audio.mp3",
                mime="audio/mpeg",
                key=config.download_audio_key,
                width="stretch",
            )
        else:
            st.button(
                "Download Narrated Audio (.mp3)",
                disabled=True,
                key=config.download_audio_disabled_key,
                width="stretch",
            )
    with dl_col_4:
        if video_bytes:
            st.download_button(
                "Download Full Video (.mp4)",
                data=video_bytes,
                file_name=f"{safe_topic}_video.mp4",
                mime="video/mp4",
                key=config.download_video_key,
                width="stretch",
            )
        else:
            st.button(
                "Download Full Video (.mp4)",
                disabled=True,
                key=config.download_video_disabled_key,
                width="stretch",
            )


def _script_for_slide_index(*, slide_scripts: list[VideoSlideScript], slide_index: int) -> dict[str, Any] | None:
    for pos, script in enumerate(slide_scripts):
        if not isinstance(script, dict):
            continue
        raw_idx = script.get("slide_index", pos + 1)
        try:
            normalized = int(raw_idx) - 1
        except (TypeError, ValueError):
            normalized = pos
        if normalized == slide_index:
            return cast(dict[str, Any], script)
    if 0 <= slide_index < len(slide_scripts):
        item = slide_scripts[slide_index]
        if isinstance(item, dict):
            return cast(dict[str, Any], item)
    return None


def _video_scripts_to_markdown(*, topic: str, payload: VideoPayload) -> str:
    lines: list[str] = [f"# {topic.strip() or 'Video Script'}", ""]

    speakers = payload.get("speaker_roster", [])
    if isinstance(speakers, list) and speakers:
        lines.append("## Speakers")
        for item in speakers:
            if isinstance(item, dict):
                name = " ".join(str(item.get("name", "")).split()).strip()
                role = " ".join(str(item.get("role", "")).split()).strip()
            else:
                name = " ".join(str(item).split()).strip()
                role = ""
            if name:
                lines.append(f"- {name}" + (f" ({role})" if role else ""))
        lines.append("")

    scripts = payload.get("slide_scripts", [])
    if isinstance(scripts, list):
        lines.append("## Slide Narration")
        lines.append("")
        for idx, script in enumerate(scripts, start=1):
            if not isinstance(script, dict):
                continue
            title = " ".join(str(script.get("slide_title", f"Slide {idx}")).split()).strip() or f"Slide {idx}"
            lines.append(f"### Slide {idx}: {title}")
            summary = " ".join(str(script.get("summary", "")).split()).strip()
            if summary:
                lines.append(summary)
                lines.append("")
            dialogue = script.get("dialogue", [])
            if isinstance(dialogue, list):
                for turn in dialogue:
                    if not isinstance(turn, dict):
                        continue
                    speaker = " ".join(str(turn.get("speaker", "Speaker")).split()).strip() or "Speaker"
                    text = " ".join(str(turn.get("text", "")).split()).strip()
                    if text:
                        lines.append(f"- **{speaker}:** {text}")
            lines.append("")

    return "\n".join(lines)
