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

