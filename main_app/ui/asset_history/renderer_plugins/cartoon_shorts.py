from __future__ import annotations

from main_app.ui.asset_history.renderer_plugins.types import AssetHistoryRendererPlugin
from main_app.ui.asset_history.renderers.interactive import render_cartoon_record


PLUGIN = AssetHistoryRendererPlugin(intent="cartoon_shorts", renderer=render_cartoon_record)

