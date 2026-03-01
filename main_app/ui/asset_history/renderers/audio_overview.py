from __future__ import annotations

import json
import re
from html import escape
from typing import cast

import streamlit as st

from main_app.contracts import AudioOverviewPayload, DialogueTurn, AudioSpeaker
from main_app.models import AssetHistoryRecord
from main_app.ui.asset_history.context import AssetHistoryRenderContext


def _as_audio_payload(value: object) -> AudioOverviewPayload | None:
    if not isinstance(value, dict):
        return None
    return cast(AudioOverviewPayload, value)


def _speakers(payload: AudioOverviewPayload) -> list[AudioSpeaker]:
    raw = payload.get("speakers", [])
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _dialogue(payload: AudioOverviewPayload) -> list[DialogueTurn]:
    raw = payload.get("dialogue", [])
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def render_audio_overview_record(record: AssetHistoryRecord, context: AssetHistoryRenderContext) -> None:
    payload = _as_audio_payload(record.result_payload)
    if payload is None:
        st.json(record.result_payload)
        return

    scope = f"asset_history_audio_{record.id}"
    audio_key = f"{scope}_audio_bytes"
    audio_error_key = f"{scope}_audio_error"
    language_key = f"{scope}_language"
    slow_key = f"{scope}_slow"

    if audio_key not in st.session_state:
        st.session_state[audio_key] = None
    if audio_error_key not in st.session_state:
        st.session_state[audio_error_key] = ""
    if language_key not in st.session_state:
        st.session_state[language_key] = str(record.request_payload.get("language", "en")) or "en"
    if slow_key not in st.session_state:
        st.session_state[slow_key] = bool(record.request_payload.get("slow_audio", False))

    speakers = _speakers(payload)
    dialogue = _dialogue(payload)
    title = str(payload.get("title", "")).strip() or "Audio Overview"
    topic = record.topic or str(payload.get("topic", "")).strip()
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
                if isinstance(speaker, dict):
                    speaker_name = str(speaker.get("name", "Speaker"))
                    speaker_role = str(speaker.get("role", ""))
                else:
                    speaker_name = str(speaker)
                    speaker_role = ""
                st.markdown(
                    (
                        '<div class="ao-speaker">'
                        f'<p class="ao-speaker-name">{escape(speaker_name)}</p>'
                        f'<p class="ao-speaker-role">{escape(speaker_role)}</p>'
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

    controls_col_1, controls_col_2, controls_col_3 = st.columns([0.32, 0.32, 0.36])
    with controls_col_1:
        st.selectbox(
            "Audio Language",
            options=["en", "hi", "es", "fr", "de", "ja"],
            key=language_key,
        )
    with controls_col_2:
        st.checkbox("Slow narration", key=slow_key)
    with controls_col_3:
        if st.button("Regenerate Audio", key=f"{scope}_regen", width="stretch"):
            try:
                with st.spinner("Synthesizing audio..."):
                    audio_bytes, audio_error = context.audio_overview_service.synthesize_mp3(
                        overview_payload=payload,
                        language=st.session_state[language_key],
                        slow=bool(st.session_state[slow_key]),
                    )
                st.session_state[audio_key] = audio_bytes
                st.session_state[audio_error_key] = audio_error or ""
                if audio_error:
                    st.warning(audio_error)
                else:
                    st.success("Audio generated.")
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(f"Audio synthesis failed: {exc}")

    st.markdown("#### Audio")
    audio_bytes = st.session_state[audio_key]
    audio_error = str(st.session_state[audio_error_key]).strip()
    if audio_bytes:
        st.audio(audio_bytes, format="audio/mp3")
    elif audio_error:
        st.warning(audio_error)
    else:
        st.caption("No audio cached for this history record yet. Click `Regenerate Audio`.")

    safe_topic = re.sub(r"[^a-zA-Z0-9_-]+", "_", (topic or "audio_overview"))[:60].strip("_") or "audio_overview"
    script_markdown = audio_overview_to_markdown(payload)

    dl_col_1, dl_col_2, dl_col_3 = st.columns(3)
    with dl_col_1:
        st.download_button(
            "Download Transcript (.md)",
            data=script_markdown,
            file_name=f"{safe_topic}_audio_overview.md",
            mime="text/markdown",
            key=f"{scope}_download_md",
            width="stretch",
        )
    with dl_col_2:
        st.download_button(
            "Download Script (.json)",
            data=json.dumps(payload, ensure_ascii=False, indent=2),
            file_name=f"{safe_topic}_audio_overview.json",
            mime="application/json",
            key=f"{scope}_download_json",
            width="stretch",
        )
    with dl_col_3:
        if audio_bytes:
            st.download_button(
                "Download Audio (.mp3)",
                data=audio_bytes,
                file_name=f"{safe_topic}_audio_overview.mp3",
                mime="audio/mpeg",
                key=f"{scope}_download_mp3",
                width="stretch",
            )
        else:
            st.button(
                "Download Audio (.mp3)",
                disabled=True,
                key=f"{scope}_download_mp3_disabled",
                width="stretch",
            )


def audio_overview_to_markdown(payload: AudioOverviewPayload) -> str:
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
            speaker_name = str(turn.get("speaker", "Speaker")).strip() or "Speaker"
            text = str(turn.get("text", "")).strip()
            if text:
                lines.append(f"- **{speaker_name}:** {text}")
    lines.append("")

    if summary:
        lines.append("## Summary")
        lines.append(summary)
        lines.append("")

    return "\n".join(lines)
