from __future__ import annotations

import json
import re
from html import escape
from typing import Any

import streamlit as st

from main_app.models import GroqSettings
from main_app.services.audio_overview_service import AudioOverviewService
from main_app.services.background_jobs import BackgroundJobContext, BackgroundJobManager
from main_app.services.cached_llm_service import CachedLLMService
from main_app.ui.components import render_background_job_panel
from main_app.ui.error_handling import UI_HANDLED_EXCEPTIONS, report_ui_error

AUDIO_OVERVIEW_TAB_CSS = """
<style>
    .ao-title {
        font-size: 1.9rem;
        font-weight: 760;
        color: #0f172a;
        margin: 2px 0 4px 0;
    }
    .ao-subtitle {
        color: #475569;
        margin: 0 0 12px 0;
    }
    .ao-card {
        border: 1px solid #e2e8f0;
        border-radius: 14px;
        background: linear-gradient(145deg, #f8fafc 0%, #f1f5f9 100%);
        padding: 14px;
        margin-bottom: 10px;
    }
    .ao-meta {
        color: #334155;
        font-size: 0.92rem;
        font-weight: 650;
        margin: 0 0 8px 0;
    }
    .ao-speaker {
        border: 1px solid #dbeafe;
        border-radius: 12px;
        background: #eff6ff;
        padding: 10px;
        margin-bottom: 8px;
    }
    .ao-speaker-name {
        margin: 0;
        color: #1e3a8a;
        font-weight: 700;
    }
    .ao-speaker-role {
        margin: 2px 0 0 0;
        color: #1f2937;
        font-size: 0.92rem;
    }
    .ao-turn {
        border: 1px solid #e5e7eb;
        border-radius: 12px;
        background: #ffffff;
        padding: 10px 12px;
        margin-bottom: 8px;
    }
    .ao-turn-speaker {
        margin: 0 0 4px 0;
        color: #1f2937;
        font-size: 0.94rem;
        font-weight: 700;
    }
    .ao-turn-text {
        margin: 0;
        color: #111827;
        line-height: 1.45;
    }
</style>
"""


_AUDIO_DEFAULT_USE_HINGLISH_SCRIPT = False


def _resolve_audio_language(*, selected_language: str, use_hinglish_script: bool) -> str:
    if use_hinglish_script:
        return "hi"
    return " ".join(str(selected_language).split()).strip() or "en"


