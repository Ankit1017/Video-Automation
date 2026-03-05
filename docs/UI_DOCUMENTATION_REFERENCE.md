# UI Documentation Reference

This guide explains how to use the product end to end from the UI.

## 1. Quick Start

1. Open the app and set model settings from the sidebar (`model`, `temperature`, `max tokens`).
2. Optionally enable web sourcing and configure provider/reliability settings.
3. Choose the tab based on your outcome.
4. Enter a focused topic and constraints.
5. Generate, review, and iterate.
6. Export artifacts (where supported) and track outcomes in Observability/Asset History.

## 2. Tab-by-Tab Usage

## Detailed Description
- Use for long-form explanation generation.
- Best for concept understanding and narrative depth.

## Mind Map Builder
- Use for hierarchical concept structure.
- Use node explain actions for deeper branch-level detail.

## Flashcards
- Use for active recall.
- Generate cards, flip, then use explanation actions for weak cards.

## Create Report
- Use for formal document output.
- Select output format first, then generate and export.

## Data Table
- Use for structured comparisons.
- Add clear dimensions in prompt to improve table quality.

## Quiz
- Use for self-assessment.
- Use hints/feedback/explanations to improve learning loop.

## Slide Show
- Use for presentation generation.
- Validate content and run export jobs.

## Video Builder
- Use for script + rendered video output.
- Default mode is `avatar_conversation` (floating conversational avatars over full slide content).
- Use advanced controls to switch `render_mode`, enable subtitles, choose style pack, and toggle auto-fallback.
- Check `Conversation Timeline Diagnostics` before final MP4 export.

## Cartoon Shorts Studio
- Use for animated multi-character shorts.
- Choose `Idea to Script` mode for automatic scene creation or `Manual Timeline JSON` for explicit control.
- Supports `dual` output rendering (`9:16` and `16:9`) and downloadable project/script artifacts.
- Track stage progress in the background job panel (`Script Generation`, `Voice Synthesis`, render stages).

## Audio Overview
- Use for narrated audio summary.
- Select narration settings (including Hinglish option when available).

## Web Sourcing Check
- Use for query/provider diagnostics before grounded generation.
- Inspect `search_count`, `fetched_count`, `accepted_count`, and warnings.

## Cache Center
- Inspect cache hit/miss behavior and entries.
- Useful when debugging repeated generation behavior.

## Documentation Center
- Use `UI Documentation` mode for usage help.
- Use `Debug Documentation` mode for backend flow and triage.

## Observability
- Inspect metrics, telemetry events, and payload references.
- Filter by `request_id` and `run_id` first.

## Additional Settings
- Persist defaults for grouped settings.
- Use group-level save/reset controls.

## Chat Bot Intent
- Convert free-form prompts into intents and planning context.

## Agent Dashboard
- Run tool/workflow orchestration with plan-stage execution.

## Asset History
- Revisit previous outputs and re-export/reuse where supported.

## 3. Recommended User Flows

## Learning flow
- Detailed Description -> Mind Map Builder -> Flashcards -> Quiz

## Delivery flow
- Create Report -> Slide Show -> Video Builder / Cartoon Shorts Studio / Audio Overview

## Reliability flow
- Web Sourcing Check -> Generation tab -> Observability -> Asset History

## 4. Common UI Mistakes

- Using broad topics without constraints.
- Ignoring warnings from web sourcing diagnostics.
- Running exports without validating generated payload quality.
- Debugging without correlation IDs (`request_id`, `run_id`, `job_id`).

## 5. Where to Go Next

- Debug and operational flow: `docs/DEBUG_DOCUMENTATION_REFERENCE.md`
- Observability architecture: `docs/OBSERVABILITY_ARCHITECTURE.md`
- Troubleshooting by IDs: `docs/OBSERVABILITY_DEBUG_COOKBOOK.md`
