# Cartoon Shorts Architecture

## Overview

The `cartoon_shorts` asset is a separate media pipeline integrated with:

- Intent routing
- Agent Dashboard orchestration
- Asset history rendering
- Background jobs
- Telemetry/observability

## Core Services

- `cartoon_shorts_asset_service.py`: orchestrates storyboard/timeline payload creation.
- `cartoon_storyboard_service.py`: idea-to-scene LLM generation with fallback path.
- `cartoon_timeline_service.py`: validation/normalization of scene and turn timing.
- `cartoon_character_pack_service.py`: loads local character pack metadata.
- `cartoon_audio_service.py`: builds narration track from timeline turns.
- `cartoon_export_service.py`: renders MP4 outputs for selected aspect ratio(s).
- `cartoon_scene_renderer.py`: draws per-scene visual frames.
- `cartoon_render_profile_service.py`: hardware-adaptive render profile.
- `cartoon_subtitle_service.py`: speaker-aware subtitle formatting/colors.

## Contracts

Defined in `main_app/contracts.py`:

- `CartoonPayload`
- `CartoonTimeline`
- `CartoonScene`
- `CartoonDialogueTurn`
- `CartoonCharacterSpec`
- `CartoonRenderProfile`
- `CartoonOutputArtifact`

## Orchestration Integration

`cartoon_shorts` is registered in:

- intent requirement spec
- tool registry
- workflow registry
- executor plugin discovery
- renderer plugin discovery (agent dashboard + asset history)

Schema:

- `main_app/schemas/assets/cartoon_shorts.v1.json`

Verification:

- media verification path validates timeline + roster integrity.

