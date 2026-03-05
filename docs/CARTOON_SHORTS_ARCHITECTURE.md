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
- `cartoon_character_asset_validator.py`: validates strict v2 cache layout and required state coverage.
  - Also audits motion quality (low frame-count variants) for operator feedback.
- `cartoon_lottie_cache_service.py`: resolves deterministic sprite frame paths from pre-rendered cache.
- `cartoon_motion_planner_service.py`: frame-by-frame camera/blocking/character state planner with easing.
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

v2 additions:

- `timeline_schema_version` (`v1 | v2`)
- `quality_tier` (`auto | light | balanced | high`)
- `render_style` (`scene | character_showcase`)
- `background_style` (`auto | scene | chroma_green`)
- `fidelity_preset` (`auto_profile | hd_1080p30 | uhd_4k30`)
- `showcase_avatar_mode` (`auto | cache_sprite | procedural_presenter`)
- `camera_track`, `character_tracks`, `subtitle_track` on scenes
- extended `CartoonCharacterSpec` fields for cache-based rendering

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
- v2 verification additionally validates motion tracks and required character asset references.