def render_audio_overview_tab(
    *,
    audio_overview_service: AudioOverviewService,
    llm_service: CachedLLMService,
    settings: GroqSettings,
    cache_count_placeholder: Any,
    job_manager: BackgroundJobManager,
) -> None:
    _apply_audio_overview_job_result(
        job_manager=job_manager,
        llm_service=llm_service,
        cache_count_placeholder=cache_count_placeholder,
    )

    st.markdown(AUDIO_OVERVIEW_TAB_CSS, unsafe_allow_html=True)
    st.markdown('<div class="ao-title">Audio Overview</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="ao-subtitle">Generate a multi-speaker podcast-style conversation with distinct voices per speaker.</div>',
        unsafe_allow_html=True,
    )

    setup_col, control_col = st.columns([0.72, 0.28], gap="large")
    with setup_col:
        topic = st.text_input(
            "Audio Topic",
            placeholder="e.g. Segment Trees for Interviews and Competitive Programming",
            key="audio_overview_topic_input",
        )
        constraints = st.text_area(
            "Optional Audio Constraints",
            placeholder="e.g. Focus on real-world examples, pitfalls, and implementation decisions.",
            height=90,
            key="audio_overview_constraints",
        )

    with control_col:
        st.markdown("#### Episode Controls")
        speaker_count = st.slider(
            "Speakers",
            min_value=2,
            max_value=6,
            value=2,
            step=1,
            key="audio_overview_speaker_count",
        )
        turn_count = st.slider(
            "Dialogue Turns",
            min_value=6,
            max_value=28,
            value=12,
            step=2,
            key="audio_overview_turn_count",
        )
        conversation_style = st.selectbox(
            "Conversation Style",
            options=["Educational Discussion", "Interview", "Roundtable", "Debate"],
            index=0,
            key="audio_overview_style",
        )
        language = st.selectbox(
            "Audio Language",
            options=["en", "hi", "es", "fr", "de", "ja"],
            index=0,
            key="audio_overview_tts_language",
        )
        slow_audio = st.checkbox("Slow narration", value=False, key="audio_overview_tts_slow")
        use_youtube_prompt = st.checkbox(
            "Use YouTube-style prompt",
            value=False,
            key="audio_overview_use_youtube_prompt",
        )
        use_hinglish_script = st.checkbox(
            "Use Hinglish narration script (Roman)",
            value=_AUDIO_DEFAULT_USE_HINGLISH_SCRIPT,
            key="audio_overview_use_hinglish_script",
        )
        generate_audio_overview = st.button(
            "Generate Audio Overview",
            type="primary",
            key="generate_audio_overview",
            width="stretch",
        )

    if generate_audio_overview:
        if not settings.has_api_key():
            st.error("Please enter your Groq API key in the sidebar.")
            st.stop()
        if not settings.has_model():
            st.error("Please select or enter a valid model.")
            st.stop()
        if not topic or not topic.strip():
            st.error("Please enter a topic.")
            st.stop()

        topic_clean = topic.strip()
        constraints_clean = constraints.strip()
        playback_language = _resolve_audio_language(
            selected_language=language,
            use_hinglish_script=bool(use_hinglish_script),
        )

        def _worker(context: BackgroundJobContext) -> dict[str, Any]:
            context.update_progress(progress=0.1, message="Generating podcast script...")
            result = audio_overview_service.generate(
                topic=topic_clean,
                speaker_count=speaker_count,
                turn_count=turn_count,
                conversation_style=conversation_style,
                constraints=constraints_clean,
                use_youtube_prompt=use_youtube_prompt,
                use_hinglish_script=bool(use_hinglish_script),
                settings=settings,
            )
            context.raise_if_cancelled()

            payload = result.parsed_overview
            audio_bytes: bytes | None = None
            audio_error = ""
            if payload and not result.parse_error:
                context.update_progress(progress=0.65, message="Synthesizing audio...")
                audio_bytes, synth_error = audio_overview_service.synthesize_mp3(
                    overview_payload=payload,
                    language=playback_language,
                    slow=slow_audio,
                )
                audio_error = synth_error or ""

            context.raise_if_cancelled()
            context.update_progress(progress=1.0, message="Audio overview generation completed.")
            return {
                "topic": topic_clean,
                "constraints": constraints_clean,
                "language": playback_language,
                "slow_audio": bool(slow_audio),
                "result": result,
                "audio_bytes": audio_bytes,
                "audio_error": audio_error,
                "youtube_prompt": use_youtube_prompt,
                "use_hinglish_script": bool(use_hinglish_script),
            }

        job_id = job_manager.submit(
            label=f"Audio Overview: {topic_clean}",
            worker=_worker,
            metadata={"asset": "audio_overview", "topic": topic_clean},
        )
        st.session_state.audio_overview_background_job_id = job_id
        st.session_state.audio_overview_background_job_applied_id = ""
        st.info("Audio overview request queued in background.")
        st.rerun()

    active_job_id = str(st.session_state.get("audio_overview_background_job_id", "")).strip()
    if active_job_id:
        replacement_job_id = render_background_job_panel(
            manager=job_manager,
            job_id=active_job_id,
            title="Audio Overview Generation Job",
            key_prefix="audio_overview_background_job",
        )
        if replacement_job_id != active_job_id:
            st.session_state.audio_overview_background_job_id = replacement_job_id
            st.session_state.audio_overview_background_job_applied_id = ""
            st.rerun()

    if not st.session_state.audio_overview_payload:
        return

    payload: dict[str, Any] = st.session_state.audio_overview_payload
    speakers: list[dict[str, str]] = payload.get("speakers", [])
    dialogue: list[dict[str, str]] = payload.get("dialogue", [])
    title = str(payload.get("title", "")).strip() or "Audio Overview"
    topic = str(st.session_state.audio_overview_topic or payload.get("topic", "")).strip()
    summary = str(payload.get("summary", "")).strip()

    with st.container(border=True):
        st.markdown(
            (
                '<div class="ao-card">'
                f'<div class="ao-meta">Topic: {escape(topic or "N/A")}</div>'
                f'<h4 style="margin: 0; color: #0f172a;">{escape(title)}</h4>'
                f'<p style="margin: 8px 0 0 0; color: #475569;">Speakers: {len(speakers)} | Turns: {len(dialogue)}</p>'
                "</div>"
            ),
            unsafe_allow_html=True,
        )

    if speakers:
        st.markdown("#### Speakers")
        speaker_cols = st.columns(min(len(speakers), 3), gap="small")
        for idx, speaker in enumerate(speakers):
            col = speaker_cols[idx % len(speaker_cols)]
            with col:
                st.markdown(
                    (
                        '<div class="ao-speaker">'
                        f'<p class="ao-speaker-name">{escape(speaker.get("name", "Speaker"))}</p>'
                        f'<p class="ao-speaker-role">{escape(speaker.get("role", ""))}</p>'
                        "</div>"
                    ),
                    unsafe_allow_html=True,
                )

    st.markdown("#### Transcript")
    with st.container(border=True):
        for turn in dialogue:
            speaker_name = str(turn.get("speaker", "Speaker")).strip() or "Speaker"
            text = str(turn.get("text", "")).strip()
            st.markdown(
                (
                    '<div class="ao-turn">'
                    f'<p class="ao-turn-speaker">{escape(speaker_name)}</p>'
                    f'<p class="ao-turn-text">{escape(text)}</p>'
                    "</div>"
                ),
                unsafe_allow_html=True,
            )

    if summary:
        with st.expander("Episode Summary", expanded=False):
            st.write(summary)

    st.markdown("#### Audio")
    audio_bytes: bytes | None = st.session_state.audio_overview_audio_bytes
    audio_error = str(st.session_state.audio_overview_audio_error).strip()

    if audio_bytes:
        st.audio(audio_bytes, format="audio/mp3")
    elif audio_error:
        st.warning(audio_error)

    regen_col, _ = st.columns([0.28, 0.72])
    with regen_col:
        if st.button("Regenerate Audio", key="audio_overview_regen_audio", width="stretch"):
            try:
                with st.spinner("Synthesizing audio..."):
                    audio_bytes, audio_error = audio_overview_service.synthesize_mp3(
                        overview_payload=payload,
                        language=st.session_state.audio_overview_tts_language,
                        slow=bool(st.session_state.audio_overview_tts_slow),
                    )
                st.session_state.audio_overview_audio_bytes = audio_bytes
                st.session_state.audio_overview_audio_error = audio_error or ""
                if audio_error:
                    st.warning(audio_error)
                else:
                    st.success("Audio regenerated.")
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(f"Audio synthesis failed: {exc}")

    safe_topic = re.sub(r"[^a-zA-Z0-9_-]+", "_", (topic or "audio_overview"))[:60].strip("_") or "audio_overview"
    script_markdown = _audio_overview_to_markdown(payload)

    dl_col_1, dl_col_2, dl_col_3 = st.columns(3)
    with dl_col_1:
        st.download_button(
            "Download Transcript (.md)",
            data=script_markdown,
            file_name=f"{safe_topic}_audio_overview.md",
            mime="text/markdown",
            key="download_audio_overview_md",
            width="stretch",
        )
    with dl_col_2:
        st.download_button(
            "Download Script (.json)",
            data=json.dumps(payload, ensure_ascii=False, indent=2),
            file_name=f"{safe_topic}_audio_overview.json",
            mime="application/json",
            key="download_audio_overview_json",
            width="stretch",
        )
    with dl_col_3:
        if audio_bytes:
            st.download_button(
                "Download Audio (.mp3)",
                data=audio_bytes,
                file_name=f"{safe_topic}_audio_overview.mp3",
                mime="audio/mpeg",
                key="download_audio_overview_mp3",
                width="stretch",
            )
        else:
            st.button(
                "Download Audio (.mp3)",
                disabled=True,
                key="download_audio_overview_mp3_disabled",
                width="stretch",
            )


