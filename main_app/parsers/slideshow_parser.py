from __future__ import annotations

import json
import re
from typing import Any, Callable

from main_app.shared.slideshow.representation_normalizer import normalize_slide_representation
from main_app.models import GroqSettings
from main_app.parsers.json_utils import extract_json_text, repair_json_text_locally
from main_app.services.cached_llm_service import CachedLLMService


class SlideShowParser:
    def __init__(self, llm_service: CachedLLMService) -> None:
        self._llm_service = llm_service

    def parse_outline(
        self,
        raw_text: str,
        *,
        max_subtopics: int,
        settings: GroqSettings,
    ) -> tuple[dict[str, Any] | None, str | None, str | None]:
        return self._parse_json_with_repair(
            raw_text,
            settings=settings,
            repair_task="slideshow_outline_json_repair",
            repair_label="SlideShow Outline JSON Repair",
            repair_topic="slideshow_outline_json_repair",
            normalizer=lambda parsed: self._normalize_outline(parsed, max_subtopics=max_subtopics),
            parse_error_prefix="Could not parse slideshow outline JSON",
            local_repair_note="Slide outline JSON had minor syntax issues and was auto-repaired locally.",
            llm_repair_note="Slide outline JSON was repaired using LLM.",
        )

    def parse_section_slides(
        self,
        raw_text: str,
        *,
        max_slides: int,
        settings: GroqSettings,
    ) -> tuple[list[dict[str, Any]] | None, str | None, str | None]:
        return self._parse_json_with_repair(
            raw_text,
            settings=settings,
            repair_task="slideshow_section_json_repair",
            repair_label="SlideShow Section JSON Repair",
            repair_topic="slideshow_section_json_repair",
            normalizer=lambda parsed: self._normalize_section_slides(parsed, max_slides=max_slides),
            parse_error_prefix="Could not parse slideshow section JSON",
            local_repair_note="Slide section JSON had minor syntax issues and was auto-repaired locally.",
            llm_repair_note="Slide section JSON was repaired using LLM.",
            partial_recovery=lambda text: self._recover_partial_section_slides(
                candidate_text=text,
                max_slides=max_slides,
            ),
        )

    def _parse_json_with_repair(
        self,
        raw_text: str,
        *,
        settings: GroqSettings,
        repair_task: str,
        repair_label: str,
        repair_topic: str,
        normalizer,
        parse_error_prefix: str,
        local_repair_note: str,
        llm_repair_note: str,
        partial_recovery: Callable[[str], tuple[Any | None, str | None]] | None = None,
    ) -> tuple[Any, str | None, str | None]:
        json_text = extract_json_text(raw_text)
        if not json_text:
            if partial_recovery is not None:
                recovered, recovery_note = partial_recovery(raw_text)
                if recovered is not None:
                    return recovered, None, recovery_note
            return None, "Model response did not contain JSON.", None

        parse_errors: list[str] = []
        llm_json_text: str | None = None

        try:
            parsed = json.loads(json_text)
            normalized, schema_error, normalize_note = self._unpack_normalizer_result(normalizer(parsed))
            if schema_error:
                return None, schema_error, None
            return normalized, None, normalize_note
        except json.JSONDecodeError as exc:
            parse_errors.append(f"original parse: {exc}")

        locally_repaired_json = repair_json_text_locally(json_text)
        if locally_repaired_json != json_text:
            try:
                parsed = json.loads(locally_repaired_json)
                normalized, schema_error, normalize_note = self._unpack_normalizer_result(normalizer(parsed))
                if schema_error:
                    return None, schema_error, None
                return normalized, None, self._merge_parse_notes(local_repair_note, normalize_note)
            except json.JSONDecodeError as exc:
                parse_errors.append(f"local repair parse: {exc}")

        if settings.has_api_key() and settings.has_model():
            try:
                repair_seed = locally_repaired_json if locally_repaired_json != json_text else json_text
                llm_repaired_text, repair_cache_hit = self._repair_json_with_llm(
                    raw_json_text=repair_seed,
                    settings=settings,
                    task=repair_task,
                    label=repair_label,
                    topic=repair_topic,
                )
                llm_json_text = extract_json_text(llm_repaired_text) or llm_repaired_text
                try:
                    parsed = json.loads(llm_json_text)
                    normalized, schema_error, normalize_note = self._unpack_normalizer_result(normalizer(parsed))
                    if schema_error:
                        return None, schema_error, None
                    note = llm_repair_note
                    if repair_cache_hit:
                        note += " Repair result was served from cache."
                    return normalized, None, self._merge_parse_notes(note, normalize_note)
                except json.JSONDecodeError:
                    final_local_repair = repair_json_text_locally(llm_json_text)
                    parsed = json.loads(final_local_repair)
                    normalized, schema_error, normalize_note = self._unpack_normalizer_result(normalizer(parsed))
                    if schema_error:
                        return None, schema_error, None
                    note = llm_repair_note + " Output needed final local sanitization."
                    if repair_cache_hit:
                        note += " Repair result was served from cache."
                    return normalized, None, self._merge_parse_notes(note, normalize_note)
            except (
                AttributeError,
                OSError,
                RuntimeError,
                TypeError,
                ValueError,
                json.JSONDecodeError,
            ) as exc:
                parse_errors.append(f"LLM repair parse: {exc}")

        if partial_recovery is not None:
            for candidate in [raw_text, json_text, locally_repaired_json, llm_json_text or ""]:
                recovered, recovery_note = partial_recovery(candidate)
                if recovered is not None:
                    return recovered, None, recovery_note

        return None, f"{parse_error_prefix}: " + " | ".join(parse_errors), None

    def _recover_partial_section_slides(
        self,
        *,
        candidate_text: str,
        max_slides: int,
    ) -> tuple[list[dict[str, Any]] | None, str | None]:
        if not candidate_text:
            return None, None

        text = str(candidate_text)
        fenced_match = re.search(r"```(?:json)?\s*([\s\S]*?)$", text, flags=re.IGNORECASE)
        if fenced_match:
            text = fenced_match.group(1)

        slides_anchor = text.find('"slides"')
        array_start = text.find("[", slides_anchor if slides_anchor != -1 else 0)
        if array_start == -1:
            return None, None

        recovered_items: list[dict[str, Any]] = []
        idx = array_start + 1
        total_len = len(text)
        while idx < total_len and len(recovered_items) < max_slides:
            while idx < total_len and text[idx] not in "{]":
                idx += 1
            if idx >= total_len or text[idx] == "]":
                break

            obj_start = idx
            depth = 0
            in_string = False
            escape_next = False
            j = idx
            object_closed = False

            while j < total_len:
                ch = text[j]
                if in_string:
                    if escape_next:
                        escape_next = False
                    elif ch == "\\":
                        escape_next = True
                    elif ch == '"':
                        in_string = False
                else:
                    if ch == '"':
                        in_string = True
                    elif ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            object_closed = True
                            break
                j += 1

            if not object_closed:
                break

            object_text = text[obj_start : j + 1]
            try:
                parsed_item = json.loads(object_text)
            except json.JSONDecodeError:
                repaired_item = repair_json_text_locally(object_text)
                try:
                    parsed_item = json.loads(repaired_item)
                except json.JSONDecodeError:
                    idx = j + 1
                    continue

            if isinstance(parsed_item, dict):
                recovered_items.append(parsed_item)

            idx = j + 1

        if not recovered_items:
            return None, None

        normalized, schema_error, normalize_note = self._normalize_section_slides(
            {"slides": recovered_items},
            max_slides=max_slides,
        )
        if schema_error:
            return None, None

        normalized_count = len(normalized) if isinstance(normalized, list) else 0
        recovery_note = (
            f"Section JSON was truncated; recovered {normalized_count} complete slide(s) "
            "from partial model output."
        )
        note = self._merge_parse_notes(recovery_note, normalize_note)
        return normalized, note

    def _repair_json_with_llm(
        self,
        *,
        raw_json_text: str,
        settings: GroqSettings,
        task: str,
        label: str,
        topic: str,
    ) -> tuple[str, bool]:
        repair_system_prompt = (
            "You repair malformed JSON. "
            "Return strictly valid JSON only. Do not explain, do not add markdown."
        )
        repair_user_prompt = (
            "The following JSON is invalid. Repair it while preserving structure and meaning.\n\n"
            f"{raw_json_text}"
        )
        repair_messages = [
            {"role": "system", "content": repair_system_prompt},
            {"role": "user", "content": repair_user_prompt},
        ]

        return self._llm_service.call(
            settings=settings,
            messages=repair_messages,
            task=task,
            label=label,
            topic=topic,
            temperature_override=0.0,
            max_tokens_override=min(int(settings.max_tokens), 2048),
        )

    def _normalize_outline(
        self,
        parsed: Any,
        *,
        max_subtopics: int,
    ) -> tuple[dict[str, Any] | None, str | None]:
        if isinstance(parsed, dict):
            raw_topic = str(parsed.get("topic", "")).strip()
            raw_subtopics = parsed.get("subtopics") or parsed.get("outline")
        elif isinstance(parsed, list):
            raw_topic = ""
            raw_subtopics = parsed
        else:
            return None, "Outline JSON must be an object with `subtopics` list."

        if not isinstance(raw_subtopics, list):
            return None, "Outline JSON missing `subtopics` list."

        subtopics: list[dict[str, str]] = []
        for item in raw_subtopics:
            if isinstance(item, str):
                normalized_title = " ".join(item.split()).strip()
                if normalized_title:
                    subtopics.append({"title": normalized_title, "focus": ""})
            elif isinstance(item, dict):
                raw_title = item.get("title") or item.get("name") or item.get("subtopic")
                raw_focus = item.get("focus") or item.get("goal") or item.get("description") or ""
                title_text = " ".join(str(raw_title).split()).strip() if raw_title is not None else ""
                focus_text = " ".join(str(raw_focus).split()).strip() if raw_focus is not None else ""
                if title_text:
                    subtopics.append({"title": title_text, "focus": focus_text})

        if len(subtopics) < 2:
            return None, "Need at least 2 valid subtopics for slide outline."

        return {
            "topic": raw_topic,
            "subtopics": subtopics[:max_subtopics],
        }, None

    def _normalize_section_slides(
        self,
        parsed: Any,
        *,
        max_slides: int,
    ) -> tuple[list[dict[str, Any]] | None, str | None, str | None]:
        if isinstance(parsed, dict):
            raw_slides = parsed.get("slides")
        elif isinstance(parsed, list):
            raw_slides = parsed
        else:
            return None, "Section JSON must be an object with `slides` list or a direct slide list.", None

        if not isinstance(raw_slides, list):
            return None, "Section JSON missing `slides` list.", None

        normalized_slides: list[dict[str, Any]] = []
        normalization_notes: list[str] = []
        for item in raw_slides:
            if not isinstance(item, dict):
                continue

            raw_title = item.get("title") or item.get("heading")
            if raw_title is None:
                continue
            title = " ".join(str(raw_title).split()).strip()
            if not title:
                continue

            raw_bullets = item.get("bullets") or item.get("points") or []
            bullets: list[str] = []
            inferred_code_snippet = ""
            inferred_code_language = ""
            if isinstance(raw_bullets, list):
                for bullet in raw_bullets:
                    bullet_raw_text = str(bullet)
                    bullet_without_code, code_from_bullet, language_from_bullet = self._extract_markdown_code_block(
                        bullet_raw_text
                    )
                    if code_from_bullet and not inferred_code_snippet:
                        inferred_code_snippet = code_from_bullet
                        inferred_code_language = language_from_bullet

                    bullet_text = " ".join(bullet_without_code.split()).strip()
                    if bullet_text:
                        bullets.append(bullet_text)

            notes = item.get("speaker_notes") or item.get("notes") or ""
            notes_text = " ".join(str(notes).split()).strip()
            code_snippet = self._normalize_code_snippet(
                item.get("code_snippet") or item.get("code") or item.get("snippet") or inferred_code_snippet
            )
            code_language = " ".join(
                str(item.get("code_language") or item.get("language") or item.get("lang") or inferred_code_language).split()
            ).strip()
            candidate_slide = {
                "title": title,
                "representation": item.get("representation", "bullet"),
                "layout_payload": item.get("layout_payload", {}),
                "bullets": bullets[:6],
                "speaker_notes": notes_text,
                "code_snippet": code_snippet,
                "code_language": code_language,
            }
            normalized_slide, note = normalize_slide_representation(candidate_slide)
            normalized_bullets = normalized_slide.get("bullets", [])
            bullet_count = len(normalized_bullets) if isinstance(normalized_bullets, list) else 0
            if code_snippet and bullet_count < 1:
                normalized_slide["bullets"] = ["Implementation walkthrough using the code example on this slide."]
                bullet_count = 1
            if bullet_count < (1 if code_snippet else 2):
                continue
            if note:
                normalization_notes.append(f"{title}: {note}")
            normalized_slides.append(normalized_slide)

        if not normalized_slides:
            return None, "No valid slides found for section.", None

        parse_note = self._join_notes(normalization_notes)
        return normalized_slides[:max_slides], None, parse_note

    @staticmethod
    def _normalize_code_snippet(raw_code: Any) -> str:
        if raw_code is None:
            return ""
        if isinstance(raw_code, list):
            lines = [str(line).rstrip() for line in raw_code if str(line).strip()]
            return "\n".join(lines).strip()
        if isinstance(raw_code, dict):
            return ""
        raw_text = str(raw_code).strip()
        _, extracted_code, _ = SlideShowParser._extract_markdown_code_block(raw_text)
        return extracted_code if extracted_code else raw_text

    @staticmethod
    def _extract_markdown_code_block(text: str) -> tuple[str, str, str]:
        pattern = r"```([a-zA-Z0-9_+.-]*)\s*([\s\S]*?)```"
        match = re.search(pattern, text)
        if not match:
            return text, "", ""

        language = (match.group(1) or "").strip().lower()
        code = (match.group(2) or "").strip("\n").rstrip()
        cleaned = re.sub(pattern, "", text).strip()
        return cleaned, code, language

    @staticmethod
    def _join_notes(notes: list[str]) -> str | None:
        cleaned = [" ".join(str(note).split()).strip() for note in notes if str(note).strip()]
        if not cleaned:
            return None
        unique: list[str] = []
        for note in cleaned:
            if note not in unique:
                unique.append(note)
        return "; ".join(unique[:4])

    @staticmethod
    def _merge_parse_notes(base_note: str | None, extra_note: str | None) -> str | None:
        parts = []
        if base_note and str(base_note).strip():
            parts.append(" ".join(str(base_note).split()).strip())
        if extra_note and str(extra_note).strip():
            parts.append(" ".join(str(extra_note).split()).strip())
        if not parts:
            return None
        deduped: list[str] = []
        for part in parts:
            if part not in deduped:
                deduped.append(part)
        return " ".join(deduped)

    @staticmethod
    def _unpack_normalizer_result(result: Any) -> tuple[Any, str | None, str | None]:
        if isinstance(result, tuple):
            if len(result) == 3:
                return result[0], result[1], result[2]
            if len(result) == 2:
                return result[0], result[1], None
        return result, None, None
