from __future__ import annotations

from typing import Protocol

from main_app.contracts import CartoonPayload, CartoonRenderProfile


class CartoonExporter(Protocol):
    def build_cartoon_mp4s(
        self,
        *,
        topic: str,
        cartoon_payload: CartoonPayload,
        output_mode: str | None = None,
        render_profile: CartoonRenderProfile | None = None,
    ) -> tuple[dict[str, bytes], str | None]: ...
