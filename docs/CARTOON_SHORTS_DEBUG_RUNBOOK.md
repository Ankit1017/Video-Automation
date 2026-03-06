# Cartoon Shorts Debug Runbook

## Correlation Keys

Use the same IDs used across the app:

- `request_id`
- `run_id`
- `job_id`

For cartoon jobs, start with `job_id` from background job panel.

## Expected Events

- `cartoon.storyboard.start`
- `cartoon.storyboard.end`
- `cartoon.timeline.normalize`
- `cartoon.audio.synthesis.start`
- `cartoon.audio.synthesis.end`
- `cartoon.render.start`
- `cartoon.render.format.start`
- `cartoon.render.format.end`
- `cartoon.render.end`
- `cartoon.export.error`
- `cartoon.pack.validate.start`
- `cartoon.pack.validate.end`
- `cartoon.pack.audit.summary`
- `cartoon.timeline.v2.scene`
- `cartoon.render.quality_tier`
- `cartoon.showcase.preset.applied`
- `cartoon.qa.bundle.generated`

## Common Failures

## 1) Manual timeline rejected

Checks:

1. `timeline.scenes` exists and is a list.
2. Each scene has at least one turn.
3. Each turn has `speaker_id` and `text`.

## 2) No MP4 output generated

Checks:

1. `moviepy` and `Pillow` dependencies are installed.
2. Output mode includes at least one target.
3. Timeline has valid scenes/turns.
4. Review `cartoon.export.error` event attributes.
5. If `fidelity_preset=uhd_4k30`, verify machine memory/CPU headroom.

## 3) Rendering is slow

Checks:

1. Inspect selected render profile (`gpu_high` / `gpu_balanced` / `cpu_safe`).
2. Reduce scene count and turn density.
3. Render one format first (`shorts_9_16` or `widescreen_16_9`).

## 4) Speaker visuals wrong

Checks:

1. Validate `character_roster` IDs and names.
2. Ensure turns use matching `speaker_id`.
3. Confirm default character pack manifest is readable.

## 5) v2 render fails before frame export

Checks:

1. Confirm `timeline_schema_version` is `v2`.
2. Verify every scene has `camera_track.keyframes` and `character_tracks`.
3. Verify each character has `asset_mode=lottie_cache`, `lottie_source`, and `cache_root`.
4. Confirm cache layout exists:
   `characters/<char_id>/cache/<state>/<variant>/f####.png`.

## 6) Cache miss spikes or frozen sprite motion

Checks:

1. Inspect `cartoon.sprite.cache_miss_total`.
2. Verify `talk` variants include visemes `A..H,X`.
3. Confirm render `quality_tier` and selected fps match expected cache cadence.
4. Inspect `pack_motion_warning_count` in payload metadata; non-zero means low frame count variants.
5. Ensure pack `cache_fps` matches actual cache export cadence.

## 7) Output style does not match single-character showcase target

Checks:

1. Set `render_style=character_showcase` in payload/UI.
2. Set `background_style=chroma_green` (or keep `auto` while showcase style is selected).
3. Verify payload metadata contains both keys on export-start path.
4. Confirm character cache variants contain multiple frames; single-frame variants will look static.
5. If sprite pack is placeholder-quality, set `showcase_avatar_mode=procedural_presenter` (or keep `auto` and ensure motion warnings are detected).
6. If presenter arms look static, verify scene `character_tracks` are present and v2 planner is active (talk-pose choreography depends on active speaker timing).

## 8) Production pack validation fails in v2

Checks:

1. `lottie_source` file exists for every character and path is readable.
2. Manifest `cache_resolution` matches actual PNG frame size.
3. Required directories exist for all `idle/blink/talk` variants.
4. If `cache_resolution` is unknown, set it in `manifest.json` as `WIDTHxHEIGHT`.

## 9) QA bundle missing or incomplete

Checks:

1. Set `qa_bundle_mode=auto`.
2. Confirm export completed at least one target output.
3. Verify payload metadata contains `qa_bundle` and output artifacts include `key=qa_bundle`.
4. Inspect `qa_bundle.pack_motion_warning_count` and `qa_bundle.cache_miss_count` for motion quality diagnostics.

## 10) Flat-assets v3 runtime selected but render quality/fallback is wrong

Checks:

1. Confirm metadata has `asset_runtime_version=v3_flat_assets_direct`.
2. Confirm `asset_pack_root` points to the intended `.../cartoon_packs/flat_assets` path.
3. Verify required directories exist:
   - `Templates/Bust`, `Templates/Standing`, `Templates/Sitting`
   - `Separate Atoms/face`, `head`, `body`, `pose/standing`, `pose/sitting`
4. Verify `cairosvg` is installed (`pip show cairosvg`).
5. Inspect telemetry:
   - `cartoon.runtime.v3.selected`
   - `cartoon.flat_assets.catalog.loaded`
   - `cartoon.flat_assets.svg_rasterize.cache_hits/misses`
   - `cartoon.flat_assets.compose.total/failures`
6. If compose failures are high, renderer falls back to procedural presenter or circle fallback.
