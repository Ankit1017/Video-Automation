from __future__ import annotations

import re
from typing import Any, Callable


FieldExtractor = Callable[[str, str], Any | None]


class IntentRouterTextUtils:
    def __init__(self) -> None:
        self._field_extractors: dict[str, FieldExtractor] | None = None
        self._custom_field_extractors: dict[str, FieldExtractor] = {}

    @staticmethod
    def clean_text(value: Any) -> str:
        return " ".join(str(value).split()).strip()

    @classmethod
    def is_valid_topic(cls, topic: str) -> bool:
        candidate = cls.clean_text(topic)
        if not candidate:
            return False
        return not cls.is_invalid_topic_candidate(candidate)

    @classmethod
    def is_followup_reference_message(cls, message: str) -> bool:
        text = " ".join(str(message).strip().lower().split())
        if not text:
            return False

        if cls.contains_reference_pronoun(text):
            return True

        explicit_markers = ["about ", " on ", " for ", "topic is", "topic:"]
        if any(marker in f" {text} " for marker in explicit_markers):
            return False

        return False

    @classmethod
    def fallback_topic_from_message(cls, message: str) -> str:
        text = str(message).strip()
        if not text:
            return ""

        quoted = re.search(r"\"([^\"]{3,120})\"|'([^']{3,120})'", text)
        if quoted:
            candidate = cls.clean_topic_candidate(quoted.group(1) or quoted.group(2) or "")
            if candidate and not cls.is_invalid_topic_candidate(candidate):
                return candidate
            return ""

        patterns = [
            r"\babout\s+([A-Za-z0-9][^,.!?]{2,120})",
            r"\bon\s+([A-Za-z0-9][^,.!?]{2,120})",
            r"\bfor\s+([A-Za-z0-9][^,.!?]{2,120})",
            r"\btopic\s*(?:is|:)\s*([A-Za-z0-9][^,.!?]{2,120})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            candidate = cls.clean_topic_candidate(match.group(1) or "")
            if len(candidate) >= 3 and not cls.is_invalid_topic_candidate(candidate):
                return candidate
        return ""

    @staticmethod
    def clean_topic_candidate(raw_value: str) -> str:
        candidate = " ".join(str(raw_value).split()).strip()
        if not candidate:
            return ""

        candidate = re.split(r"\b(and|with|plus|then|while|where)\b", candidate, maxsplit=1, flags=re.IGNORECASE)[0].strip()
        candidate = re.sub(r"\s+", " ", candidate)
        candidate = re.sub(
            r"\b(in detail|in-depth|in depth|deeply|properly|clearly|briefly|quickly|please)\b\.?\s*$",
            "",
            candidate,
            flags=re.IGNORECASE,
        ).strip(" .,:;")
        return " ".join(candidate.split()).strip()

    @staticmethod
    def is_invalid_topic_candidate(candidate: str) -> bool:
        value = " ".join(str(candidate).strip().lower().split())
        if not value:
            return True

        exact_invalid = {
            "it",
            "this",
            "that",
            "same",
            "same topic",
            "same one",
            "previous",
            "previous topic",
            "above",
            "above topic",
            "it please",
            "this please",
            "that please",
            "topic",
            "topic name",
            "global topic",
            "empty string",
            "clean topic",
            "global topic if present else empty string",
            "clean topic or empty string",
            "topic for this intent if present",
            "mindmap",
            "mind map",
            "flashcards",
            "data table",
            "quiz",
            "slideshow",
            "slide show",
            "video",
            "audio overview",
            "audio_overview",
            "report",
        }
        if value in exact_invalid:
            return True

        placeholder_markers = {
            "if present",
            "empty string",
            "return json",
            "schema",
            "<intent>",
            "<optional_field>",
            "or empty string",
        }
        if any(marker in value for marker in placeholder_markers):
            return True

        tokens = value.split()
        pronoun_heads = {"it", "this", "that", "same", "previous", "above"}
        filler = {"please", "properly", "deeply", "clearly", "briefly", "quickly", "well"}
        if tokens and tokens[0] in pronoun_heads and len(tokens) <= 4:
            if all(token in pronoun_heads.union(filler).union({"topic", "one"}) for token in tokens):
                return True

        return False

    @staticmethod
    def contains_reference_pronoun(text: str) -> bool:
        normalized = f" {text.strip().lower()} "
        markers = [
            " it ",
            " this ",
            " that ",
            " same ",
            " previous ",
            " above ",
            " same topic ",
            " same one ",
            " previous topic ",
        ]
        return any(marker in normalized for marker in markers)

    @staticmethod
    def extract_constraint_text_from_message(message: str) -> str:
        text = " ".join(str(message).split()).strip()
        if not text:
            return ""

        patterns = [
            r"\badditional instructions?\b\s*(?:is|are|:|-)?\s*(.+)$",
            r"\badditional instruction\b\s*(?:is|are|:|-)?\s*(.+)$",
            r"\bconstraints?\b\s*(?:is|are|:|-)?\s*(.+)$",
            r"\bnotes?\b\s*(?:is|are|:|-)?\s*(.+)$",
            r"\bkeep it\b\s+(.+)$",
            r"\bfocus on\b\s+(.+)$",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            value = " ".join((match.group(1) or "").split()).strip(" .")
            value = re.sub(r"^(that|to)\s+", "", value, flags=re.IGNORECASE).strip()
            if value:
                return value
        return ""

    def extract_field_from_message(
        self,
        *,
        message: str,
        field_name: str,
    ) -> Any | None:
        text = " ".join(str(message).split())
        lower = text.lower()
        extractor = self._field_extractor_map().get(str(field_name).strip())
        if extractor:
            return extractor(text, lower)
        return None

    def register_field_extractor(self, field_name: str, extractor: FieldExtractor) -> None:
        normalized_name = str(field_name).strip()
        if not normalized_name:
            return
        self._custom_field_extractors[normalized_name] = extractor

    def _field_extractor_map(self) -> dict[str, FieldExtractor]:
        extractors = dict(self._default_field_extractors())
        extractors.update(self._custom_field_extractors)
        return extractors

    def _default_field_extractors(self) -> dict[str, FieldExtractor]:
        if self._field_extractors is not None:
            return self._field_extractors

        extractors: dict[str, FieldExtractor] = {}
        int_patterns: dict[str, list[str]] = {
            "question_count": [r"(\d+)\s*(?:questions?|mcqs?)"],
            "card_count": [r"(\d+)\s*(?:flashcards?|cards?)"],
            "row_count": [r"(\d+)\s*rows?"],
            "subtopic_count": [r"(\d+)\s*subtopics?"],
            "slides_per_subtopic": [
                r"(\d+)\s*slides?\s*(?:per|/)\s*subtopic",
                r"(\d+)\s*slides?\s*each subtopic",
            ],
            "max_depth": [r"(?:max\s*depth|depth)\s*(?:of|=|:)?\s*(\d+)"],
            "speaker_count": [r"(\d+)\s*(?:speakers?|voices?|hosts?|persons?|people)"],
            "turn_count": [r"(\d+)\s*(?:dialogue\s*turns?|turns?)"],
        }
        for field_name, patterns in int_patterns.items():
            extractors[field_name] = self._build_int_extractor(patterns)

        extractors["difficulty"] = lambda _text, lower: self._extract_difficulty(lower)
        extractors["format_key"] = lambda _text, lower: self._extract_format_key(lower)
        extractors["code_mode"] = lambda _text, lower: self._extract_code_mode(lower)
        extractors["conversation_style"] = lambda _text, lower: self._extract_conversation_style(lower)
        extractors["language"] = lambda _text, lower: self._extract_language(lower)
        extractors["slow_audio"] = lambda _text, lower: self._extract_slow_audio(lower)
        for field_name in {"constraints", "notes", "additional_notes", "additional_instructions"}:
            extractors[field_name] = lambda text, _lower: self.extract_constraint_text_from_message(text)

        self._field_extractors = extractors
        return self._field_extractors

    def _build_int_extractor(self, patterns: list[str]) -> FieldExtractor:
        def _extractor(_text: str, lower: str) -> Any | None:
            return self.extract_first_int(lower, patterns)

        return _extractor

    @staticmethod
    def _extract_difficulty(lower: str) -> str | None:
        if "beginner" in lower:
            return "Beginner"
        if "advanced" in lower:
            return "Advanced"
        if "intermediate" in lower:
            return "Intermediate"
        return None

    @staticmethod
    def _extract_format_key(lower: str) -> str | None:
        if "study guide" in lower:
            return "study_guide"
        if "blog post" in lower or "blog" in lower:
            return "blog_post"
        if "briefing" in lower:
            return "briefing_doc"
        return None

    @staticmethod
    def _extract_code_mode(lower: str) -> str | None:
        if any(token in lower for token in ["without code", "no code", "exclude code"]):
            return "none"
        if any(token in lower for token in ["with code", "code examples", "include code", "show code"]):
            return "force"
        return None

    @staticmethod
    def _extract_conversation_style(lower: str) -> str | None:
        if "interview" in lower:
            return "Interview"
        if "roundtable" in lower:
            return "Roundtable"
        if "debate" in lower:
            return "Debate"
        if "discussion" in lower:
            return "Educational Discussion"
        return None

    @staticmethod
    def _extract_language(lower: str) -> str | None:
        if any(token in lower for token in [" hindi", "in hindi", "language hi"]):
            return "hi"
        if any(token in lower for token in [" spanish", "in spanish", "language es"]):
            return "es"
        if any(token in lower for token in [" french", "in french", "language fr"]):
            return "fr"
        if any(token in lower for token in [" german", "in german", "language de"]):
            return "de"
        if any(token in lower for token in [" japanese", "in japanese", "language ja"]):
            return "ja"
        if any(token in lower for token in [" english", "in english", "language en"]):
            return "en"
        return None

    @staticmethod
    def _extract_slow_audio(lower: str) -> bool | None:
        if any(token in lower for token in ["slow narration", "speak slowly", "slow voice", "slow audio"]):
            return True
        if any(token in lower for token in ["fast narration", "normal speed", "quick voice"]):
            return False
        return None

    @staticmethod
    def extract_first_int(text: str, patterns: list[str]) -> int | None:
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                try:
                    return int(match.group(1))
                except (TypeError, ValueError):
                    continue
        return None
