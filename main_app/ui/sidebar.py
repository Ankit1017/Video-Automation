from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import streamlit as st

from main_app.constants import PRESET_MODELS, TAB_TITLES
from main_app.models import GroqSettings, WebSourcingSettings
from main_app.platform.web_sourcing.prechecks import parse_domain_list


_WEB_SOURCING_BEST_PROFILE = {
    "cache_ttl_seconds": 21_600,
    "max_search_results": 8,
    "max_fetch_pages": 6,
    "max_chars_per_page": 4_000,
    "max_total_chars": 20_000,
    "timeout_ms": 8_000,
    "query_variant_count": 3,
    "candidate_pool_multiplier": 3,
    "min_quality_score": 0.45,
    "max_results_per_domain": 2,
    "trusted_boost_enabled": True,
    "trusted_domains": [],
    "allow_provider_failover": True,
    "retry_count": 2,
    "retry_base_delay_ms": 250,
    "retry_max_delay_ms": 1_500,
    "domain_rate_limit_per_minute": 6,
    "provider_circuit_breaker_enabled": True,
    "provider_error_threshold": 4,
    "provider_cooldown_seconds": 120,
    "provider_probe_requests": 1,
    "reliability_diagnostics_enabled": True,
}


@dataclass
class SidebarRenderResult:
    settings: GroqSettings
    cache_count_placeholder: Any
    web_sourcing_settings: WebSourcingSettings
    enabled_tab_titles: list[str]


class _NoopCacheCountPlaceholder:
    def caption(self, _value: str) -> None:
        return


