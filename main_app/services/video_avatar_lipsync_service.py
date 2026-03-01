from __future__ import annotations

import json
import os
import subprocess
import tempfile
from typing import cast

from main_app.contracts import DialogueAudioSegment


class VideoAvatarLipsyncService:
    def __init__(self, *, rhubarb_cli_path: str | None = None) -> None:
        self._rhubarb_cli_path = rhubarb_cli_path or os.getenv("VIDEO_RHUBARB_CLI_PATH", "").strip()

    def build_mouth_cues(
        self,
        *,
        segment: DialogueAudioSegment,
        segment_audio_wav: bytes | None = None,
    ) -> tuple[list[dict[str, object]], str | None]:
        if segment_audio_wav and self._rhubarb_cli_path:
            cues = self._run_rhubarb(segment_audio_wav=segment_audio_wav)
            if cues:
                return cues, None
        return self._heuristic_cues(segment=segment), "rhubarb_unavailable_or_failed"

    def _run_rhubarb(self, *, segment_audio_wav: bytes) -> list[dict[str, object]]:
        try:
            with tempfile.TemporaryDirectory(prefix="video_avatar_lipsync_") as temp_dir:
                audio_path = os.path.join(temp_dir, "segment.wav")
                json_path = os.path.join(temp_dir, "segment.json")
                with open(audio_path, "wb") as fh:  # noqa: PTH123
                    fh.write(segment_audio_wav)
                process = subprocess.run(  # noqa: S603
                    [self._rhubarb_cli_path, "-f", "json", "-o", json_path, audio_path],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=6.0,
                )
                if process.returncode != 0:
                    return []
                with open(json_path, "r", encoding="utf-8") as fh:  # noqa: PTH123
                    payload = json.load(fh)
        except (OSError, ValueError, TypeError, subprocess.SubprocessError, json.JSONDecodeError):
            return []

        mouth_cues = payload.get("mouthCues", []) if isinstance(payload, dict) else []
        if not isinstance(mouth_cues, list):
            return []
        normalized: list[dict[str, object]] = []
        for cue in mouth_cues:
            if not isinstance(cue, dict):
                continue
            normalized.append(
                cast(
                    dict[str, object],
                    {
                        "start_ms": int(round(float(_safe_float(cue.get("start"), default=0.0)) * 1000.0)),
                        "end_ms": int(round(float(_safe_float(cue.get("end"), default=0.0)) * 1000.0)),
                        "mouth": " ".join(str(cue.get("value", "")).split()).strip().upper() or "X",
                    },
                )
            )
        return normalized

    def _heuristic_cues(self, *, segment: DialogueAudioSegment) -> list[dict[str, object]]:
        duration_ms = max(200, _safe_int(segment.get("duration_ms", 1000), default=1000))
        text = " ".join(str(segment.get("text", "")).split()).strip()
        words = [word for word in text.split(" ") if word]
        if not words:
            return []

        step_ms = max(120, duration_ms // max(1, len(words)))
        cues: list[dict[str, object]] = []
        mouth_cycle = ["A", "B", "C", "D", "E", "F", "G", "H", "X"]
        current = 0
        for idx, _ in enumerate(words):
            start_ms = current
            end_ms = min(duration_ms, start_ms + step_ms)
            cues.append(
                {
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                    "mouth": mouth_cycle[idx % len(mouth_cycle)],
                }
            )
            current = end_ms
            if current >= duration_ms:
                break
        if not cues:
            cues.append({"start_ms": 0, "end_ms": duration_ms, "mouth": "X"})
        return cues


def _safe_int(value: object, *, default: int) -> int:
    try:
        if isinstance(value, bool):
            return default
        if isinstance(value, (int, float, str)):
            return int(value)
        return int(str(value))
    except (TypeError, ValueError):
        return default


def _safe_float(value: object, *, default: float) -> float:
    try:
        if isinstance(value, bool):
            return default
        if isinstance(value, (int, float, str)):
            return float(value)
        return float(str(value))
    except (TypeError, ValueError):
        return default

