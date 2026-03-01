# Schema Contracts

Asset schemas provide minimal, enforceable contracts for normalized artifact envelopes.

## Location

Primary schema files:

- `main_app/schemas/assets/topic.v1.json`
- `main_app/schemas/assets/mindmap.v1.json`
- `main_app/schemas/assets/flashcards.v1.json`
- `main_app/schemas/assets/data_table.v1.json`
- `main_app/schemas/assets/quiz.v1.json`
- `main_app/schemas/assets/slideshow.v1.json`
- `main_app/schemas/assets/video.v1.json`
- `main_app/schemas/assets/audio_overview.v1.json`
- `main_app/schemas/assets/report.v1.json`

## Current Schema Shape

Each schema defines:

- `id`
- `intent`
- `version`
- `required_section_key`
- `required_data_type` (`string` or `object`)

## Validation Stage

Schema validation happens during `validate_schema` stage in the tool orchestrator.

Service:

- `main_app/services/agent_dashboard/schema_validation_service.py`

## Candidate Resolution Order

Schema loader checks:

1. `main_app/domains/<intent>/schema/<intent>.<version>.json`
2. `main_app/schemas/assets/<intent>.<version>.json`
3. `main_app/schemas/assets/<intent_with_underscores>.<version>.json`

## Enforcement Control

- `SCHEMA_VALIDATE_ENFORCE=true` (default): schema failures fail stage
- `SCHEMA_VALIDATE_ENFORCE=false`: failures are reported but stage status can remain pass

## Validation Output

Stored in artifact provenance:

- `artifact.provenance.schema_validation`
  - `status`
  - `schema_id`
  - `checks_run`
  - `issues`
  - `enforce`

## Error Code

- `E_SCHEMA_VALIDATION_FAILED`
