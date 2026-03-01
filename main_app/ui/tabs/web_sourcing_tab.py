from __future__ import annotations

from dataclasses import replace

import streamlit as st

from main_app.models import WebSourcingSettings
from main_app.services.global_grounding_service import GlobalGroundingService


def render_web_sourcing_tab(
    *,
    global_grounding_service: GlobalGroundingService,
    web_sourcing_settings: WebSourcingSettings,
) -> None:
    st.subheader("Global Web Sourcing Check")
    st.caption("This tab does not call the LLM. It only runs search + fetch and shows sourced data volume.")

    topic_text = st.text_area(
        "Input Text / Topic",
        placeholder="e.g. Transformers in AI and how they improved NLP systems",
        height=120,
        key="web_check_topic_text",
    )
    constraints = st.text_area(
        "Optional Query Constraints",
        placeholder="e.g. prefer practical guides and architecture-level explanations",
        height=90,
        key="web_check_constraints",
    )

    with st.container(border=True):
        st.markdown("#### Run Settings")
        provider = st.selectbox(
            "Provider",
            options=["duckduckgo", "serper"],
            index=0 if web_sourcing_settings.provider_key != "serper" else 1,
            key="web_check_provider",
        )
        allow_when_global_off = st.checkbox(
            "Allow run when global toggle is OFF",
            value=not web_sourcing_settings.enabled,
            key="web_check_allow_when_global_off",
        )
        force_refresh = st.checkbox(
            "Force refresh for this run",
            value=True,
            key="web_check_force_refresh",
        )
        strict_mode = st.checkbox(
            "Strict mode for this run",
            value=bool(web_sourcing_settings.strict_mode),
            key="web_check_strict_mode",
        )
        max_sources = st.slider(
            "Max merged sources to return",
            min_value=1,
            max_value=20,
            value=min(12, max(1, int(web_sourcing_settings.max_fetch_pages))),
            step=1,
            key="web_check_max_sources",
        )

    run_check = st.button("Run Web Sourcing Check", type="primary", key="web_check_run")
    if not run_check:
        return

    if not topic_text or not topic_text.strip():
        st.error("Please enter text in Input Text / Topic.")
        st.stop()

    effective_enabled = bool(web_sourcing_settings.enabled or allow_when_global_off)
    effective_settings = replace(
        web_sourcing_settings,
        enabled=effective_enabled,
        provider_key=provider,
        force_refresh=bool(force_refresh),
        strict_mode=bool(strict_mode),
    )
    if not effective_settings.enabled:
        st.error("Web sourcing is disabled (global OFF and local override disabled).")
        st.stop()

    with st.spinner("Running web sourcing..."):
        sources, warnings, diagnostics = global_grounding_service.build_sources(
            [],
            topic=topic_text.strip(),
            constraints=constraints.strip(),
            web_settings=effective_settings,
            max_sources=max_sources,
        )

    web_sources = [source for source in sources if source.source_type == "web"]
    sourced_chars = sum(source.char_count for source in web_sources)
    max_chars = max(1, int(effective_settings.max_total_chars))
    fill_pct = (100.0 * sourced_chars) / max_chars

    metric_cols = st.columns(4)
    metric_cols[0].metric("Web Sources", str(len(web_sources)))
    metric_cols[1].metric("Sourced Chars", str(sourced_chars))
    metric_cols[2].metric("Search Results", str(int(diagnostics.get("web_search_count", 0) or 0)))
    metric_cols[3].metric("Char Budget Used", f"{fill_pct:.1f}%")

    quality_stats = diagnostics.get("web_quality_stats", {}) if isinstance(diagnostics.get("web_quality_stats"), dict) else {}
    quality_avg = float(quality_stats.get("avg", 0.0) or 0.0)
    quality_min = float(quality_stats.get("min", 0.0) or 0.0)
    quality_max = float(quality_stats.get("max", 0.0) or 0.0)
    above_threshold_count = int(quality_stats.get("above_threshold_count", 0) or 0)
    fallback_quality_mode_used = bool(diagnostics.get("web_fallback_quality_mode_used", False))

    quality_cols = st.columns(3)
    quality_cols[0].metric("Quality Avg", f"{quality_avg:.2f}")
    quality_cols[1].metric("Quality Range", f"{quality_min:.2f} - {quality_max:.2f}")
    quality_cols[2].metric("Above Threshold", str(above_threshold_count))

    if fallback_quality_mode_used:
        st.warning("Quality threshold fallback was used for this run (best available pages were returned).")

    run_diagnostics = diagnostics.get("web_run_diagnostics", {})
    if not isinstance(run_diagnostics, dict):
        run_diagnostics = {}
    failover_used = bool(run_diagnostics.get("failover_used", False))
    failover_reason = " ".join(str(run_diagnostics.get("failover_reason", "")).split()).strip()
    retry_events = int(run_diagnostics.get("retry_events", 0) or 0)
    rate_limited_urls = int(run_diagnostics.get("rate_limited_urls", 0) or 0)
    content_cache_hits = int(run_diagnostics.get("content_cache_hit_count", 0) or 0)
    content_cache_misses = int(run_diagnostics.get("content_cache_miss_count", 0) or 0)
    provider_attempts = run_diagnostics.get("provider_attempts", [])
    provider_circuit_state = run_diagnostics.get("provider_circuit_state", {})

    reliability_cols = st.columns(5)
    reliability_cols[0].metric("Failover Used", "Yes" if failover_used else "No")
    reliability_cols[1].metric("Retry Events", str(retry_events))
    reliability_cols[2].metric("Rate-Limited URLs", str(rate_limited_urls))
    reliability_cols[3].metric("Content Cache Hits", str(content_cache_hits))
    reliability_cols[4].metric("Provider Attempts", str(len(provider_attempts) if isinstance(provider_attempts, list) else 0))
    if content_cache_hits or content_cache_misses:
        st.caption(f"Content cache: hits={content_cache_hits}, misses={content_cache_misses}")
    if failover_used and failover_reason:
        st.caption(f"Failover reason: `{failover_reason}`")

    st.caption(
        " | ".join(
            [
                f"Provider: {diagnostics.get('web_provider', '') or provider}",
                f"Cache hit: {bool(diagnostics.get('web_cache_hit', False))}",
                f"Attempted fetch: {int(diagnostics.get('web_attempted_count', 0) or 0)}",
                f"Accepted pages: {int(diagnostics.get('web_accepted_count', 0) or 0)}",
            ]
        )
    )

    if warnings:
        with st.expander("Warnings", expanded=True):
            for warning in warnings:
                st.markdown(f"- {warning}")
    else:
        st.success("No warnings reported.")

    if web_sources:
        quality_reason_map: dict[str, list[str]] = {}
        raw_page_summaries = diagnostics.get("web_page_summaries", [])
        if isinstance(raw_page_summaries, list):
            for item in raw_page_summaries:
                if not isinstance(item, dict):
                    continue
                uri = " ".join(str(item.get("uri", "")).split()).strip()
                if not uri:
                    continue
                quality_reason_map[uri] = [
                    str(reason)
                    for reason in item.get("quality_reasons", [])
                    if str(reason).strip()
                ]

        rows = [
            {
                "source_id": source.source_id,
                "name": source.name,
                "char_count": source.char_count,
                "truncated": source.truncated,
                "quality_score": f"{float(source.quality_score):.2f}",
                "quality_reasons": "; ".join(
                    quality_reason_map.get(source.uri, [])
                ),
                "uri": source.uri,
                "retrieved_at": source.retrieved_at,
            }
            for source in web_sources
        ]
        st.markdown("#### Retrieved Sources")
        st.dataframe(rows, width="stretch", hide_index=True)

        preview_text = "\n\n---\n\n".join(
            f"[{source.source_id}] {source.name}\n{source.text}"
            for source in web_sources[:5]
        )
        st.markdown("#### Context Preview")
        st.text_area(
            "Preview (first 8000 chars)",
            value=preview_text[:8000],
            height=260,
            key="web_check_preview",
        )
    else:
        st.warning("No web source text was accepted for this input.")

    if isinstance(provider_attempts, list) and provider_attempts:
        st.markdown("#### Provider Attempt Timeline")
        st.dataframe(provider_attempts, width="stretch", hide_index=True)

    if isinstance(provider_circuit_state, dict) and provider_circuit_state:
        st.markdown("#### Provider Circuit State")
        st.json(provider_circuit_state)

    with st.expander("Diagnostics JSON", expanded=False):
        st.json(diagnostics)
