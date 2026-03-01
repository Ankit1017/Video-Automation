from __future__ import annotations

from html import escape
from typing import Any, cast

import streamlit as st

from main_app.contracts import IntentPayload
from main_app.services.agent_dashboard import normalize_intent
from main_app.ui.agent_dashboard.context import AgentAssetRenderContext
from main_app.ui.agent_dashboard.render_handlers import (
    AgentAsset,
    AgentAssetRenderHandler,
    build_default_render_handlers,
    render_unknown_asset,
)


def _as_intent_payload(value: object) -> IntentPayload:
    if not isinstance(value, dict):
        return {}
    return cast(IntentPayload, {str(key): item for key, item in value.items()})


class AgentAssetRenderer:
    def __init__(
        self,
        context: AgentAssetRenderContext,
        render_handlers: dict[str, AgentAssetRenderHandler] | None = None,
    ) -> None:
        self._context = context
        self._render_handlers: dict[str, AgentAssetRenderHandler] = build_default_render_handlers()
        for intent, handler in (render_handlers or {}).items():
            normalized_intent = normalize_intent(intent)
            if normalized_intent:
                self._render_handlers[normalized_intent] = handler

    def render_assets_in_chat(self, *, assets: list[dict[str, Any]], item_idx: int) -> None:
        for asset_idx, asset in enumerate(assets):
            intent = str(asset.get("intent", "unknown"))
            status = str(asset.get("status", "error"))
            title = str(asset.get("title", intent)).strip() or intent
            scope = f"{item_idx}_{asset_idx}"

            with st.container(border=True):
                st.markdown(
                    (
                        '<div class="ad-asset-card">'
                        f'<p class="ad-asset-title">{escape(title)}</p>'
                        f'<p class="ad-asset-meta">Intent: {escape(intent)} | Status: {escape(status)}</p>'
                        "</div>"
                    ),
                    unsafe_allow_html=True,
                )

                if status != "success":
                    st.error(str(asset.get("error", "Asset generation failed.")))
                    raw_text = asset.get("raw_text")
                    if raw_text:
                        with st.expander("Raw model response", expanded=False):
                            st.code(str(raw_text))
                    continue

                parse_note = str(asset.get("parse_note", "")).strip()
                if parse_note:
                    st.caption(parse_note)

                payload = _as_intent_payload(asset.get("payload"))
                content = asset.get("content")
                normalized_intent = normalize_intent(intent)
                render_handler = self._render_handlers.get(normalized_intent, render_unknown_asset)
                render_handler(self._context, scope, payload, content, asset if isinstance(asset, dict) else {})


__all__ = ["AgentAssetRenderContext", "AgentAssetRenderer", "AgentAsset", "AgentAssetRenderHandler"]
