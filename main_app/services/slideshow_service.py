from __future__ import annotations

from typing import Any, Literal

from main_app.shared.slideshow.representation_normalizer import (
    normalize_representation_mode,
    normalize_slide_representation,
)
from main_app.models import GroqSettings, SlideShowGenerationResult
from main_app.parsers.slideshow_parser import SlideShowParser
from main_app.services.asset_history_service import AssetHistoryService
from main_app.services.cached_llm_service import CachedLLMService
from main_app.services.text_sanitizer import sanitize_text


class SlideShowService:
    def __init__(
        self,
        llm_service: CachedLLMService,
        parser: SlideShowParser,
        history_service: AssetHistoryService | None = None,
    ) -> None:
        self._llm_service = llm_service
        self._parser = parser
        self._history_service = history_service

    def generate(
        self,
        *,
        topic: str,
        constraints: str,
        subtopic_count: int,
        slides_per_subtopic: int,
        code_mode: Literal["auto", "force", "none"] = "auto",
        representation_mode: str = "auto",
        grounding_context: str = "",
        source_manifest: list[dict[str, Any]] | None = None,
        require_citations: bool = False,
        grounding_metadata: dict[str, Any] | None = None,
        settings: GroqSettings,
        record_history: bool = True,
    ) -> SlideShowGenerationResult:
        subtopic_count = max(2, min(int(subtopic_count), 10))
        slides_per_subtopic = max(1, min(int(slides_per_subtopic), 3))
        normalized_mode: Literal["auto", "force", "none"] = code_mode if code_mode in {"auto", "force", "none"} else "auto"
        normalized_representation_mode = normalize_representation_mode(representation_mode)
        has_code_intent = self._has_code_intent(topic=topic, constraints=constraints)
        should_enforce_code = normalized_mode == "force" or (normalized_mode == "auto" and has_code_intent)
        topic_clean = topic.strip()
        constraints_clean = constraints.strip()

        parse_notes: list[str] = []
        cache_hits = 0
        total_calls = 0

        def _record_history(result: SlideShowGenerationResult) -> None:
            if not record_history:
                return
            if self._history_service is None:
                return
            self._history_service.record_generation(
                asset_type="slideshow",
                topic=topic_clean,
                title=f"Slide Show: {topic_clean}",
                model=settings.normalized_model,
                request_payload={
                    "topic": topic_clean,
                    "constraints": constraints_clean,
                    "subtopic_count": subtopic_count,
                    "slides_per_subtopic": slides_per_subtopic,
                    "code_mode": normalized_mode,
                    "representation_mode": normalized_representation_mode,
                    "grounded_mode": bool(grounding_context.strip()),
                    "require_citations": bool(require_citations),
                    "sources": list(source_manifest or []),
                    "grounding_metadata": dict(grounding_metadata or {}),
                },
                result_payload={"slides": result.slides} if result.slides else {},
                status="error" if result.parse_error else "success",
                cache_hit=result.cache_hits > 0,
                parse_note=" ".join(result.parse_notes).strip(),
                error=result.parse_error or "",
                raw_text=result.debug_raw or "",
            )

        outline_raw, outline_cache_hit = self._generate_outline(
            topic=topic,
            constraints=constraints,
            subtopic_count=subtopic_count,
            grounding_context=grounding_context,
            require_citations=require_citations,
            settings=settings,
        )
        total_calls += 1
        if outline_cache_hit:
            cache_hits += 1

        outline, outline_error, outline_note = self._parser.parse_outline(
            outline_raw,
            max_subtopics=subtopic_count,
            settings=settings,
        )
        if outline_note:
            parse_notes.append(outline_note)
        if outline_error:
            result = SlideShowGenerationResult(
                slides=None,
                parse_error=outline_error,
                parse_notes=parse_notes,
                cache_hits=cache_hits,
                total_calls=total_calls,
                debug_raw=outline_raw,
            )
            _record_history(result)
            return result

        slides: list[dict[str, Any]] = []
        subtopics = outline["subtopics"]

        # Intro slide created locally for consistent deck start.
        slides.append(
            {
                "title": topic.strip(),
                "section": "Introduction",
                "representation": "bullet",
                "layout_payload": {
                    "items": [
                        f"Presentation roadmap with {len(subtopics)} core sections",
                        "Progressive coverage from fundamentals to practical understanding",
                        "Focus on concepts, trade-offs, and real-world applicability",
                    ]
                },
                "bullets": [
                    f"Presentation roadmap with {len(subtopics)} core sections",
                    "Progressive coverage from fundamentals to practical understanding",
                    "Focus on concepts, trade-offs, and real-world applicability",
                ],
                "speaker_notes": "Use this slide to introduce scope and flow.",
            }
        )

        for index, subtopic in enumerate(subtopics, start=1):
            section_raw, section_cache_hit = self._generate_section_slides(
                topic=topic,
                subtopic=subtopic,
                section_index=index,
                total_sections=len(subtopics),
                slides_per_subtopic=slides_per_subtopic,
                constraints=constraints,
                code_mode=normalized_mode,
                representation_mode=normalized_representation_mode,
                has_code_intent=has_code_intent,
                grounding_context=grounding_context,
                require_citations=require_citations,
                settings=settings,
            )
            total_calls += 1
            if section_cache_hit:
                cache_hits += 1

            section_slides, section_error, section_note = self._parser.parse_section_slides(
                section_raw,
                max_slides=slides_per_subtopic,
                settings=settings,
            )
            if section_note:
                parse_notes.append(f"{subtopic['title']}: {section_note}")
            if section_error:
                result = SlideShowGenerationResult(
                    slides=None,
                    parse_error=f"Section `{subtopic['title']}` failed: {section_error}",
                    parse_notes=parse_notes,
                    cache_hits=cache_hits,
                    total_calls=total_calls,
                    debug_raw=section_raw,
                )
                _record_history(result)
                return result

            for slide in section_slides:
                slide["section"] = subtopic["title"]
                slides.append(slide)

        if should_enforce_code and not any(str(s.get("code_snippet", "")).strip() for s in slides):
            fallback_raw, fallback_cache_hit = self._generate_forced_code_slide(
                topic=topic,
                first_subtopic=subtopics[0],
                constraints=constraints,
                grounding_context=grounding_context,
                require_citations=require_citations,
                settings=settings,
            )
            total_calls += 1
            if fallback_cache_hit:
                cache_hits += 1

            fallback_slides, fallback_error, fallback_note = self._parser.parse_section_slides(
                fallback_raw,
                max_slides=1,
                settings=settings,
            )
            if fallback_note:
                parse_notes.append(f"Forced code slide: {fallback_note}")
            if fallback_error:
                parse_notes.append(f"Forced code slide skipped due to parse error: {fallback_error}")
            elif fallback_slides:
                fallback_slide = fallback_slides[0]
                fallback_slide["section"] = subtopics[0]["title"]
                slides.insert(1, fallback_slide)

        slides.append(
            {
                "title": "Summary and Next Steps",
                "section": "Conclusion",
                "representation": "bullet",
                "layout_payload": {
                    "items": [
                        f"Recap of {len(subtopics)} major areas in {topic.strip()}",
                        "Key takeaways to retain for implementation and decision-making",
                        "Suggested path for deeper study and practical application",
                    ]
                },
                "bullets": [
                    f"Recap of {len(subtopics)} major areas in {topic.strip()}",
                    "Key takeaways to retain for implementation and decision-making",
                    "Suggested path for deeper study and practical application",
                ],
                "speaker_notes": "Close with actionable next steps and Q&A transition.",
            }
        )
        slides, representation_notes = self._sanitize_slides(
            slides=slides,
            keep_citations=bool(require_citations),
        )
        parse_notes.extend(representation_notes)

        result = SlideShowGenerationResult(
            slides=slides,
            parse_error=None,
            parse_notes=parse_notes,
            cache_hits=cache_hits,
            total_calls=total_calls,
            debug_raw=None,
        )
        _record_history(result)
        return result

    @staticmethod
    def _sanitize_slides(
        *,
        slides: list[dict[str, Any]],
        keep_citations: bool,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        normalized: list[dict[str, Any]] = []
        notes: list[str] = []
        for slide in slides:
            if not isinstance(slide, dict):
                continue
            bullets = slide.get("bullets", [])
            clean_bullets: list[str] = []
            if isinstance(bullets, list):
                for bullet in bullets:
                    bullet_text = sanitize_text(bullet, keep_citations=keep_citations)
                    if bullet_text:
                        clean_bullets.append(bullet_text)

            raw_layout_payload = SlideShowService._sanitize_json_value(
                slide.get("layout_payload", {}),
                keep_citations=keep_citations,
            )
            candidate_slide = {
                "title": sanitize_text(slide.get("title", ""), keep_citations=keep_citations),
                "section": sanitize_text(slide.get("section", ""), keep_citations=keep_citations),
                "representation": str(slide.get("representation", "bullet")),
                "layout_payload": raw_layout_payload if isinstance(raw_layout_payload, dict) else {},
                "bullets": clean_bullets,
                "speaker_notes": sanitize_text(slide.get("speaker_notes", ""), keep_citations=keep_citations),
                "code_snippet": sanitize_text(
                    slide.get("code_snippet", ""),
                    keep_citations=keep_citations,
                    preserve_newlines=True,
                ),
                "code_language": sanitize_text(slide.get("code_language", ""), keep_citations=True),
            }
            normalized_slide, note = normalize_slide_representation(candidate_slide)
            normalized.append(normalized_slide)
            if note:
                title = str(normalized_slide.get("title", "")).strip() or "slide"
                notes.append(f"{title}: {note}")
        return normalized, notes

    @staticmethod
    def _sanitize_json_value(value: Any, *, keep_citations: bool) -> Any:
        if isinstance(value, dict):
            return {
                str(key): SlideShowService._sanitize_json_value(item, keep_citations=keep_citations)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [
                SlideShowService._sanitize_json_value(item, keep_citations=keep_citations)
                for item in value
            ]
        if value is None:
            return ""
        return sanitize_text(value, keep_citations=keep_citations)

    def _generate_outline(
        self,
        *,
        topic: str,
        constraints: str,
        subtopic_count: int,
        grounding_context: str,
        require_citations: bool,
        settings: GroqSettings,
    ) -> tuple[str, bool]:
        system_prompt = (
            "You are a presentation strategist. "
            "Return strict JSON only. Do not use markdown."
        )
        user_prompt = (
            f"Create an outline for a slide deck on topic: {topic.strip()}\n\n"
            "Return JSON:\n"
            "{\n"
            '  "topic": "topic name",\n'
            '  "subtopics": [\n'
            '    {"title": "subtopic title", "focus": "what this section should achieve"}\n'
            "  ]\n"
            "}\n\n"
            "Rules:\n"
            f"- Generate exactly {subtopic_count} subtopics when possible.\n"
            "- Keep titles concise and presentation-friendly.\n"
            "- Ensure logical flow between subtopics.\n"
            "- Return JSON only."
        )
        if grounding_context.strip():
            user_prompt += (
                "\n\nGrounding sources:\n"
                f"{grounding_context.strip()}\n\n"
                "Use these sources to shape section ordering and focus."
            )
            if require_citations:
                user_prompt += (
                    "\nCitation rule for future slides: section content should support inline citations like [S1]."
                )
        if constraints.strip():
            user_prompt += f"\n\nAdditional constraints:\n{constraints.strip()}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        return self._llm_service.call(
            settings=settings,
            messages=messages,
            task="slideshow_outline",
            label=f"SlideShow Outline: {topic.strip()}",
            topic=topic.strip(),
        )

    def _generate_section_slides(
        self,
        *,
        topic: str,
        subtopic: dict[str, str],
        section_index: int,
        total_sections: int,
        slides_per_subtopic: int,
        constraints: str,
        code_mode: Literal["auto", "force", "none"],
        representation_mode: str,
        has_code_intent: bool,
        grounding_context: str,
        require_citations: bool,
        settings: GroqSettings,
    ) -> tuple[str, bool]:
        section_should_include_code = (
            code_mode == "force" or (code_mode == "auto" and has_code_intent and section_index % 2 == 1)
        )
        if code_mode == "none":
            code_rule = (
                "- Do not include code snippets for this section.\n"
                "- Set `code_snippet` to an empty string and `code_language` to an empty string."
            )
        elif section_should_include_code:
            code_rule = (
                "- Include code in exactly 1 slide for this section when practical.\n"
                "- Put code in `code_snippet` as plain text and set `code_language` (python, sql, javascript, etc.).\n"
                "- Keep code short (8-20 lines) and runnable-looking.\n"
                "- Do NOT put markdown code fences (``` ) anywhere in bullets or code_snippet.\n"
                "- code_snippet must be valid JSON string content (escape newlines and quotes properly).\n"
                "- For non-code slides in this section, leave `code_snippet` and `code_language` empty."
            )
        else:
            code_rule = (
                "- Prefer conceptual slides for this section.\n"
                "- Add code only if absolutely necessary; otherwise keep `code_snippet` empty.\n"
                "- Do NOT use markdown code fences (``` ) in any bullet."
            )

        if representation_mode == "classic":
            representation_rule = (
                "- Prefer `bullet` representation for most slides.\n"
                "- Use non-bullet representations only when they clearly improve comprehension."
            )
        elif representation_mode == "visual":
            representation_rule = (
                "- Prefer non-bullet representations (`two_column`, `timeline`, `comparison`, `process_flow`, `metric_cards`).\n"
                "- Use `bullet` only when the content is not suitable for a visual structure."
            )
        else:
            representation_rule = (
                "- Use a balanced mix of representations.\n"
                "- Select the representation that best matches the content shape."
            )

        system_prompt = (
            "You are a presentation content writer. "
            "Create high-quality slide content in strict JSON only."
        )
        user_prompt = (
            f"Root topic: {topic.strip()}\n"
            f"Current subtopic ({section_index}/{total_sections}): {subtopic['title']}\n"
            f"Subtopic focus: {subtopic.get('focus', '')}\n\n"
            "Create slide content for this subtopic only.\n"
            "Return JSON:\n"
            "{\n"
            '  "slides": [\n'
            '    {\n'
            '      "title": "slide title",\n'
            '      "representation": "bullet|two_column|timeline|comparison|process_flow|metric_cards",\n'
            '      "layout_payload": {"shape depends on representation"},\n'
            '      "bullets": ["point 1", "point 2", "point 3"],\n'
            '      "speaker_notes": "optional presenter notes",\n'
            '      "code_snippet": "optional multi-line code",\n'
            '      "code_language": "optional language"\n'
            "    }\n"
            "  ]\n"
            "}\n\n"
            "Rules:\n"
            f"- Generate {slides_per_subtopic} slides when possible.\n"
            "- Each slide should have 3 to 5 concise bullets.\n"
            "- Bullets should be specific, not vague placeholders.\n"
            "- Keep each bullet presentation-ready (short, clear, informative).\n"
            "- Add citation markers like [S1] for factual/source-backed bullets when sources are provided.\n"
            "- `representation` must be one of: bullet, two_column, timeline, comparison, process_flow, metric_cards.\n"
            "- `layout_payload` requirements:\n"
            "  - bullet: {\"items\": [str]}\n"
            "  - two_column: {\"left_title\": str, \"left_items\": [str], \"right_title\": str, \"right_items\": [str]}\n"
            "  - timeline: {\"events\": [{\"label\": str, \"detail\": str}]}\n"
            "  - comparison: {\"left_title\": str, \"left_points\": [str], \"right_title\": str, \"right_points\": [str]}\n"
            "  - process_flow: {\"steps\": [{\"title\": str, \"detail\": str}]}\n"
            "  - metric_cards: {\"cards\": [{\"label\": str, \"value\": str, \"context\": str}]}\n"
            "- Always include a valid `bullets` list as a backup summary for rendering compatibility.\n"
            f"{representation_rule}\n"
            f"{code_rule}\n"
            "- Return JSON only."
        )
        if grounding_context.strip():
            user_prompt += (
                "\n\nGrounding sources:\n"
                f"{grounding_context.strip()}\n\n"
                "Use the sources for factual grounding and add source markers in bullets/notes when relevant."
            )
            if require_citations:
                user_prompt += (
                    "\nCitation requirement:\n"
                    "- Most slides should include at least one citation marker like [S1] or [S2].\n"
                    "- Do not cite source IDs not present in provided source blocks."
                )
        if constraints.strip():
            user_prompt += f"\n\nAdditional constraints:\n{constraints.strip()}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        return self._llm_service.call(
            settings=settings,
            messages=messages,
            task="slideshow_section",
            label=f"SlideShow Section: {topic.strip()} | {subtopic['title']}",
            topic=f"{topic.strip()} | {subtopic['title']}",
        )

    def _generate_forced_code_slide(
        self,
        *,
        topic: str,
        first_subtopic: dict[str, str],
        constraints: str,
        grounding_context: str,
        require_citations: bool,
        settings: GroqSettings,
    ) -> tuple[str, bool]:
        system_prompt = (
            "You are a presentation content writer. "
            "Return strict JSON only."
        )
        user_prompt = (
            f"Root topic: {topic.strip()}\n"
            f"Subtopic: {first_subtopic.get('title', '').strip()}\n"
            f"Focus: {first_subtopic.get('focus', '').strip()}\n\n"
            "Generate exactly 1 slide that includes a concrete code example.\n"
            "Return JSON:\n"
            "{\n"
            '  "slides": [\n'
            '    {\n'
            '      "title": "slide title",\n'
            '      "bullets": ["point 1", "point 2", "point 3"],\n'
            '      "speaker_notes": "optional presenter notes",\n'
            '      "code_snippet": "required multi-line code",\n'
            '      "code_language": "required language"\n'
            "    }\n"
            "  ]\n"
            "}\n\n"
            "Rules:\n"
            "- code_snippet is required and must be non-empty.\n"
            "- Keep code concise (8-20 lines).\n"
            "- Do NOT use markdown code fences (``` ).\n"
            "- code_snippet must be valid JSON string content (escape newlines and quotes properly).\n"
            "- Keep bullets and notes aligned with the code.\n"
            "- Return JSON only."
        )
        if grounding_context.strip():
            user_prompt += (
                "\n\nGrounding sources:\n"
                f"{grounding_context.strip()}\n\n"
                "Reference source-backed claims with markers like [S1] in bullets when relevant."
            )
            if require_citations:
                user_prompt += (
                    "\nCitation requirement: include at least one valid source citation marker in the slide bullets."
                )
        if constraints.strip():
            user_prompt += f"\n\nAdditional constraints:\n{constraints.strip()}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        return self._llm_service.call(
            settings=settings,
            messages=messages,
            task="slideshow_forced_code_slide",
            label=f"SlideShow Forced Code: {topic.strip()}",
            topic=f"{topic.strip()} | forced_code",
        )

    @staticmethod
    def _has_code_intent(*, topic: str, constraints: str) -> bool:
        combined = f"{topic} {constraints}".lower()
        code_keywords = (
            "code",
            "coding",
            "program",
            "implementation",
            "example",
            "snippet",
            "sql",
            "python",
            "javascript",
            "java",
            "api",
            "script",
            "algorithm",
            "pseudo",
            "pseudocode",
            "function",
            "class",
        )
        return any(keyword in combined for keyword in code_keywords)
