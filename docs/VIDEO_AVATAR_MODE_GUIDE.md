# Video Avatar Mode Guide

This guide covers the new default video render path: `avatar_conversation`.

## 1. What It Does

- Keeps full slide content visible.
- Overlays conversational avatar bubbles.
- Highlights active speaker and subtitle text.
- Uses timeline turns from `conversation_timeline`.
- Auto-falls back to `classic_slides` if avatar path fails (when enabled).

## 2. Render Modes

- `avatar_conversation` (default): avatar overlays + subtitle diagnostics.
- `classic_slides`: legacy renderer without avatars.

## 3. Hardware-Adaptive Profiles

Selected automatically by `VideoRenderProfileService`:

- `gpu_high`: 1920x1080 @ 30fps
- `gpu_balanced`: 1280x720 @ 24fps
- `cpu_safe`: 960x540 @ 20fps

Profile info is written into `video_payload.render_profile` and metadata.

## 4. Required Payload Fields

- `speaker_roster` (at least 2 speakers)
- `conversation_timeline.turns` (non-empty)
- Monotonic timing (`start_ms`, `end_ms`)
- Optional `conversation_timeline.audio_segments`

## 5. Environment Variables

- `VIDEO_RENDER_MODE_DEFAULT=avatar_conversation`
- `VIDEO_AVATAR_ALLOW_FALLBACK=true`
- `VIDEO_ADAPTIVE_PROFILE=true`
- `VIDEO_RHUBARB_CLI_PATH=` (optional local phoneme tool path)

## 6. Troubleshooting

## Avatar path fails and video still renders
- Expected when fallback is enabled.
- Check metadata: `avatar_fallback_used=true`.
- Check event: `video.avatar_fallback`.

## No lip-sync cues
- Ensure local Rhubarb CLI path is valid.
- Without Rhubarb, system uses heuristic mouth cues.

## OTel timeline visibility
- Watch these events:
  - `video.conversation_timeline.start/end`
  - `video.dialogue_audio.start/end`
  - `video.avatar_lipsync.segment`
  - `video.avatar_overlay.end`
  - `video.avatar_fallback`

## 7. Validation Commands

```powershell
python -m pytest -q tests/test_video_asset_service.py tests/test_video_export_service.py tests/test_video_tab.py tests/test_video_avatar_mode.py
```
