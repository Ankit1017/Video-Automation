from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Callable

import streamlit as st

from main_app.contracts import CartoonPayload


CartoonBuildFn = Callable[[str, CartoonPayload], tuple[dict[str, bytes], str | None]]


@dataclass(frozen=True)
class CartoonRenderConfig:
    build_button_key: str
    outputs_state_key: str
    output_error_state_key: str
    download_script_key: str
    download_project_key: str
    download_shorts_key: str
    download_widescreen_key: str


def render_cartoon_view(
    *,
    topic: str,
    cartoon_payload: CartoonPayload,
    config: CartoonRenderConfig,
    build_cartoon_fn: CartoonBuildFn,
    initial_outputs: dict[str, bytes] | None = None,
    initial_error: str = "",
) -> None:
    if config.outputs_state_key not in st.session_state:
        st.session_state[config.outputs_state_key] = dict(initial_outputs or {})
    if config.output_error_state_key not in st.session_state:
        st.session_state[config.output_error_state_key] = str(initial_error or "")

    _render_timeline_diagnostics(cartoon_payload=cartoon_payload)

    if st.button("Build Cartoon MP4 Outputs", type="primary", key=config.build_button_key):
        with st.spinner("Rendering cartoon shorts outputs..."):
            outputs, error = build_cartoon_fn(topic, cartoon_payload)
        st.session_state[config.outputs_state_key] = dict(outputs)
        st.session_state[config.output_error_state_key] = str(error or "")
        if error:
            st.warning(error)
        elif outputs:
            st.success("Cartoon outputs rendered successfully.")
        st.rerun()

    outputs = st.session_state.get(config.outputs_state_key)
    output_error = str(st.session_state.get(config.output_error_state_key, "")).strip()
    outputs_map = dict(outputs) if isinstance(outputs, dict) else {}
    if output_error:
        st.warning(output_error)

    shorts_bytes = outputs_map.get("shorts_9_16")
    widescreen_bytes = outputs_map.get("widescreen_16_9")
    if isinstance(shorts_bytes, (bytes, bytearray)):
        st.markdown("#### 9:16 Shorts Preview")
        st.video(bytes(shorts_bytes))
    if isinstance(widescreen_bytes, (bytes, bytearray)):
        st.markdown("#### 16:9 Widescreen Preview")
        st.video(bytes(widescreen_bytes))

    safe_topic = re.sub(r"[^a-zA-Z0-9_-]+", "_", topic.strip())[:60].strip("_") or "cartoon_shorts"
    script_markdown = str(cartoon_payload.get("script_markdown", "") or "")
    project_json = json.dumps(cartoon_payload, ensure_ascii=False, indent=2)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.download_button(
            "Download Script (.md)",
            data=script_markdown,
            file_name=f"{safe_topic}_script.md",
            mime="text/markdown",
            key=config.download_script_key,
            width="stretch",
        )
    with col2:
        st.download_button(
            "Download Project (.json)",
            data=project_json,
            file_name=f"{safe_topic}_project.json",
            mime="application/json",
            key=config.download_project_key,
            width="stretch",
        )
    with col3:
        if isinstance(shorts_bytes, (bytes, bytearray)):
            st.download_button(
                "Download 9:16 (.mp4)",
                data=bytes(shorts_bytes),
                file_name=f"{safe_topic}_shorts_9_16.mp4",
                mime="video/mp4",
                key=config.download_shorts_key,
                width="stretch",
            )
        else:
            st.button("Download 9:16 (.mp4)", disabled=True, key=f"{config.download_shorts_key}_disabled", width="stretch")
    with col4:
        if isinstance(widescreen_bytes, (bytes, bytearray)):
            st.download_button(
                "Download 16:9 (.mp4)",
                data=bytes(widescreen_bytes),
                file_name=f"{safe_topic}_widescreen_16_9.mp4",
                mime="video/mp4",
                key=config.download_widescreen_key,
                width="stretch",
            )
        else:
            st.button(
                "Download 16:9 (.mp4)",
                disabled=True,
                key=f"{config.download_widescreen_key}_disabled",
                width="stretch",
            )


def _render_timeline_diagnostics(*, cartoon_payload: CartoonPayload) -> None:
    timeline = cartoon_payload.get("timeline", {})
    timeline_map = timeline if isinstance(timeline, dict) else {}
    scenes = timeline_map.get("scenes", [])
    scenes_list = [scene for scene in scenes if isinstance(scene, dict)] if isinstance(scenes, list) else []
    total_turns = 0
    for scene in scenes_list:
        turns = scene.get("turns", [])
        if isinstance(turns, list):
            total_turns += len([turn for turn in turns if isinstance(turn, dict)])
    profile = cartoon_payload.get("render_profile", {})
    profile_map = profile if isinstance(profile, dict) else {}

    with st.expander("Cartoon Timeline Diagnostics", expanded=False):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Scenes", len(scenes_list))
        c2.metric("Turns", total_turns)
        c3.metric("Speakers", len(cartoon_payload.get("character_roster", [])) if isinstance(cartoon_payload.get("character_roster", []), list) else 0)
        c4.metric("Render Profile", " ".join(str(profile_map.get("profile_key", "n/a")).split()).strip() or "n/a")
        st.caption(
            "Output mode: "
            + (" ".join(str(cartoon_payload.get("output_mode", "dual")).split()).strip() or "dual")
        )

