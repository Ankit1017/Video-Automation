from __future__ import annotations

import os
from typing import cast

from main_app.contracts import CartoonRenderProfile


class CartoonRenderProfileService:
    def select_profile(self) -> CartoonRenderProfile:
        gpu_available, gpu_memory_mb = self._detect_gpu()
        if gpu_available and gpu_memory_mb >= 10_000:
            return cast(
                CartoonRenderProfile,
                {
                    "profile_key": "gpu_high",
                    "shorts_width": 1080,
                    "shorts_height": 1920,
                    "widescreen_width": 1920,
                    "widescreen_height": 1080,
                    "fps": 30,
                    "gpu_available": True,
                    "gpu_memory_mb": gpu_memory_mb,
                    "animation_level": "high",
                },
            )
        if gpu_available:
            return cast(
                CartoonRenderProfile,
                {
                    "profile_key": "gpu_balanced",
                    "shorts_width": 720,
                    "shorts_height": 1280,
                    "widescreen_width": 1280,
                    "widescreen_height": 720,
                    "fps": 24,
                    "gpu_available": True,
                    "gpu_memory_mb": gpu_memory_mb,
                    "animation_level": "balanced",
                },
            )
        return cast(
            CartoonRenderProfile,
            {
                "profile_key": "cpu_safe",
                "shorts_width": 540,
                "shorts_height": 960,
                "widescreen_width": 960,
                "widescreen_height": 540,
                "fps": 20,
                "gpu_available": False,
                "gpu_memory_mb": 0,
                "animation_level": "light",
            },
        )

    def _detect_gpu(self) -> tuple[bool, int]:
        try:
            import torch  # type: ignore
        except ImportError:
            return False, 0
        try:
            if not bool(getattr(torch.cuda, "is_available", lambda: False)()):
                return False, 0
            memory_bytes = int(torch.cuda.get_device_properties(0).total_memory)  # type: ignore[attr-defined]
            return True, max(0, memory_bytes // (1024 * 1024))
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
            return True, _int_env("CARTOON_GPU_MEMORY_MB_HINT", default=4096)


def _int_env(name: str, *, default: int) -> int:
    raw = " ".join(str(os.getenv(name, "")).split()).strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default
