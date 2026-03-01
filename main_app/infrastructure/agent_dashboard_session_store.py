from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol, cast

from main_app.contracts import (
    AgentDashboardSessionEntry,
    AgentDashboardSessionStorePayload,
)
from main_app.infrastructure.mongo_base import MongoCollectionConfig, MongoCollectionProvider


def _as_session_entry(value: object) -> AgentDashboardSessionEntry | None:
    if not isinstance(value, dict):
        return None
    return cast(AgentDashboardSessionEntry, value)


class AgentDashboardSessionRepository(Protocol):
    def list_sessions(self) -> list[AgentDashboardSessionEntry]:
        ...

    def get_session(self, session_id: str) -> AgentDashboardSessionEntry | None:
        ...

    def upsert_session(self, session_entry: AgentDashboardSessionEntry) -> None:
        ...

    def delete_session(self, session_id: str) -> None:
        ...

    def save_sessions(self, sessions: list[AgentDashboardSessionEntry]) -> None:
        ...


class AgentDashboardSessionStore:
    def __init__(self, storage_file: Path) -> None:
        self._storage_file = storage_file

    def list_sessions(self) -> list[AgentDashboardSessionEntry]:
        data = self._load_data()
        sessions = data.get("sessions", [])
        if not isinstance(sessions, list):
            return []
        normalized: list[AgentDashboardSessionEntry] = []
        for item in sessions:
            parsed = _as_session_entry(item)
            if parsed is not None:
                normalized.append(parsed)
        return sorted(
            normalized,
            key=lambda item: str(item.get("updated_at", item.get("created_at", ""))),
            reverse=True,
        )

    def get_session(self, session_id: str) -> AgentDashboardSessionEntry | None:
        target = str(session_id).strip()
        if not target:
            return None
        for item in self.list_sessions():
            if str(item.get("id", "")).strip() == target:
                return item
        return None

    def upsert_session(self, session_entry: AgentDashboardSessionEntry) -> None:
        session_id = str(session_entry.get("id", "")).strip()
        if not session_id:
            return

        sessions = self.list_sessions()
        replaced = False
        for idx, item in enumerate(sessions):
            if str(item.get("id", "")).strip() == session_id:
                created_at = " ".join(str(item.get("created_at", "")).split()).strip()
                if "created_at" not in session_entry and created_at:
                    session_entry["created_at"] = created_at
                sessions[idx] = session_entry
                replaced = True
                break

        if not replaced:
            sessions.append(session_entry)

        self.save_sessions(sessions)

    def delete_session(self, session_id: str) -> None:
        target = str(session_id).strip()
        if not target:
            return
        sessions = [item for item in self.list_sessions() if str(item.get("id", "")).strip() != target]
        self.save_sessions(sessions)

    def save_sessions(self, sessions: list[AgentDashboardSessionEntry]) -> None:
        payload: AgentDashboardSessionStorePayload = {"sessions": sessions}
        self._storage_file.parent.mkdir(parents=True, exist_ok=True)
        self._storage_file.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_data(self) -> AgentDashboardSessionStorePayload:
        if not self._storage_file.exists():
            return {"sessions": []}
        try:
            payload = json.loads(self._storage_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {"sessions": []}
        if not isinstance(payload, dict):
            return {"sessions": []}
        sessions = payload.get("sessions", [])
        if not isinstance(sessions, list):
            return {"sessions": []}
        normalized: list[AgentDashboardSessionEntry] = []
        for item in sessions:
            parsed = _as_session_entry(item)
            if parsed is not None:
                normalized.append(parsed)
        return {"sessions": normalized}


class MongoAgentDashboardSessionStore:
    def __init__(
        self,
        *,
        uri: str,
        db_name: str,
        collection_name: str = "agent_dashboard_sessions",
    ) -> None:
        self._provider = MongoCollectionProvider(
            MongoCollectionConfig(
                uri=uri,
                db_name=db_name,
                collection_name=collection_name,
            )
        )

    @property
    def description(self) -> str:
        return self._provider.description

    def list_sessions(self) -> list[AgentDashboardSessionEntry]:
        collection = self._provider.collection()
        sessions: list[AgentDashboardSessionEntry] = []
        for item in collection.find({}, {"_id": 0, "session_entry": 1}).sort("updated_sort", -1):
            session_entry = item.get("session_entry")
            parsed = _as_session_entry(session_entry)
            if parsed is not None:
                sessions.append(parsed)
        return sessions

    def get_session(self, session_id: str) -> AgentDashboardSessionEntry | None:
        target = str(session_id).strip()
        if not target:
            return None
        collection = self._provider.collection()
        item = collection.find_one({"_id": target}, {"_id": 0, "session_entry": 1})
        session_entry = item.get("session_entry") if isinstance(item, dict) else None
        return _as_session_entry(session_entry)

    def upsert_session(self, session_entry: AgentDashboardSessionEntry) -> None:
        session_id = str(session_entry.get("id", "")).strip()
        if not session_id:
            return

        collection = self._provider.collection()
        existing = collection.find_one({"_id": session_id}, {"_id": 0, "session_entry": 1})
        existing_entry = existing.get("session_entry") if isinstance(existing, dict) else None
        if isinstance(existing_entry, dict) and "created_at" not in session_entry:
            created_at = " ".join(str(existing_entry.get("created_at", "")).split()).strip()
            if created_at:
                session_entry = cast(AgentDashboardSessionEntry, dict(session_entry))
                session_entry["created_at"] = created_at

        updated_sort = str(session_entry.get("updated_at", session_entry.get("created_at", "")))
        collection.replace_one(
            {"_id": session_id},
            {
                "_id": session_id,
                "updated_sort": updated_sort,
                "session_entry": dict(session_entry),
            },
            upsert=True,
        )

    def delete_session(self, session_id: str) -> None:
        target = str(session_id).strip()
        if not target:
            return
        collection = self._provider.collection()
        collection.delete_one({"_id": target})

    def save_sessions(self, sessions: list[AgentDashboardSessionEntry]) -> None:
        collection = self._provider.collection()
        collection.delete_many({})
        documents: list[dict[str, object]] = []
        for session in sessions:
            if not isinstance(session, dict):
                continue
            session_id = str(session.get("id", "")).strip()
            if not session_id:
                continue
            documents.append(
                {
                    "_id": session_id,
                    "updated_sort": str(session.get("updated_at", session.get("created_at", ""))),
                    "session_entry": dict(session),
                }
            )
        if documents:
            collection.insert_many(documents, ordered=False)