def _audio_overview_to_markdown(payload: dict[str, Any]) -> str:
    topic = str(payload.get("topic", "")).strip()
    title = str(payload.get("title", "")).strip() or "Audio Overview"
    speakers = payload.get("speakers") or []
    dialogue = payload.get("dialogue") or []
    summary = str(payload.get("summary", "")).strip()

    lines = [f"# {title}", ""]
    if topic:
        lines.append(f"Topic: {topic}")
        lines.append("")

    lines.append("## Speakers")
    if isinstance(speakers, list):
        for speaker in speakers:
            if not isinstance(speaker, dict):
                continue
            name = str(speaker.get("name", "")).strip()
            role = str(speaker.get("role", "")).strip()
            if not name:
                continue
            lines.append(f"- {name}" + (f" ({role})" if role else ""))
    lines.append("")

    lines.append("## Transcript")
    if isinstance(dialogue, list):
        for turn in dialogue:
            if not isinstance(turn, dict):
                continue
            speaker = str(turn.get("speaker", "Speaker")).strip() or "Speaker"
            text = str(turn.get("text", "")).strip()
            if text:
                lines.append(f"- **{speaker}:** {text}")
    lines.append("")

    if summary:
        lines.append("## Summary")
        lines.append(summary)
        lines.append("")

    return "\n".join(lines)


