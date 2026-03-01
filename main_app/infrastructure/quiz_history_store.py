from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol, cast

from main_app.contracts import QuizHistoryEntry, QuizHistoryStorePayload
from main_app.infrastructure.mongo_base import MongoCollectionConfig, MongoCollectionProvider


def _as_quiz_entry(value: object) -> QuizHistoryEntry | None:
    if not isinstance(value, dict):
        return None
    return cast(QuizHistoryEntry, value)


class QuizHistoryRepository(Protocol):
    def list_quizzes(self) -> list[QuizHistoryEntry]:
        ...

    def save_quizzes(self, quizzes: list[QuizHistoryEntry]) -> None:
        ...

    def get_quiz(self, quiz_id: str) -> QuizHistoryEntry | None:
        ...

    def upsert_quiz(self, quiz_entry: QuizHistoryEntry) -> None:
        ...


class QuizHistoryStore:
    def __init__(self, storage_file: Path) -> None:
        self._storage_file = storage_file

    def list_quizzes(self) -> list[QuizHistoryEntry]:
        data = self._load_data()
        quizzes = data.get("quizzes", [])
        if not isinstance(quizzes, list):
            return []
        normalized: list[QuizHistoryEntry] = []
        for item in quizzes:
            parsed = _as_quiz_entry(item)
            if parsed is not None:
                normalized.append(parsed)
        return normalized

    def save_quizzes(self, quizzes: list[QuizHistoryEntry]) -> None:
        payload: QuizHistoryStorePayload = {"quizzes": quizzes}
        self._storage_file.parent.mkdir(parents=True, exist_ok=True)
        self._storage_file.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get_quiz(self, quiz_id: str) -> QuizHistoryEntry | None:
        for item in self.list_quizzes():
            if str(item.get("id", "")) == quiz_id:
                return item
        return None

    def upsert_quiz(self, quiz_entry: QuizHistoryEntry) -> None:
        quiz_id = str(quiz_entry.get("id", "")).strip()
        if not quiz_id:
            return

        quizzes = self.list_quizzes()
        replaced = False
        for idx, item in enumerate(quizzes):
            if str(item.get("id", "")) == quiz_id:
                quizzes[idx] = quiz_entry
                replaced = True
                break

        if not replaced:
            quizzes.append(quiz_entry)

        self.save_quizzes(quizzes)

    def _load_data(self) -> QuizHistoryStorePayload:
        if not self._storage_file.exists():
            return {"quizzes": []}
        try:
            payload = json.loads(self._storage_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {"quizzes": []}
        if not isinstance(payload, dict):
            return {"quizzes": []}
        quizzes = payload.get("quizzes", [])
        if not isinstance(quizzes, list):
            return {"quizzes": []}
        normalized: list[QuizHistoryEntry] = []
        for item in quizzes:
            parsed = _as_quiz_entry(item)
            if parsed is not None:
                normalized.append(parsed)
        return {"quizzes": normalized}


class MongoQuizHistoryStore:
    def __init__(
        self,
        *,
        uri: str,
        db_name: str,
        collection_name: str = "quiz_history",
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

    def list_quizzes(self) -> list[QuizHistoryEntry]:
        collection = self._provider.collection()
        quizzes: list[QuizHistoryEntry] = []
        for item in collection.find({}, {"_id": 0, "quiz_entry": 1}):
            quiz_entry = item.get("quiz_entry")
            parsed = _as_quiz_entry(quiz_entry)
            if parsed is not None:
                quizzes.append(parsed)
        return quizzes

    def save_quizzes(self, quizzes: list[QuizHistoryEntry]) -> None:
        collection = self._provider.collection()
        collection.delete_many({})
        documents: list[dict[str, object]] = []
        for quiz in quizzes:
            if not isinstance(quiz, dict):
                continue
            quiz_id = str(quiz.get("id", "")).strip()
            if not quiz_id:
                continue
            documents.append({"_id": quiz_id, "quiz_entry": dict(quiz)})
        if documents:
            collection.insert_many(documents, ordered=False)

    def get_quiz(self, quiz_id: str) -> QuizHistoryEntry | None:
        target = str(quiz_id).strip()
        if not target:
            return None
        collection = self._provider.collection()
        item = collection.find_one({"_id": target}, {"_id": 0, "quiz_entry": 1})
        quiz_entry = item.get("quiz_entry") if isinstance(item, dict) else None
        return _as_quiz_entry(quiz_entry)

    def upsert_quiz(self, quiz_entry: QuizHistoryEntry) -> None:
        quiz_id = str(quiz_entry.get("id", "")).strip()
        if not quiz_id:
            return
        collection = self._provider.collection()
        collection.replace_one(
            {"_id": quiz_id},
            {"_id": quiz_id, "quiz_entry": dict(quiz_entry)},
            upsert=True,
        )
