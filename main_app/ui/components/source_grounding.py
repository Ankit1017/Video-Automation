from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

import streamlit as st

from main_app.models import WebSourcingSettings
from main_app.services.global_grounding_service import GlobalGroundingService
from main_app.services.source_grounding_service import SourceDocument, SourceGroundingService


@dataclass(frozen=True)
class SourceGroundingSelection:
    enabled: bool
    require_citations: bool
    sources: list[SourceDocument]
    grounding_context: str
    source_manifest: list[dict[str, Any]]
    warnings: list[str]
    diagnostics: dict[str, Any] = field(default_factory=dict)


def render_source_grounding_controls(
    *,
    key_prefix: str,
    source_grounding_service: SourceGroundingService,
    global_grounding_service: GlobalGroundingService | None = None,
    web_settings: WebSourcingSettings | None = None,
    topic: str = "",
    constraints: str = "",
    heading: str = "Source-Grounded Generation",
) -> SourceGroundingSelection:
    with st.container(border=True):
        st.markdown(f"#### {heading}")
        enabled = st.checkbox(
            "Enable source-grounded mode",
            key=f"{key_prefix}_grounded_enabled",
            help="When enabled, uploaded files are used as grounding context for generation.",
        )
        if not enabled:
            return SourceGroundingSelection(
                enabled=False,
                require_citations=False,
                sources=[],
                grounding_context="",
                source_manifest=[],
                warnings=[],
                diagnostics={},
            )

        require_citations = st.checkbox(
            "Require citation markers in output (e.g. [S1], [S2])",
            value=True,
            key=f"{key_prefix}_grounded_citations",
        )
        max_sources = st.slider(
            "Max sources to use",
            min_value=1,
            max_value=12,
            value=6,
            step=1,
            key=f"{key_prefix}_grounded_max_sources",
        )
        uploaded_files = st.file_uploader(
            "Upload source files",
            type=source_grounding_service.supported_upload_types,
            accept_multiple_files=True,
            key=f"{key_prefix}_grounded_files",
        )

        effective_web_settings = web_settings or WebSourcingSettings()
        disable_web_for_run = False
        query_override = ""
        if effective_web_settings.enabled:
            with st.expander("Web Sourcing Override", expanded=False):
                disable_web_for_run = st.checkbox(
                    "Disable web sourcing for this run",
                    value=False,
                    key=f"{key_prefix}_grounded_disable_web_for_run",
                )
                query_override = st.text_input(
                    "Custom web query (optional)",
                    value="",
                    key=f"{key_prefix}_grounded_web_query_override",
                    help="When set, this overrides topic/constraints for web retrieval only.",
                )
        effective_web_settings = replace(
            effective_web_settings,
            enabled=bool(effective_web_settings.enabled and not disable_web_for_run),
        )

        query_topic = " ".join(str(query_override or topic).split()).strip()
        query_constraints = " ".join(str(constraints).split()).strip() if not query_override.strip() else ""
        diagnostics: dict[str, Any] = {}
        if global_grounding_service is not None:
            sources, warnings, diagnostics = global_grounding_service.build_sources(
                uploaded_files or [],
                topic=query_topic,
                constraints=query_constraints,
                web_settings=effective_web_settings,
                max_sources=max_sources,
            )
        else:
            sources, warnings = source_grounding_service.extract_sources(
                uploaded_files or [],
                max_sources=max_sources,
            )
        grounding_context = source_grounding_service.build_grounding_context(sources)
        source_manifest = source_grounding_service.build_source_manifest(sources)
        effective_enabled, effective_require_citations, mode_warnings = resolve_grounding_mode(
            has_sources=bool(sources),
            strict_mode=bool(effective_web_settings.strict_mode),
            require_citations=bool(require_citations),
        )
        warnings.extend(mode_warnings)

        if sources:
            st.caption(
                f"Loaded {len(sources)} source(s), total context size: {len(grounding_context)} characters."
            )
            with st.expander("Source Summary", expanded=False):
                for source in sources:
                    truncation_note = " (truncated)" if source.truncated else ""
                    source_kind = f", {source.source_type}" if source.source_type else ""
                    st.markdown(
                        f"- `[{source.source_id}]` {source.name} ({source.char_count} chars{source_kind}){truncation_note}"
                    )
        else:
            st.caption("No valid sources loaded yet.")

        for warning_text in warnings:
            st.caption(f"Note: {warning_text}")

        return SourceGroundingSelection(
            enabled=effective_enabled,
            require_citations=effective_require_citations,
            sources=sources,
            grounding_context=grounding_context,
            source_manifest=source_manifest,
            warnings=warnings,
            diagnostics=diagnostics,
        )


def resolve_grounding_mode(
    *,
    has_sources: bool,
    strict_mode: bool,
    require_citations: bool,
) -> tuple[bool, bool, list[str]]:
    warnings: list[str] = []
    if has_sources:
        return True, bool(require_citations), warnings
    if strict_mode:
        warnings.append("Strict mode is enabled and no valid sources were available for this run.")
        return True, bool(require_citations), warnings
    warnings.append("No valid sources found. Continuing in ungrounded mode for this run.")
    return False, False, warnings
