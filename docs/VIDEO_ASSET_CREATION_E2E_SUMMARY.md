# Video Asset Creation End-to-End Summary

This document explains the current video generation pipeline from UI request to final MP4/audio outputs.

## Scope

Two video paths are covered:

1. Direct **Video Builder** tab flow
2. Agent Dashboard tool/workflow flow for `video` intent

## Key Entry Points

- UI tab: `main_app/ui/tabs/video_tab.py`
- Video generation: `main_app/services/video_asset_service.py`
- Video rendering/export: `main_app/services/video_export_service.py`
- Agent execution: `main_app/services/agent_dashboard/*`

## A) Direct UI Path (Video Builder Tab)

### 1) User Input

Collected in `render_video_tab(...)`:

- topic + optional constraints
- subtopic count and slides per subtopic
- animation style
- implicit defaults for code mode, template, speaker count, representation mode

### 2) Background Job Submission

Tab submits a background worker via `BackgroundJobManager`:

1. generate slideshow + narration scripts
2. synthesize combined narration audio
3. render MP4 (if audio exists)

### 3) Video Payload Generation (`VideoAssetService.generate`)

Pipeline:

1. Calls `SlideShowService.generate(...)`.
2. For each slide, calls LLM for slide dialogue JSON.
3. Parses each dialogue with `AudioOverviewParser`.
4. Normalizes speaker turns, trims invalid text, estimates duration.
5. Assembles final `video_payload`:
   - slides
   - speaker roster
   - slide scripts
   - metadata (template/style/mode flags)

If any slide script fails parsing, generation aborts with structured parse error.

### 4) Audio Synthesis (`VideoAssetService.synthesize_audio`)

Builds dialogue payload and delegates to `AudioOverviewService.synthesize_mp3(...)`.

Outputs:

- `audio_bytes` on success
- error string on failure

### 5) MP4 Rendering (`VideoExportService.build_video_mp4`)

Flow:

1. Validates slides + audio input
2. Creates temporary render workspace
3. Selects adaptive render profile (`gpu_high`, `gpu_balanced`, `cpu_safe`)
4. Builds timeline map from `conversation_timeline` and segment timing view
5. Renders either:
   - `avatar_conversation` (default): floating speaker avatars + subtitles + speaking focus
   - `classic_slides` (fallback/compatibility path)
6. Applies motion profile (`none`, `smooth`, `youtube_dynamic`)
7. Stitches clips + narration audio with MoviePy
8. Returns MP4 bytes

### 6) Avatar Failure Strategy

- If avatar pipeline fails and fallback is enabled:
  - Emits `video.avatar_fallback` event
  - Increments `video_avatar_fallback_total`
  - Automatically retries render in `classic_slides` mode
- Final payload metadata records:
  - `render_mode_requested`
  - `render_mode_used`
  - `avatar_fallback_used`
  - selected render profile details

## B) Agent Dashboard Path

When `video` runs through the generic asset flow:

1. Tool resolved from `AgentToolRegistry`
2. Workflow DAG order resolved by `AgentWorkflowRegistry`
3. Stage orchestrator executes `video` through standard stages:
   - validate registration
   - validate payload requirements
   - resolve dependencies
   - execute tool
   - normalize artifact
   - validate schema
   - verify result
   - policy gate
   - finalize

Default workflow dependency for media pipeline:

- `video` depends on `slideshow` in `media_production_assets`

## Artifact Contract

Primary video section key:

- `artifact.video.payload` (object)

Schema:

- `main_app/schemas/assets/video.v1.json`

Verification checks include:

- payload presence
- slide/script presence
- `speaker_roster` minimum shape
- `conversation_timeline` presence + monotonic timing checks
- audio artifact consistency

## Storage and History

- Generation history is persisted via `AssetHistoryService`.
- Background job status is tracked in session state.
- Agent path additionally records stage diagnostics/run diagnostics.

## Common Failure Modes

1. Missing Groq config in sidebar
2. Slideshow generation failure cascades into video failure
3. Slide script JSON parse failure
4. Audio synthesis failure (TTS/provider/runtime)
5. MP4 render dependency missing (`moviepy`/`Pillow`/FFmpeg)

## Minimal Validation Set

```powershell
python -m pytest -q tests/test_video_asset_service.py tests/test_video_export_service.py tests/test_video_tab.py
```

For workflow-level checks:

```powershell
python scripts/simulate_workflow.py --workflow media_production_assets --dry
```
