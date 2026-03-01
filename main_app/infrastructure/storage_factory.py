from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path
from typing import Any

from main_app.infrastructure.agent_dashboard_session_store import (
    AgentDashboardSessionRepository,
    AgentDashboardSessionStore,
    MongoAgentDashboardSessionStore,
)
from main_app.infrastructure.asset_history_store import (
    AssetHistoryRepository,
    AssetHistoryStore,
    MongoAssetHistoryStore,
)
from main_app.infrastructure.cache_store import CacheStore, JsonFileCacheStore, MongoCacheStore
from main_app.infrastructure.orchestration_ledger_store import (
    JsonRunLedgerStore,
    JsonStageLedgerStore,
    MongoRunLedgerStore,
    MongoStageLedgerStore,
)
from main_app.infrastructure.quiz_history_store import (
    MongoQuizHistoryStore,
    QuizHistoryRepository,
    QuizHistoryStore,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StorageBundle:
    cache_store: CacheStore
    cache_label: str
    asset_history_store: AssetHistoryRepository
    quiz_history_store: QuizHistoryRepository
    agent_dashboard_session_store: AgentDashboardSessionRepository
    run_ledger_store: Any
    stage_ledger_store: Any


def build_storage_bundle(
    *,
    cache_file: Path,
    asset_history_file: Path,
    quiz_history_file: Path,
    agent_dashboard_sessions_file: Path,
    run_ledger_file: Path | None = None,
    stage_ledger_file: Path | None = None,
    telemetry_service: Any | None = None,
) -> StorageBundle:
    resolved_run_ledger_file = run_ledger_file or cache_file.parent / "run_ledger.json"
    resolved_stage_ledger_file = stage_ledger_file or cache_file.parent / "stage_ledger.json"
    mode = _storage_mode()
    if mode == "json":
        bundle = _build_json_bundle(
            cache_file=cache_file,
            asset_history_file=asset_history_file,
            quiz_history_file=quiz_history_file,
            agent_dashboard_sessions_file=agent_dashboard_sessions_file,
            run_ledger_file=resolved_run_ledger_file,
            stage_ledger_file=resolved_stage_ledger_file,
        )
        return _instrument_bundle(bundle=bundle, telemetry_service=telemetry_service)

    uri = os.getenv("MONGODB_URI", "").strip()
    if not uri:
        if mode == "mongo":
            raise RuntimeError("MONGODB_URI is required when APP_STORE_BACKEND is set to `mongo`.")
        bundle = _build_json_bundle(
            cache_file=cache_file,
            asset_history_file=asset_history_file,
            quiz_history_file=quiz_history_file,
            agent_dashboard_sessions_file=agent_dashboard_sessions_file,
            run_ledger_file=resolved_run_ledger_file,
            stage_ledger_file=resolved_stage_ledger_file,
        )
        return _instrument_bundle(bundle=bundle, telemetry_service=telemetry_service)

    try:
        mongo_bundle = _build_mongo_bundle(uri=uri)
        _warm_up_mongo_bundle(mongo_bundle)
        _migrate_json_to_mongo_if_needed(
            mongo_bundle=mongo_bundle,
            cache_file=cache_file,
            asset_history_file=asset_history_file,
            quiz_history_file=quiz_history_file,
            agent_dashboard_sessions_file=agent_dashboard_sessions_file,
            run_ledger_file=resolved_run_ledger_file,
            stage_ledger_file=resolved_stage_ledger_file,
        )
        return _instrument_bundle(bundle=mongo_bundle, telemetry_service=telemetry_service)
    except Exception as exc:  # noqa: BLE001
        if mode == "mongo":
            raise
        logger.exception("MongoDB storage unavailable; falling back to JSON stores: %s", exc)
        bundle = _build_json_bundle(
            cache_file=cache_file,
            asset_history_file=asset_history_file,
            quiz_history_file=quiz_history_file,
            agent_dashboard_sessions_file=agent_dashboard_sessions_file,
            run_ledger_file=resolved_run_ledger_file,
            stage_ledger_file=resolved_stage_ledger_file,
        )
        return _instrument_bundle(bundle=bundle, telemetry_service=telemetry_service)


def _storage_mode() -> str:
    raw_mode = " ".join(str(os.getenv("APP_STORE_BACKEND", "auto")).strip().lower().split())
    if raw_mode in {"json", "mongo"}:
        return raw_mode
    return "auto"


def _build_json_bundle(
    *,
    cache_file: Path,
    asset_history_file: Path,
    quiz_history_file: Path,
    agent_dashboard_sessions_file: Path,
    run_ledger_file: Path,
    stage_ledger_file: Path,
) -> StorageBundle:
    return StorageBundle(
        cache_store=JsonFileCacheStore(cache_file),
        cache_label=str(cache_file),
        asset_history_store=AssetHistoryStore(asset_history_file),
        quiz_history_store=QuizHistoryStore(quiz_history_file),
        agent_dashboard_session_store=AgentDashboardSessionStore(agent_dashboard_sessions_file),
        run_ledger_store=JsonRunLedgerStore(run_ledger_file),
        stage_ledger_store=JsonStageLedgerStore(stage_ledger_file),
    )


def _build_mongo_bundle(*, uri: str) -> StorageBundle:
    db_name = str(os.getenv("MONGODB_DB", "knowledge_app")).strip() or "knowledge_app"
    cache_collection = str(os.getenv("MONGODB_COLLECTION_CACHE", "llm_cache")).strip() or "llm_cache"
    asset_collection = (
        str(os.getenv("MONGODB_COLLECTION_ASSET_HISTORY", "asset_history")).strip() or "asset_history"
    )
    quiz_collection = str(os.getenv("MONGODB_COLLECTION_QUIZ_HISTORY", "quiz_history")).strip() or "quiz_history"
    sessions_collection = (
        str(os.getenv("MONGODB_COLLECTION_AGENT_SESSIONS", "agent_dashboard_sessions")).strip()
        or "agent_dashboard_sessions"
    )
    run_ledger_collection = str(os.getenv("MONGODB_COLLECTION_RUN_LEDGER", "run_ledger")).strip() or "run_ledger"
    stage_ledger_collection = (
        str(os.getenv("MONGODB_COLLECTION_STAGE_LEDGER", "stage_ledger")).strip() or "stage_ledger"
    )

    cache_store = MongoCacheStore(
        uri=uri,
        db_name=db_name,
        collection_name=cache_collection,
    )
    return StorageBundle(
        cache_store=cache_store,
        cache_label=cache_store.description,
        asset_history_store=MongoAssetHistoryStore(
            uri=uri,
            db_name=db_name,
            collection_name=asset_collection,
        ),
        quiz_history_store=MongoQuizHistoryStore(
            uri=uri,
            db_name=db_name,
            collection_name=quiz_collection,
        ),
        agent_dashboard_session_store=MongoAgentDashboardSessionStore(
            uri=uri,
            db_name=db_name,
            collection_name=sessions_collection,
        ),
        run_ledger_store=MongoRunLedgerStore(
            uri=uri,
            db_name=db_name,
            collection_name=run_ledger_collection,
        ),
        stage_ledger_store=MongoStageLedgerStore(
            uri=uri,
            db_name=db_name,
            collection_name=stage_ledger_collection,
        ),
    )


def _warm_up_mongo_bundle(bundle: StorageBundle) -> None:
    bundle.cache_store.load()
    bundle.asset_history_store.list_records()
    bundle.quiz_history_store.list_quizzes()
    bundle.agent_dashboard_session_store.list_sessions()
    bundle.run_ledger_store.list_records()
    bundle.stage_ledger_store.list_records()


def _migrate_json_to_mongo_if_needed(
    *,
    mongo_bundle: StorageBundle,
    cache_file: Path,
    asset_history_file: Path,
    quiz_history_file: Path,
    agent_dashboard_sessions_file: Path,
    run_ledger_file: Path,
    stage_ledger_file: Path,
) -> None:
    json_bundle = _build_json_bundle(
        cache_file=cache_file,
        asset_history_file=asset_history_file,
        quiz_history_file=quiz_history_file,
        agent_dashboard_sessions_file=agent_dashboard_sessions_file,
        run_ledger_file=run_ledger_file,
        stage_ledger_file=stage_ledger_file,
    )

    target_cache = mongo_bundle.cache_store.load()
    source_cache = json_bundle.cache_store.load()
    if not target_cache and source_cache:
        mongo_bundle.cache_store.save(source_cache)
        logger.info("Migrated %s cache entries from JSON to MongoDB.", len(source_cache))

    target_assets = mongo_bundle.asset_history_store.list_records()
    source_assets = json_bundle.asset_history_store.list_records()
    if not target_assets and source_assets:
        mongo_bundle.asset_history_store.save_records(source_assets)
        logger.info("Migrated %s asset history records from JSON to MongoDB.", len(source_assets))

    target_quizzes = mongo_bundle.quiz_history_store.list_quizzes()
    source_quizzes = json_bundle.quiz_history_store.list_quizzes()
    if not target_quizzes and source_quizzes:
        mongo_bundle.quiz_history_store.save_quizzes(source_quizzes)
        logger.info("Migrated %s quiz history records from JSON to MongoDB.", len(source_quizzes))

    target_sessions = mongo_bundle.agent_dashboard_session_store.list_sessions()
    source_sessions = json_bundle.agent_dashboard_session_store.list_sessions()
    if not target_sessions and source_sessions:
        mongo_bundle.agent_dashboard_session_store.save_sessions(source_sessions)
        logger.info("Migrated %s agent dashboard sessions from JSON to MongoDB.", len(source_sessions))

    target_run_records = mongo_bundle.run_ledger_store.list_records()
    source_run_records = json_bundle.run_ledger_store.list_records()
    if not target_run_records and source_run_records:
        mongo_bundle.run_ledger_store.save_records(source_run_records)
        logger.info("Migrated %s run ledger records from JSON to MongoDB.", len(source_run_records))

    target_stage_records = mongo_bundle.stage_ledger_store.list_records()
    source_stage_records = json_bundle.stage_ledger_store.list_records()
    if not target_stage_records and source_stage_records:
        mongo_bundle.stage_ledger_store.save_records(source_stage_records)
        logger.info("Migrated %s stage ledger records from JSON to MongoDB.", len(source_stage_records))


def _instrument_bundle(*, bundle: StorageBundle, telemetry_service: Any | None) -> StorageBundle:
    if telemetry_service is None:
        return bundle
    return StorageBundle(
        cache_store=_InstrumentedStoreProxy(
            store=bundle.cache_store,
            telemetry_service=telemetry_service,
            component="storage.cache_store",
        ),
        cache_label=bundle.cache_label,
        asset_history_store=_InstrumentedStoreProxy(
            store=bundle.asset_history_store,
            telemetry_service=telemetry_service,
            component="storage.asset_history_store",
        ),
        quiz_history_store=_InstrumentedStoreProxy(
            store=bundle.quiz_history_store,
            telemetry_service=telemetry_service,
            component="storage.quiz_history_store",
        ),
        agent_dashboard_session_store=_InstrumentedStoreProxy(
            store=bundle.agent_dashboard_session_store,
            telemetry_service=telemetry_service,
            component="storage.agent_session_store",
        ),
        run_ledger_store=_InstrumentedStoreProxy(
            store=bundle.run_ledger_store,
            telemetry_service=telemetry_service,
            component="storage.run_ledger_store",
        ),
        stage_ledger_store=_InstrumentedStoreProxy(
            store=bundle.stage_ledger_store,
            telemetry_service=telemetry_service,
            component="storage.stage_ledger_store",
        ),
    )


class _InstrumentedStoreProxy:
    _WRAPPED_METHODS = {
        "load",
        "save",
        "list_records",
        "save_records",
        "upsert_record",
        "list_quizzes",
        "save_quizzes",
        "upsert_session",
        "list_sessions",
        "delete_session",
    }

    def __init__(self, *, store: Any, telemetry_service: Any, component: str) -> None:
        self._store = store
        self._telemetry_service = telemetry_service
        self._component = component

    def __getattr__(self, item: str) -> Any:
        target = getattr(self._store, item)
        if not callable(target) or item not in self._WRAPPED_METHODS:
            return target

        def _wrapped(*args: Any, **kwargs: Any) -> Any:
            from time import perf_counter
            started = perf_counter()
            try:
                result = target(*args, **kwargs)
                duration_ms = max((perf_counter() - started) * 1000.0, 0.0)
                self._record(status="ok", method=item, duration_ms=duration_ms, error="")
                return result
            except (OSError, RuntimeError, ValueError, TypeError, KeyError, AttributeError) as exc:
                duration_ms = max((perf_counter() - started) * 1000.0, 0.0)
                self._record(status="error", method=item, duration_ms=duration_ms, error=str(exc))
                raise

        return _wrapped

    def _record(self, *, status: str, method: str, duration_ms: float, error: str) -> None:
        attrs = {"component": self._component, "method": method, "status": status}
        self._telemetry_service.record_metric(
            name="storage_operation_duration_ms",
            value=duration_ms,
            attrs=attrs,
        )
        self._telemetry_service.record_event(
            {
                "event_name": "storage.operation",
                "component": self._component,
                "status": status,
                "timestamp": _now_iso(),
                "attributes": {**attrs, "duration_ms": round(duration_ms, 3), "error": error},
            }
        )


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