def _apply_audio_overview_job_result(
    *,
    job_manager: BackgroundJobManager,
    llm_service: CachedLLMService,
    cache_count_placeholder: Any,
) -> None:
    job_id = str(st.session_state.get("audio_overview_background_job_id", "")).strip()
    if not job_id:
        return
    snapshot = job_manager.get_snapshot(job_id)
    if snapshot is None or not snapshot.is_terminal:
        return

    applied_id = str(st.session_state.get("audio_overview_background_job_applied_id", "")).strip()
    if applied_id == job_id:
        return
    st.session_state.audio_overview_background_job_applied_id = job_id

    if snapshot.status == "cancelled":
        st.warning("Audio overview generation was cancelled.")
        return
    if snapshot.status == "failed":
        st.error(f"Audio overview generation failed: {snapshot.error or 'Unknown error'}")
        return

    payload = snapshot.result
    if not isinstance(payload, dict):
        st.error("Audio overview background job returned unexpected payload.")
        return

    result = payload.get("result")
    if result is None:
        st.error("Audio overview background job did not return generation result.")
        return

    try:
        parse_note = str(getattr(result, "parse_note", "") or "").strip()
        parse_error = str(getattr(result, "parse_error", "") or "").strip()
        raw_text = str(getattr(result, "raw_text", "") or "")
        cache_hit = bool(getattr(result, "cache_hit", False))
        parsed_overview = getattr(result, "parsed_overview", None)
    except UI_HANDLED_EXCEPTIONS as exc:
        report_ui_error(action="audio_overview_apply_job_result", exc=exc)
        return

    if parse_note:
        st.info(parse_note)

    if parse_error or not isinstance(parsed_overview, dict):
        st.error(parse_error or "Audio overview generation failed.")
        if raw_text:
            st.caption("Debug raw response:")
            st.code(raw_text)
        return

    topic = " ".join(str(payload.get("topic", "")).split()).strip()
    constraints = " ".join(str(payload.get("constraints", "")).split()).strip()
    language = " ".join(str(payload.get("language", "en")).split()).strip() or "en"
    slow_audio = bool(payload.get("slow_audio", False))
    youtube_prompt = bool(payload.get("youtube_prompt", False))
    use_hinglish_script = bool(payload.get("use_hinglish_script", False))
    audio_bytes = payload.get("audio_bytes")
    audio_error = " ".join(str(payload.get("audio_error", "")).split()).strip()

    st.session_state.audio_overview_topic = topic
    st.session_state.audio_overview_payload = parsed_overview
    st.session_state.audio_overview_audio_bytes = audio_bytes if isinstance(audio_bytes, (bytes, bytearray)) else None
    st.session_state.audio_overview_audio_error = audio_error
    st.session_state.audio_overview_last_constraints = constraints
    st.session_state.audio_overview_tts_language = language
    st.session_state.audio_overview_tts_slow = slow_audio
    st.session_state.audio_overview_use_youtube_prompt = youtube_prompt
    st.session_state.audio_overview_use_hinglish_script = use_hinglish_script

    if cache_hit:
        st.info("Audio script served from cache.")
    else:
        cache_count_placeholder.caption(f"Cached responses: {llm_service.count}")

    if audio_error:
        st.warning(audio_error)
    st.success("Audio overview generated.")
