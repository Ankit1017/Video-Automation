# Payload Logging Policy

This project supports full payload observability capture by default.

## Scope

Captured payloads can include:

- LLM request/response bodies
- Web sourcing run diagnostics and fetched summaries
- Grounding diagnostics
- Agent run/stage diagnostic envelopes
- Export metadata

## Controls

- `OBSERVABILITY_PAYLOAD_CAPTURE_ENABLED` (default: `true`)
- `OBSERVABILITY_PAYLOAD_RETENTION_DAYS` (default: `14`)
- `OBSERVABILITY_PAYLOAD_VAULT_DIR` (default: `.cache/observability_payloads`)
- `OBSERVABILITY_PAYLOAD_ENCRYPTION_ENABLED` (default: `true`)
- `OBSERVABILITY_PAYLOAD_ENCRYPTION_KEY` (optional explicit key)
- `OBSERVABILITY_PAYLOAD_KEY_FILE` (optional persisted key file path)

## Retention

- Payload files older than retention are purged by vault operations.
- Adjust retention based on compliance and storage constraints.

## Encryption at Rest

- Enabled by default when `cryptography` is installed.
- If encryption is enabled but key is missing, the app generates/stores a local key file by default.

## Operational Guidance

- Treat payload vault as sensitive data.
- Restrict filesystem and backup access for payload directory.
- Avoid sharing payload dumps outside trusted channels.
