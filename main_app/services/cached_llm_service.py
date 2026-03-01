from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from main_app.infrastructure.cache_store import CacheStore
from main_app.infrastructure.groq_client import (
    ChatCompletionClient,
    ChatCompletionMetadataClient,
    CompletionResult,
    CompletionUsage,
)
from main_app.models import GroqSettings
from main_app.services.observability_service import ObservabilityService, ensure_request_id


class CachedLLMService:
    def __init__(
        self,
        *,
        chat_client: ChatCompletionClient,
        cache_store: CacheStore,
        cache_data: dict[str, Any],
        observability_service: ObservabilityService | None = None,
    ) -> None:
        self._chat_client = chat_client
        self._cache_store = cache_store
        self._cache_data = cache_data
        self._observability_service = observability_service

    @property
    def count(self) -> int:
        return len(self._cache_data)

    @property
    def observability(self) -> ObservabilityService | None:
        return self._observability_service

    def metrics_table_rows(self) -> list[dict[str, Any]]:
        if self._observability_service is None:
            return []
        return self._observability_service.metrics_table_rows()

    def current_request_id(self) -> str:
        if self._observability_service is None:
            return ""
        return self._observability_service.current_request_id()

    def cache_keys_latest_first(self) -> list[str]:
        return list(self._cache_data.keys())[::-1]

    def cache_entry_label(self, cache_key: str) -> str:
        cache_entry = self._cache_data.get(cache_key)
        if isinstance(cache_entry, dict):
            label = cache_entry.get("label") or cache_entry.get("topic") or "Cached entry"
            label = " ".join(str(label).split())
            if len(label) > 42:
                label = label[:39] + "..."
            task = cache_entry.get("task", "task")
            model_name = cache_entry.get("model", "unknown-model")
            return f"{label} | {task} | {model_name} | {cache_key[:8]}"
        return f"{cache_key[:8]} (legacy)"

    def cache_entry(self, cache_key: str) -> dict[str, Any] | None:
        cache_entry = self._cache_data.get(cache_key)
        if not isinstance(cache_entry, dict):
            return None
        response_text = str(cache_entry.get("response", ""))
        usage = self._extract_cached_usage(cache_entry)
        return {
            "key": cache_key,
            "task": " ".join(str(cache_entry.get("task", "")).split()).strip(),
            "model": " ".join(str(cache_entry.get("model", "")).split()).strip(),
            "topic": " ".join(str(cache_entry.get("topic", "")).split()).strip(),
            "label": " ".join(str(cache_entry.get("label", "")).split()).strip(),
            "response": response_text,
            "response_chars": len(response_text),
            "usage": self._usage_to_cache_dict(usage),
        }

    def cache_entries_latest_first(self) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for cache_key in self.cache_keys_latest_first():
            entry = self.cache_entry(cache_key)
            if entry is None:
                entries.append(
                    {
                        "key": cache_key,
                        "task": "",
                        "model": "",
                        "topic": "",
                        "label": "",
                        "response": "",
                        "response_chars": 0,
                        "usage": None,
                    }
                )
            else:
                entries.append(entry)
        return entries

    def clear_entry(self, cache_key: str) -> None:
        self._cache_data.pop(cache_key, None)
        self._cache_store.save(self._cache_data)

    def clear_all(self) -> None:
        self._cache_data.clear()
        self._cache_store.save(self._cache_data)

    def call(
        self,
        *,
        settings: GroqSettings,
        messages: list[dict[str, str]],
        task: str,
        label: str,
        topic: str,
        temperature_override: float | None = None,
        max_tokens_override: int | None = None,
        use_cache: bool = True,
    ) -> tuple[str, bool]:
        request_id = ensure_request_id()
        model = settings.normalized_model
        temperature = float(settings.temperature if temperature_override is None else temperature_override)
        max_tokens = int(settings.max_tokens if max_tokens_override is None else max_tokens_override)
        started_at = time.perf_counter()

        cache_key = self._make_cache_key(
            task=task,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            messages=messages,
        )

        if use_cache and cache_key in self._cache_data:
            cached_entry = self._cache_data[cache_key]
            cached_response = self._extract_cached_response(cached_entry)
            usage = self._extract_cached_usage(cached_entry)
            self._record_observability(
                task=task,
                model=model,
                cache_hit=True,
                started_at=started_at,
                request_id=request_id,
                usage=usage,
                error="",
            )
            return cached_response, True

        try:
            response = self._complete_with_optional_metadata(
                api_key=settings.api_key,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                messages=messages,
            )
        except Exception as exc:  # noqa: BLE001
            self._record_observability(
                task=task,
                model=model,
                cache_hit=False,
                started_at=started_at,
                request_id=request_id,
                usage=None,
                error=str(exc),
            )
            raise

        response_text = response.text
        usage = response.usage

        self._record_observability(
            task=task,
            model=model,
            cache_hit=False,
            started_at=started_at,
            request_id=request_id,
            usage=usage,
            error="",
        )

        if use_cache:
            self._cache_data[cache_key] = {
                "response": response_text,
                "topic": topic,
                "model": model,
                "task": task,
                "label": label,
                "usage": self._usage_to_cache_dict(usage),
            }
            self._cache_store.save(self._cache_data)
        return response_text, False

    @staticmethod
    def _make_cache_key(
        *,
        task: str,
        model: str,
        temperature: float,
        max_tokens: int,
        messages: list[dict[str, str]],
    ) -> str:
        cache_payload = {
            "task": task,
            "model": model,
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
            "messages": messages,
        }
        return hashlib.sha256(json.dumps(cache_payload, sort_keys=True).encode("utf-8")).hexdigest()

    @staticmethod
    def _extract_cached_response(cache_entry: Any) -> str:
        if isinstance(cache_entry, dict):
            return str(cache_entry.get("response", "No response received."))
        if isinstance(cache_entry, str):
            return cache_entry
        return str(cache_entry)

    @staticmethod
    def _extract_cached_usage(cache_entry: Any) -> CompletionUsage | None:
        if not isinstance(cache_entry, dict):
            return None
        usage = cache_entry.get("usage")
        if not isinstance(usage, dict):
            return None
        try:
            prompt_tokens = max(int(usage.get("prompt_tokens", 0) or 0), 0)
            completion_tokens = max(int(usage.get("completion_tokens", 0) or 0), 0)
            total_tokens = max(int(usage.get("total_tokens", 0) or 0), prompt_tokens + completion_tokens)
        except (TypeError, ValueError):
            return None
        return CompletionUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )

    def _complete_with_optional_metadata(
        self,
        *,
        api_key: str,
        model: str,
        temperature: float,
        max_tokens: int,
        messages: list[dict[str, str]],
    ) -> CompletionResult:
        if isinstance(self._chat_client, ChatCompletionMetadataClient):
            return self._chat_client.complete_with_metadata(
                api_key=api_key,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                messages=messages,
            )
        text = self._chat_client.complete(
            api_key=api_key,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            messages=messages,
        )
        return CompletionResult(text=text, usage=None)

    def _record_observability(
        self,
        *,
        task: str,
        model: str,
        cache_hit: bool,
        started_at: float,
        request_id: str,
        usage: CompletionUsage | None,
        error: str,
    ) -> None:
        if self._observability_service is None:
            return

        latency_ms = max((time.perf_counter() - started_at) * 1000.0, 0.0)
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0
        total_tokens = usage.total_tokens if usage else (prompt_tokens + completion_tokens)
        self._observability_service.record_llm_call(
            task=task,
            model=model,
            cache_hit=cache_hit,
            latency_ms=latency_ms,
            request_id=request_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            error=error,
        )

    @staticmethod
    def _usage_to_cache_dict(usage: CompletionUsage | None) -> dict[str, int] | None:
        if usage is None:
            return None
        return {
            "prompt_tokens": int(usage.prompt_tokens),
            "completion_tokens": int(usage.completion_tokens),
            "total_tokens": int(usage.total_tokens),
        }
