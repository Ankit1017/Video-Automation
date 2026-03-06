# Cartoon Shorts User Guide

`Cartoon Shorts Studio` lets you generate animated multi-character shorts from either:

1. Idea-to-script mode
2. Manual timeline JSON mode

## Quick Usage

1. Open `Cartoon Shorts Studio`.
2. Enter `Topic` and optional `Idea / Hook`.
3. Select:
   - `Short Type`
   - `Scenes`
   - `Characters`
   - `Output Mode`
   - `Timeline Schema Version` (`v2` recommended, `v1` legacy)
   - `Quality Tier` (`auto | light | balanced | high`)
   - `Style Preset` (`default_scene | expected_showcase`)
   - `Render Style` (`scene | character_showcase`)
   - `Background Style` (`auto | scene | chroma_green`)
   - `Fidelity Preset` (`auto_profile | hd_1080p30 | uhd_4k30`)
   - `Showcase Avatar Mode` (`auto | cache_sprite | procedural_presenter`)
   - `QA Bundle` (`auto | off`)
   - `Language`
   - `Cinematic Story Mode` (recommended)
4. Choose timeline source:
   - `Idea to Script`: auto storyboard + timeline
   - `Manual`: paste timeline JSON
5. Click `Generate Cartoon Shorts Asset`.
6. Monitor background progress and ETA.
7. Build and download:
   - Project JSON
   - Script markdown
   - MP4 outputs (`9:16`, `16:9`, or both)

## Output Modes

- `dual`: render both `shorts_9_16` and `widescreen_16_9`
- `shorts_9_16`: vertical only
- `widescreen_16_9`: horizontal only

## Timeline JSON (manual mode)

Minimum structure:

```json
{
  "scenes": [
    {
      "scene_index": 1,
      "title": "Intro",
      "turns": [
        {
          "speaker_id": "ava",
          "speaker_name": "Ava",
          "text": "Let us understand this concept quickly."
        }
      ]
    }
  ]
}
```

Extended cinematic scene fields (optional but recommended):

- `shot_type`: `wide_establishing | medium_two_shot | close_single | over_shoulder`
- `camera_move`: `static | push_in | pull_out | pan_left | pan_right`
- `transition_in`: `cut | crossfade | fade_black`
- `transition_out`: `cut | crossfade | fade_black`
- `mood`: `neutral | energetic | tense | warm | inspiring`
- `focus_character_id`: speaker id to emphasize in close shots

### Timeline v2 required fields

When `Timeline Schema Version = v2`, each scene must include:

- `camera_track.keyframes[]` with `t_ms,x,y,zoom,rotation,ease`
- `character_tracks[]` with `character_id` and keyframes:
  `t_ms,x_norm,y_norm,scale,rotation,pose,emotion,opacity,z_index,ease`
- Optional `subtitle_track` with `y_norm,max_lines,style`

If these fields are missing in manual JSON, generation fails in strict v2 mode.

## Character Pack v2 requirements

For v2 rendering, each character must provide:

- `asset_mode: lottie_cache`
- `lottie_source`
- `cache_root`
- `state_map`
- `anchor`, `default_scale`, `z_layer`

Cache folder layout:

- `characters/<char_id>/cache/<state>/<variant>/f####.png`

Required state coverage:

- States: `idle`, `blink`, `talk`
- Emotions: `neutral`, `energetic`, `tense`, `warm`, `inspiring`
- Talk visemes: `A,B,C,D,E,F,G,H,X`

Strict production checks:

- `lottie_source` path must exist on disk.
- Manifest `cache_resolution` must match PNG frame dimensions.
- Missing required variants fail fast in v2 mode.

Motion quality recommendation:

- Keep at least `8+` frames per variant (idle/blink/talk viseme variants).
- Set pack `cache_fps` in manifest to the real frame cadence used during cache export.
- The renderer now uses `cache_fps` for deterministic frame selection (independent from MP4 output fps).

Quick demo cache generation (for testing pipeline motion):

```bash
python scripts/generate_cartoon_motion_cache.py --pack-root main_app/assets/cartoon_packs/default --frames 8 --overwrite
```

## Cartoon v3 Flat-Assets Direct Runtime

You can now run cartoon rendering directly from:

`main_app/assets/cartoon_packs/flat_assets`

without converting that folder to lottie cache layout.

Activation is automatic by pack path:

- if resolved pack root folder name is `flat_assets`, runtime switches to `v3_flat_assets_direct`
- timeline schema stays `v2` (same `camera_track` + `character_tracks` contract)

Pack root resolution priority:

1. payload metadata `pack.pack_root` / `asset_pack_root`
2. env var `CARTOON_PACK_ROOT`
3. default pack path (`main_app/assets/cartoon_packs/default`)

Example (Windows PowerShell):

```powershell
$env:CARTOON_PACK_ROOT="D:\projects\projects for shown\video-automation\main_app\assets\cartoon_packs\flat_assets"
```

v3 metadata keys added to payload:

- `asset_runtime_version`
- `asset_pack_root`
- `asset_pack_kind`
- `flat_assets_catalog_summary`

Important:

- `Separate Atoms` in this pack are SVG-based.
- v3 requires `cairosvg` for runtime atom rasterization.
- install via: `pip install cairosvg`

## Expected Output Recipe

For output closest to single-presenter greenscreen references:

1. `Style Preset = expected_showcase`
2. Keep `Timeline Schema Version = v2`
3. Keep `Quality Tier = auto`
4. Keep `Render Style = character_showcase`
5. Keep `Background Style = chroma_green`
6. Keep `Showcase Avatar Mode = auto`
7. Use `Fidelity Preset = hd_1080p30` (or `uhd_4k30` for heavier renders)
8. Keep `QA Bundle = auto`

When `expected_showcase + auto_profile` is selected, export enforces a minimum target of `1080x1920 @ 30fps`.

## QA Bundle

When `QA Bundle = auto`, export metadata includes a JSON QA report with:

- selected profile/tier/preset/style values
- target resolution/fps/bitrate for each output mode
- scene duration/frame totals
- sprite cache miss count
- pack motion warning count and summary

## Tips

- Keep turns concise for better pacing.
- Use 2-4 speakers max for clean layout.
- Keep `Cinematic Story Mode` on for richer camera motion and scene transitions.
- Use `Quality Tier = auto` for hardware-aware defaults.
- For single-character greenscreen output, use:
  - `Render Style = character_showcase`
  - `Background Style = chroma_green` (or `auto` with showcase)
  - `Showcase Avatar Mode = auto` (or `procedural_presenter` while sprite pack is not production-ready)
  - v2 planner now auto-generates presenter gesture poses during active speech (`open`, `point`, `emphasis`, etc.).
- For high-quality exports, use:
  - `Fidelity Preset = hd_1080p30` (fast) or `uhd_4k30` (best quality, heavier render)
- If `Style Preset = expected_showcase` but output still looks static:
  - verify pack has `8+` frames per variant
  - verify `lottie_source` exists for each character
  - inspect QA bundle `pack_motion_warning_count` and `cache_miss_count`
- If manual JSON is rejected, validate `scenes[]` and `turns[]` first.