def render_sidebar() -> SidebarRenderResult:
    cache_count_placeholder: Any = _NoopCacheCountPlaceholder()

    model_mode = " ".join(str(st.session_state.get("groq_model_mode", "Pick from list")).split()).strip()
    if model_mode not in {"Pick from list", "Custom model ID"}:
        model_mode = "Pick from list"
    st.session_state["groq_model_mode"] = model_mode

    selected_model = " ".join(str(st.session_state.get("groq_model_select", PRESET_MODELS[0])).split()).strip()
    if selected_model not in PRESET_MODELS:
        selected_model = PRESET_MODELS[0]
    st.session_state["groq_model_select"] = selected_model

    custom_model = " ".join(str(st.session_state.get("groq_model_custom", "")).split()).strip()
    st.session_state["groq_model_custom"] = custom_model

    requested_tabs = st.session_state.get("enabled_tab_titles", list(TAB_TITLES))
    requested_tabs_list = requested_tabs if isinstance(requested_tabs, list) else list(TAB_TITLES)
    requested_tab_set = {str(item).strip() for item in requested_tabs_list if str(item).strip()}
    normalized_requested_tabs = [title for title in TAB_TITLES if title in requested_tab_set]
    st.session_state["enabled_tab_titles"] = normalized_requested_tabs

    provider_key = " ".join(str(st.session_state.get("web_sourcing_provider", "duckduckgo")).split()).strip().lower()
    if provider_key not in {"duckduckgo", "serper"}:
        provider_key = "duckduckgo"
    st.session_state["web_sourcing_provider"] = provider_key

    secondary_provider_key = (
        " ".join(str(st.session_state.get("web_sourcing_secondary_provider_key", "serper")).split()).strip().lower()
    )
    if secondary_provider_key not in {"duckduckgo", "serper"}:
        secondary_provider_key = "serper" if provider_key != "serper" else "duckduckgo"
    if secondary_provider_key == provider_key:
        secondary_provider_key = "serper" if provider_key != "serper" else "duckduckgo"
    st.session_state["web_sourcing_secondary_provider_key"] = secondary_provider_key

    with st.sidebar:
        st.header("Groq Configuration")

        api_key = st.text_input("Groq API Key", type="password", help="Your Groq API key.")
        model_mode = st.radio(
            "Model Selection",
            options=["Pick from list", "Custom model ID"],
            index=0 if model_mode == "Pick from list" else 1,
            key="groq_model_mode",
            horizontal=True,
        )
        selected_model = st.selectbox(
            "Model",
            options=PRESET_MODELS,
            index=PRESET_MODELS.index(selected_model),
            key="groq_model_select",
            disabled=model_mode != "Pick from list",
        )
        custom_model = " ".join(
            str(
                st.text_input(
                    "Custom model ID",
                    value=custom_model,
                    key="groq_model_custom",
                    disabled=model_mode != "Custom model ID",
                )
            ).split()
        ).strip()
        temperature = float(
            st.slider(
                "Temperature",
                min_value=0.0,
                max_value=1.5,
                value=float(st.session_state.get("groq_temperature", 0.4)),
                step=0.05,
                key="groq_temperature",
            )
        )
        max_tokens = int(
            st.number_input(
                "Max Tokens",
                min_value=64,
                max_value=8192,
                value=int(st.session_state.get("groq_max_tokens", 1400)),
                step=64,
                key="groq_max_tokens",
            )
        )

        st.markdown("---")
        st.subheader("Tab Enablement")
        enabled_tab_titles = st.multiselect(
            "Visible Tabs",
            options=TAB_TITLES,
            default=normalized_requested_tabs,
            key="enabled_tab_titles",
            help="Choose which main tabs are visible in the app.",
        )

        st.markdown("---")
        st.subheader("Web Sourcing")
        web_enabled = bool(
            st.checkbox(
                "Enable Global Web Sourcing",
                value=bool(st.session_state.get("web_sourcing_enabled", False)),
                key="web_sourcing_enabled",
            )
        )
        provider_key = str(
            st.selectbox(
                "Provider",
                options=["duckduckgo", "serper"],
                index=0 if provider_key != "serper" else 1,
                key="web_sourcing_provider",
            )
        ).strip().lower()
        include_domains_raw = st.text_area(
            "Include Domains (comma/newline separated)",
            value=str(st.session_state.get("web_sourcing_include_domains_raw", "")),
            height=70,
            key="web_sourcing_include_domains_raw",
        )
        exclude_domains_raw = st.text_area(
            "Exclude Domains (comma/newline separated)",
            value=str(st.session_state.get("web_sourcing_exclude_domains_raw", "")),
            height=70,
            key="web_sourcing_exclude_domains_raw",
        )

        with st.expander("Advanced Web Sourcing", expanded=False):
            allow_recency_days = int(
                st.number_input(
                    "Recency Window (days, 0 = disabled)",
                    min_value=0,
                    max_value=3650,
                    value=int(st.session_state.get("web_sourcing_allow_recency_days", 0)),
                    step=1,
                    key="web_sourcing_allow_recency_days",
                )
            )
            force_refresh = bool(
                st.checkbox(
                    "Force Refresh (skip cache)",
                    value=bool(st.session_state.get("web_sourcing_force_refresh", False)),
                    key="web_sourcing_force_refresh",
                )
            )
            strict_mode = bool(
                st.checkbox(
                    "Strict Mode (require accepted web sources)",
                    value=bool(st.session_state.get("web_sourcing_strict_mode", False)),
                    key="web_sourcing_strict_mode",
                )
            )
            secondary_provider_key = str(
                st.selectbox(
                    "Secondary Provider (Failover)",
                    options=["duckduckgo", "serper"],
                    index=0 if secondary_provider_key != "serper" else 1,
                    key="web_sourcing_secondary_provider_key",
                )
            ).strip().lower()
            trusted_domains_raw = st.text_area(
                "Trusted Domains (boost, comma/newline separated)",
                value=str(st.session_state.get("web_sourcing_trusted_domains_raw", "")),
                height=70,
                key="web_sourcing_trusted_domains_raw",
            )

    model = selected_model if model_mode == "Pick from list" else custom_model
    if not model:
        model = PRESET_MODELS[0]

    if provider_key not in {"duckduckgo", "serper"}:
        provider_key = "duckduckgo"
    if secondary_provider_key not in {"duckduckgo", "serper"}:
        secondary_provider_key = "serper" if provider_key != "serper" else "duckduckgo"
    if secondary_provider_key == provider_key:
        secondary_provider_key = "serper" if provider_key != "serper" else "duckduckgo"

    settings = GroqSettings(
        api_key=api_key,
        model=model,
        temperature=float(temperature),
        max_tokens=int(max_tokens),
    )
    web_sourcing_settings = WebSourcingSettings(
        enabled=bool(web_enabled),
        provider_key=str(provider_key).strip().lower() or "duckduckgo",
        cache_ttl_seconds=int(st.session_state.get("web_sourcing_cache_ttl_seconds", _WEB_SOURCING_BEST_PROFILE["cache_ttl_seconds"])),
        max_search_results=int(st.session_state.get("web_sourcing_max_search_results", _WEB_SOURCING_BEST_PROFILE["max_search_results"])),
        max_fetch_pages=int(st.session_state.get("web_sourcing_max_fetch_pages", _WEB_SOURCING_BEST_PROFILE["max_fetch_pages"])),
        max_chars_per_page=int(st.session_state.get("web_sourcing_max_chars_per_page", _WEB_SOURCING_BEST_PROFILE["max_chars_per_page"])),
        max_total_chars=int(st.session_state.get("web_sourcing_max_total_chars", _WEB_SOURCING_BEST_PROFILE["max_total_chars"])),
        timeout_ms=int(st.session_state.get("web_sourcing_timeout_ms", _WEB_SOURCING_BEST_PROFILE["timeout_ms"])),
        force_refresh=bool(force_refresh),
        include_domains=parse_domain_list(str(include_domains_raw)),
        exclude_domains=parse_domain_list(str(exclude_domains_raw)),
        allow_recency_days=int(allow_recency_days) if int(allow_recency_days) > 0 else None,
        strict_mode=bool(strict_mode),
        query_variant_count=int(st.session_state.get("web_sourcing_query_variant_count", _WEB_SOURCING_BEST_PROFILE["query_variant_count"])),
        candidate_pool_multiplier=int(st.session_state.get("web_sourcing_candidate_pool_multiplier", _WEB_SOURCING_BEST_PROFILE["candidate_pool_multiplier"])),
        min_quality_score=float(st.session_state.get("web_sourcing_min_quality_score", _WEB_SOURCING_BEST_PROFILE["min_quality_score"])),
        max_results_per_domain=int(st.session_state.get("web_sourcing_max_results_per_domain", _WEB_SOURCING_BEST_PROFILE["max_results_per_domain"])),
        trusted_boost_enabled=bool(st.session_state.get("web_sourcing_trusted_boost_enabled", _WEB_SOURCING_BEST_PROFILE["trusted_boost_enabled"])),
        trusted_domains=parse_domain_list(str(trusted_domains_raw)),
        allow_provider_failover=bool(st.session_state.get("web_sourcing_allow_provider_failover", _WEB_SOURCING_BEST_PROFILE["allow_provider_failover"])),
        secondary_provider_key=str(secondary_provider_key).strip().lower(),
        retry_count=int(st.session_state.get("web_sourcing_retry_count", _WEB_SOURCING_BEST_PROFILE["retry_count"])),
        retry_base_delay_ms=int(st.session_state.get("web_sourcing_retry_base_delay_ms", _WEB_SOURCING_BEST_PROFILE["retry_base_delay_ms"])),
        retry_max_delay_ms=int(st.session_state.get("web_sourcing_retry_max_delay_ms", _WEB_SOURCING_BEST_PROFILE["retry_max_delay_ms"])),
        domain_rate_limit_per_minute=int(st.session_state.get("web_sourcing_domain_rate_limit_per_minute", _WEB_SOURCING_BEST_PROFILE["domain_rate_limit_per_minute"])),
        provider_circuit_breaker_enabled=bool(st.session_state.get("web_sourcing_provider_circuit_breaker_enabled", _WEB_SOURCING_BEST_PROFILE["provider_circuit_breaker_enabled"])),
        provider_error_threshold=int(st.session_state.get("web_sourcing_provider_error_threshold", _WEB_SOURCING_BEST_PROFILE["provider_error_threshold"])),
        provider_cooldown_seconds=int(st.session_state.get("web_sourcing_provider_cooldown_seconds", _WEB_SOURCING_BEST_PROFILE["provider_cooldown_seconds"])),
        provider_probe_requests=int(st.session_state.get("web_sourcing_provider_probe_requests", _WEB_SOURCING_BEST_PROFILE["provider_probe_requests"])),
        reliability_diagnostics_enabled=bool(st.session_state.get("web_sourcing_reliability_diagnostics_enabled", _WEB_SOURCING_BEST_PROFILE["reliability_diagnostics_enabled"])),
    )
    return SidebarRenderResult(
        settings=settings,
        cache_count_placeholder=cache_count_placeholder,
        web_sourcing_settings=web_sourcing_settings,
        enabled_tab_titles=[str(title) for title in enabled_tab_titles if str(title).strip()],
    )
