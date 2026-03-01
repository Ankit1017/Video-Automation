from __future__ import annotations

import os
import shutil
import subprocess
from typing import cast

from main_app.contracts import VideoRenderProfile


class VideoRenderProfileService:
    def select_profile(self) -> VideoRenderProfile:
        adaptive = _env_flag("VIDEO_ADAPTIVE_PROFILE", default=True)
        if not adaptive:
            return _profile_balanced(gpu_available=False, gpu_memory_mb=0)

        gpu_available, gpu_memory_mb = self._detect_gpu()
        if gpu_available and gpu_memory_mb >= 8_000:
            return _profile_high(gpu_available=gpu_available, gpu_memory_mb=gpu_memory_mb)
        if gpu_available:
            return _profile_balanced(gpu_available=gpu_available, gpu_memory_mb=gpu_memory_mb)
        return _profile_cpu_safe(gpu_available=gpu_available, gpu_memory_mb=gpu_memory_mb)

    def _detect_gpu(self) -> tuple[bool, int]:
        nvidia_smi = shutil.which("nvidia-smi")
        if not nvidia_smi:
            return False, 0
        try:
            completed = subprocess.run(
                [nvidia_smi, "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                check=False,
                timeout=2.5,
            )
        except (OSError, subprocess.SubprocessError, ValueError):
            return True, 0
        if completed.returncode != 0:
            return True, 0
        memory_values: list[int] = []
        for line in completed.stdout.splitlines():
            value = " ".join(line.split()).strip()
            if not value:
                continue
            try:
                memory_values.append(int(value))
            except (TypeError, ValueError):
                continue
        if not memory_values:
            return True, 0
        return True, max(memory_values)


def _profile_high(*, gpu_available: bool, gpu_memory_mb: int) -> VideoRenderProfile:
    return cast(
        VideoRenderProfile,
        {
            "profile_key": "gpu_high",
            "width": 1920,
            "height": 1080,
            "fps": 30,
            "avatar_scale": 1.0,
            "animation_level": "high",
            "gpu_available": gpu_available,
            "gpu_memory_mb": gpu_memory_mb,
        },
    )


def _profile_balanced(*, gpu_available: bool, gpu_memory_mb: int) -> VideoRenderProfile:
    return cast(
        VideoRenderProfile,
        {
            "profile_key": "gpu_balanced",
            "width": 1280,
            "height": 720,
            "fps": 24,
            "avatar_scale": 0.92,
            "animation_level": "medium",
            "gpu_available": gpu_available,
            "gpu_memory_mb": gpu_memory_mb,
        },
    )


def _profile_cpu_safe(*, gpu_available: bool, gpu_memory_mb: int) -> VideoRenderProfile:
    return cast(
        VideoRenderProfile,
        {
            "profile_key": "cpu_safe",
            "width": 960,
            "height": 540,
            "fps": 20,
            "avatar_scale": 0.86,
            "animation_level": "low",
            "gpu_available": gpu_available,
            "gpu_memory_mb": gpu_memory_mb,
        },
    )


def _env_flag(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = " ".join(raw.split()).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default

