from __future__ import annotations

from base64 import b64decode, b64encode
from datetime import datetime, timezone
import binascii
from typing import Any
from uuid import uuid4

from main_app.contracts import AgentDashboardSessionEntry
from main_app.infrastructure.agent_dashboard_session_store import AgentDashboardSessionRepository
from main_app.services.intent import IntentRouterService
from main_app.ui.agent_dashboard.state_gateway import SessionStateGateway, StreamlitSessionStateGateway


class AgentDashboardSessionManager:
    _PLANNER_MODES = {"Local First (No LLM if possible)", "Detect and Prepare Using LLM"}

    def __init__(
        self,
        session_store: AgentDashboardSessionRepository,
        *,
        state: SessionStateGateway | None = None,
    ) -> None:
        self._session_store = session_store
        self._state: SessionStateGateway = state or StreamlitSessionStateGateway()

    @property
    def session_store(self) -> AgentDashboardSessionRepository:
        return self._session_store

    @property
    def state(self) -> SessionStateGateway:
        return self._state

    def list_saved_sessions(self) -> list[AgentDashboardSessionEntry]:
        return self._session_store.list_sessions()

    def get_session(self, session_id: str) -> AgentDashboardSessionEntry | None:
        return self._session_store.get_session(session_id)

    def delete_session(self, session_id: str) -> None:
        self._session_store.delete_session(session_id)

    def bootstrap_session(self) -> None:
        if bool(self._state.get("agent_dashboard_store_initialized", False)):
            return

        saved_sessions = self._session_store.list_sessions()
        if saved_sessions:
            latest_session = saved_sessions[0]
            self.restore_session_from_store_record(latest_session)
        else:
            self.start_fresh_session()

        self._state.set("agent_dashboard_store_initialized", True)

    def start_fresh_session(self) -> None:
        self._state.set("agent_dashboard_history", [])
        self._state.set("agent_dashboard_pending_plan", None)
        self._state.set("agent_dashboard_active_topic", "")
        self._state.set("agent_dashboard_recent_topics", [])
        self._state.set("agent_dashboard_session_id", uuid4().hex[:16])
        self._state.set("agent_dashboard_session_created_at", self._utc_now_iso())
        self._state.set("agent_dashboard_force_sync_saved_selector", True)
        self._state.set("agent_dashboard_force_sync_planner_selector", True)

    def saved_session_label(self, saved_sessions: list[AgentDashboardSessionEntry], session_id: str) -> str:
        target = str(session_id).strip()
        for item in saved_sessions:
            item_id = str(item.get("id", "")).strip()
            if item_id != target:
                continue

            title = str(item.get("title", "")).strip() or "Agent Session"
            updated_at = str(item.get("updated_at", "")).strip()
            updated_label = updated_at.replace("T", " ").replace("+00:00", "Z")
            if len(updated_label) > 19:
                updated_label = updated_label[:19]
            history = item.get("history", [])
            message_count = len(history) if isinstance(history, list) else 0
            return f"{title} | {message_count} msgs | {updated_label} | {target[:8]}"
        return target

    def restore_session_from_store_record(self, session_record: AgentDashboardSessionEntry) -> None:
        record = session_record if isinstance(session_record, dict) else {}
        session_id = str(record.get("id", "")).strip() or uuid4().hex[:16]
        created_at = str(record.get("created_at", "")).strip() or self._utc_now_iso()

        history = self._json_restore_from_store(record.get("history", []))
        if not isinstance(history, list):
            history = []

        pending_plan = self._json_restore_from_store(record.get("pending_plan"))
        if pending_plan is not None and not isinstance(pending_plan, dict):
            pending_plan = None

        raw_active_topic = " ".join(str(record.get("active_topic", "")).split()).strip()
        recent_topics_raw = self._json_restore_from_store(record.get("recent_topics", []))
        recent_topics = [str(item).strip() for item in recent_topics_raw] if isinstance(recent_topics_raw, list) else []
        recent_topics = [item for item in recent_topics if item]
        active_topic = self._resolve_best_active_topic(
            active_topic=raw_active_topic,
            recent_topics=recent_topics,
            history=history,
            title=str(record.get("title", "")).strip(),
        )

        planner_mode = str(record.get("planner_mode", "")).strip()
        if planner_mode not in self._PLANNER_MODES:
            planner_mode = str(
                self._state.get("agent_dashboard_planner_mode", "Local First (No LLM if possible)")
            ).strip()
            if planner_mode not in self._PLANNER_MODES:
                planner_mode = "Local First (No LLM if possible)"

        self._state.set("agent_dashboard_session_id", session_id)
        self._state.set("agent_dashboard_session_created_at", created_at)
        self._state.set("agent_dashboard_history", history)
        self._state.set("agent_dashboard_pending_plan", pending_plan)
        self._state.set("agent_dashboard_active_topic", active_topic)
        self._state.set("agent_dashboard_recent_topics", recent_topics)
        self._state.set("agent_dashboard_planner_mode", planner_mode)
        self._state.set("agent_dashboard_selected_saved_session_id", session_id)
        self._state.set("agent_dashboard_force_sync_saved_selector", True)
        self._state.set("agent_dashboard_force_sync_planner_selector", True)

    def persist_current_session(self) -> None:
        history = (
            self._state.get("agent_dashboard_history", [])
            if isinstance(self._state.get("agent_dashboard_history", []), list)
            else []
        )
        pending_plan = (
            self._state.get("agent_dashboard_pending_plan")
            if isinstance(self._state.get("agent_dashboard_pending_plan"), dict)
            else None
        )
        raw_active_topic = " ".join(str(self._state.get("agent_dashboard_active_topic", "")).split()).strip()
        recent_topics = (
            self._state.get("agent_dashboard_recent_topics", [])
            if isinstance(self._state.get("agent_dashboard_recent_topics", []), list)
            else []
        )
        recent_topics = [" ".join(str(item).split()).strip() for item in recent_topics if " ".join(str(item).split()).strip()]
        active_topic = self._resolve_best_active_topic(
            active_topic=raw_active_topic,
            recent_topics=recent_topics,
            history=history,
            title="",
        )
        if active_topic:
            self._state.set("agent_dashboard_active_topic", active_topic)
            if active_topic not in recent_topics:
                recent_topics = [active_topic, *[item for item in recent_topics if item.lower() != active_topic.lower()]]

        has_content = bool(history) or bool(pending_plan) or bool(active_topic) or bool(recent_topics)
        if not has_content:
            return

        session_id = " ".join(str(self._state.get("agent_dashboard_session_id", "")).split()).strip()
        if not session_id:
            session_id = uuid4().hex[:16]
            self._state.set("agent_dashboard_session_id", session_id)

        created_at = " ".join(str(self._state.get("agent_dashboard_session_created_at", "")).split()).strip()
        if not created_at:
            created_at = self._utc_now_iso()
            self._state.set("agent_dashboard_session_created_at", created_at)

        planner_mode = str(self._state.get("agent_dashboard_planner_mode", "")).strip()
        if planner_mode not in self._PLANNER_MODES:
            planner_mode = "Local First (No LLM if possible)"

        session_entry: AgentDashboardSessionEntry = {
            "id": session_id,
            "created_at": created_at,
            "updated_at": self._utc_now_iso(),
            "title": self._derive_session_title(history=history, active_topic=active_topic),
            "planner_mode": planner_mode,
            "active_topic": active_topic,
            "recent_topics": self._json_safe_for_store(recent_topics),
            "pending_plan": self._json_safe_for_store(pending_plan),
            "history": self._json_safe_for_store(history),
        }
        self._session_store.upsert_session(session_entry)
        self._state.set("agent_dashboard_selected_saved_session_id", session_id)

    def update_session_topics(self, topic: str) -> None:
        clean_topic = " ".join(str(topic).split()).strip()
        if not self._is_valid_saved_topic(clean_topic):
            return

        self._state.set("agent_dashboard_active_topic", clean_topic)
        previous_raw = self._state.get("agent_dashboard_recent_topics", [])
        previous = previous_raw if isinstance(previous_raw, list) else []
        updated = [clean_topic] + [item for item in previous if str(item).strip().lower() != clean_topic.lower()]
        self._state.set("agent_dashboard_recent_topics", updated[:12])

    def _derive_session_title(self, *, history: list[dict[str, Any]], active_topic: str) -> str:
        if self._is_valid_saved_topic(active_topic):
            return active_topic

        for item in history:
            if not isinstance(item, dict):
                continue
            if str(item.get("role", "")).strip() != "user":
                continue
            text = " ".join(str(item.get("text", "")).split()).strip()
            if text:
                return text[:80]
        return "Agent Session"

    def _resolve_best_active_topic(
        self,
        *,
        active_topic: str,
        recent_topics: list[str],
        history: list[dict[str, Any]],
        title: str,
    ) -> str:
        if self._is_valid_saved_topic(active_topic) and not self._looks_like_asset_topic(active_topic):
            return " ".join(str(active_topic).split()).strip()

        history_topic = self._best_topic_from_history(history)
        if self._is_valid_saved_topic(history_topic):
            return " ".join(str(history_topic).split()).strip()

        for item in recent_topics:
            if self._is_valid_saved_topic(item) and not self._looks_like_asset_topic(item):
                return " ".join(str(item).split()).strip()

        for item in recent_topics:
            if self._is_valid_saved_topic(item):
                return " ".join(str(item).split()).strip()

        if self._is_valid_saved_topic(active_topic):
            return " ".join(str(active_topic).split()).strip()

        if self._is_valid_saved_topic(title):
            return " ".join(str(title).split()).strip()
        return ""

    def _best_topic_from_history(self, history: list[dict[str, Any]]) -> str:
        candidates: list[str] = []
        for item in history:
            if not isinstance(item, dict):
                continue
            payloads = item.get("payloads")
            if not isinstance(payloads, dict):
                continue
            for payload in payloads.values():
                if not isinstance(payload, dict):
                    continue
                topic = " ".join(str(payload.get("topic", "")).split()).strip()
                if self._is_valid_saved_topic(topic):
                    candidates.append(topic)

        if not candidates:
            return ""

        non_asset_candidates = [topic for topic in candidates if not self._looks_like_asset_topic(topic)]
        target_candidates = non_asset_candidates if non_asset_candidates else candidates

        score_by_topic: dict[str, tuple[int, int, str]] = {}
        for idx, topic in enumerate(target_candidates):
            normalized = " ".join(topic.lower().split()).strip()
            if not normalized:
                continue
            count, _, original = score_by_topic.get(normalized, (0, -1, topic))
            score_by_topic[normalized] = (count + 1, idx, original)

        if not score_by_topic:
            return ""

        best_normalized = max(score_by_topic, key=lambda key: (score_by_topic[key][0], score_by_topic[key][1]))
        return score_by_topic[best_normalized][2]

    @staticmethod
    def _is_valid_saved_topic(topic: str) -> bool:
        candidate = " ".join(str(topic).split()).strip()
        if not candidate:
            return False
        return IntentRouterService.is_valid_topic(candidate)

    @staticmethod
    def _looks_like_asset_topic(topic: str) -> bool:
        value = " ".join(str(topic).strip().lower().split())
        asset_like_labels = {
            "topic",
            "mindmap",
            "mind map",
            "flashcards",
            "flashcard",
            "data table",
            "datatable",
            "quiz",
            "slideshow",
            "slide show",
            "video",
            "audio overview",
            "audio_overview",
            "report",
            "detailed description",
        }
        return value in asset_like_labels

    @staticmethod
    def _json_safe_for_store(value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, bytes):
            return {"__agent_dashboard_bytes_b64__": b64encode(value).decode("ascii")}
        if isinstance(value, list):
            return [AgentDashboardSessionManager._json_safe_for_store(item) for item in value]
        if isinstance(value, tuple):
            return [AgentDashboardSessionManager._json_safe_for_store(item) for item in value]
        if isinstance(value, dict):
            return {str(key): AgentDashboardSessionManager._json_safe_for_store(item) for key, item in value.items()}
        return str(value)

    @staticmethod
    def _json_restore_from_store(value: Any) -> Any:
        if isinstance(value, dict):
            if set(value.keys()) == {"__agent_dashboard_bytes_b64__"}:
                encoded = value.get("__agent_dashboard_bytes_b64__")
                if isinstance(encoded, str):
                    try:
                        return b64decode(encoded.encode("ascii"))
                    except (UnicodeEncodeError, ValueError, binascii.Error):
                        return b""
                return b""
            return {str(key): AgentDashboardSessionManager._json_restore_from_store(item) for key, item in value.items()}
        if isinstance(value, list):
            return [AgentDashboardSessionManager._json_restore_from_store(item) for item in value]
        return value

    @staticmethod
    def _utc_now_iso() -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
