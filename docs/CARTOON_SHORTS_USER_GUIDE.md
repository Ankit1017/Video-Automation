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
   - `Render Style` (`scene | character_showcase`)
   - `Background Style` (`auto | scene | chroma_green`)
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

## Tips

- Keep turns concise for better pacing.
- Use 2-4 speakers max for clean layout.
- Keep `Cinematic Story Mode` on for richer camera motion and scene transitions.
- Use `Quality Tier = auto` for hardware-aware defaults.
- For single-character greenscreen output, use:
  - `Render Style = character_showcase`
  - `Background Style = chroma_green` (or `auto` with showcase)
- If manual JSON is rejected, validate `scenes[]` and `turns[]` first.
