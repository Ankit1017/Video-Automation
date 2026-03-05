from __future__ import annotations

from main_app.ui.agent_dashboard.handlers.interactive import render_cartoon_asset
from main_app.ui.agent_dashboard.renderer_plugins.types import AgentAssetRendererPlugin


PLUGIN = AgentAssetRendererPlugin(intent="cartoon_shorts", handler=render_cartoon_asset)

