from __future__ import annotations

import json
import os
import re
from typing import Any, Literal, cast

from main_app.shared.slideshow.representation_normalizer import normalize_representation_mode
from main_app.contracts import AudioOverviewPayload, SlideContent, VideoPayload, VideoSlideScript
from main_app.models import GroqSettings, VideoGenerationResult
from main_app.parsers.audio_overview_parser import AudioOverviewParser
from main_app.services.asset_history_service import AssetHistoryService
from main_app.services.audio_overview_service import AudioOverviewService
from main_app.services.cached_llm_service import CachedLLMService
from main_app.services.video_conversation_timeline_service import VideoConversationTimelineService
from main_app.services.slideshow_service import SlideShowService
from main_app.services.text_sanitizer import sanitize_text


class VideoAssetService:
    _DEFAULT_SPEAKERS: tuple[tuple[str, str], ...] = (
        ("Ava", "Concept architect and big-picture guide"),
        ("Noah", "Practical engineer focused on implementation"),
        ("Mia", "Critical reviewer focused on trade-offs"),
        ("Liam", "Examples specialist for intuition and analogies"),
        ("Zara", "Performance and scale specialist"),
        ("Ethan", "Reliability and operations specialist"),
    )
    _YOUTUBE_PROMPT_BLOCK = (
        "Optional YouTube educational creator style:\n"
        "- Start with a hook on why this slide matters in real-world use.\n"
        "- Keep pacing concise and high-retention for spoken delivery.\n"
        "- Prefer practical examples and crisp transitions.\n"
        "- Avoid aggressive like/subscribe/click CTA language.\n"
    )
    _HINGLISH_PROMPT_BLOCK = (
        "Optional script language mode: Roman Hinglish.\n"
        "- Write natural spoken Hinglish with Hindi + English mixed in each slide conversation.\n"
        "- Use only Latin/Roman script (no Devanagari).\n"
        "- Keep lines concise, educational, and spoken-friendly.\n"
        "- Preserve technical terms in English when clearer.\n"
    )

    def __init__(
        self,
        llm_service: CachedLLMService,
        slideshow_service: SlideShowService,
        script_parser: AudioOverviewParser,
        audio_overview_service: AudioOverviewService,
        history_service: AssetHistoryService | None = None,
        timeline_service: VideoConversationTimelineService | None = None,
    ) -> None:
        self._llm_service = llm_service
        self._slideshow_service = slideshow_service
        self._script_parser = script_parser
        self._audio_overview_service = audio_overview_service
        self._history_service = history_service
        self._timeline_service = timeline_service or VideoConversationTimelineService()

    def generate(
        self,
        *,
        topic: str,
        constraints: str,
        subtopic_count: int,
        slides_per_subtopic: int,
        code_mode: Literal["auto", "force", "none"] = "auto",
        speaker_count: int = 2,
        conversation_style: str = "Educational Discussion",
        video_template: str = "standard",
        animation_style: str = "none",
        representation_mode: str = "auto",
        render_mode: Literal["avatar_conversation", "classic_slides"] | None = None,
        avatar_enable_subtitles: bool = True,
        avatar_style_pack: str = "default",
        avatar_allow_fallback: bool = True,
        use_youtube_prompt: bool = False,
        use_hinglish_script: bool = False,
        settings: GroqSettings,
    ) -> VideoGenerationResult:
        requested_speakers = max(2, min(int(speaker_count), 6))
        normalized_mode: Literal["auto", "force", "none"] = code_mode if code_mode in {"auto", "force", "none"} else "auto"
        topic_clean = " ".join(str(topic).split()).strip()
        constraints_clean = " ".join(str(constraints).split()).strip()
        conversation_style_clean = " ".join(str(conversation_style).split()).strip() or "Educational Discussion"
        template_clean = " ".join(str(video_template).split()).strip().lower() or "standard"
        animation_style_clean = " ".join(str(animation_style).split()).strip().lower() or "smooth"
        representation_mode_clean = normalize_representation_mode(representation_mode)
        render_mode_clean = self._normalize_render_mode(render_mode)
        avatar_style_pack_clean = " ".join(str(avatar_style_pack).split()).strip().lower() or "default"
        avatar_engine = " ".join(str(os.getenv("VIDEO_AVATAR_ENGINE", "local")).split()).strip().lower() or "local"
        use_hinglish_script_mode = bool(use_hinglish_script)
        parse_notes: list[str] = []
        cache_hits = 0
        total_calls = 0
        speaker_roster = self._speaker_roster(requested_speakers)

        def _record_history(result: VideoGenerationResult) -> None:
            if self._history_service is None:
                return
            self._history_service.record_generation(
                asset_type="video",
                topic=topic_clean,
                title=f"Video: {topic_clean}",
                model=settings.normalized_model,
                request_payload={
                    "topic": topic_clean,
                    "constraints": constraints_clean,
                    "subtopic_count": subtopic_count,
                    "slides_per_subtopic": slides_per_subtopic,
                    "code_mode": normalized_mode,
                    "speaker_count": requested_speakers,
                    "conversation_style": conversation_style_clean,
                    "video_template": template_clean,
                    "animation_style": animation_style_clean,
                    "representation_mode": representation_mode_clean,
                    "render_mode": render_mode_clean,
                    "avatar_enable_subtitles": bool(avatar_enable_subtitles),
                    "avatar_style_pack": avatar_style_pack_clean,
                    "avatar_allow_fallback": bool(avatar_allow_fallback),
                    "avatar_engine": avatar_engine,
                    "youtube_prompt": bool(use_youtube_prompt),
                    "hinglish_script": use_hinglish_script_mode,
                },
                result_payload=result.video_payload if result.video_payload else {},
                status="error" if result.parse_error else "success",
                cache_hit=result.cache_hits > 0,
                parse_note=" ".join(result.parse_notes).strip(),
                error=result.parse_error or "",
                raw_text=result.debug_raw or "",
            )

        slideshow_result = self._slideshow_service.generate(
            topic=topic_clean,
            constraints=constraints_clean,
            subtopic_count=subtopic_count,
            slides_per_subtopic=slides_per_subtopic,
            code_mode=normalized_mode,
            representation_mode=representation_mode_clean,
            settings=settings,
            record_history=False,
        )
        cache_hits += slideshow_result.cache_hits
        total_calls += slideshow_result.total_calls
        parse_notes.extend(slideshow_result.parse_notes)

        if slideshow_result.parse_error or not slideshow_result.slides:
            result = VideoGenerationResult(
                video_payload=None,
                parse_error=f"Slideshow stage failed: {slideshow_result.parse_error or 'No slides generated.'}",
                parse_notes=parse_notes,
                cache_hits=cache_hits,
                total_calls=total_calls,
                debug_raw=slideshow_result.debug_raw,
            )
            _record_history(result)
            return result

        slide_scripts: list[dict[str, Any]] = []
        for slide_index, slide in enumerate(slideshow_result.slides, start=1):
            slide_title = " ".join(str(slide.get("title", "")).split()).strip() or f"Slide {slide_index}"
            raw_text, cache_hit = self._generate_slide_script(
                topic=topic_clean,
                slide=slide,
                slide_index=slide_index,
                total_slides=len(slideshow_result.slides),
                speaker_roster=speaker_roster,
                conversation_style=conversation_style_clean,
                use_youtube_prompt=bool(use_youtube_prompt),
                use_hinglish_script=use_hinglish_script_mode,
                settings=settings,
            )
            total_calls += 1
            if cache_hit:
                cache_hits += 1

            parsed, parse_error, parse_note = self._script_parser.parse(
                raw_text,
                settings=settings,
                min_speakers=2,
                max_speakers=max(2, requested_speakers),
                min_turns=2,
                max_turns=12,
            )
            if parse_note:
                parse_notes.append(f"Slide {slide_index}: {parse_note}")
            if parse_error or not parsed:
                result = VideoGenerationResult(
                    video_payload=None,
                    parse_error=f"Slide `{slide_title}` narration failed: {parse_error or 'Parse failed.'}",
                    parse_notes=parse_notes,
                    cache_hits=cache_hits,
                    total_calls=total_calls,
                    debug_raw=raw_text,
                )
                _record_history(result)
                return result

            normalized_script = self._normalize_slide_script(
                parsed_payload=parsed,
                slide_title=slide_title,
                slide_index=slide_index,
                speaker_roster=speaker_roster,
            )
            if not normalized_script["dialogue"]:
                result = VideoGenerationResult(
                    video_payload=None,
                    parse_error=f"Slide `{slide_title}` narration did not include usable dialogue.",
                    parse_notes=parse_notes,
                    cache_hits=cache_hits,
                    total_calls=total_calls,
                    debug_raw=raw_text,
                )
                _record_history(result)
                return result
            slide_scripts.append(normalized_script)

        timeline = self._timeline_service.build_timeline(
            slides=cast(list[SlideContent], slideshow_result.slides),
            slide_scripts=cast(list[VideoSlideScript], slide_scripts),
        )
        visual_refs = []
        timeline_turns = timeline.get("turns", []) if isinstance(timeline.get("turns"), list) else []
        for turn in timeline_turns:
            if not isinstance(turn, dict):
                continue
            visual_ref = turn.get("visual_ref")
            if isinstance(visual_ref, dict):
                visual_refs.append(visual_ref)

        video_payload = {
            "topic": topic_clean,
            "title": f"{topic_clean} Narrated Video",
            "slides": slideshow_result.slides,
            "speaker_roster": speaker_roster,
            "slide_scripts": slide_scripts,
            "conversation_style": conversation_style_clean,
            "video_template": template_clean,
            "animation_style": animation_style_clean,
            "representation_mode": representation_mode_clean,
            "render_mode": render_mode_clean,
            "conversation_timeline": timeline,
            "visual_refs": visual_refs,
            "metadata": {
                "total_slides": len(slideshow_result.slides),
                "speaker_count": requested_speakers,
                "code_mode": normalized_mode,
                "representation_mode": representation_mode_clean,
                "render_mode": render_mode_clean,
                "avatar_enable_subtitles": bool(avatar_enable_subtitles),
                "avatar_style_pack": avatar_style_pack_clean,
                "avatar_allow_fallback": bool(avatar_allow_fallback),
                "avatar_engine": avatar_engine,
                "youtube_prompt": bool(use_youtube_prompt),
                "script_language": "hinglish" if use_hinglish_script_mode else "english",
            },
        }
        result = VideoGenerationResult(
            video_payload=cast(VideoPayload, video_payload),
            parse_error=None,
            parse_notes=parse_notes,
            cache_hits=cache_hits,
            total_calls=total_calls,
            debug_raw=None,
        )
        _record_history(result)
        return result

    @staticmethod
    def _normalize_render_mode(
        render_mode: Literal["avatar_conversation", "classic_slides"] | None,
    ) -> Literal["avatar_conversation", "classic_slides"]:
        raw = " ".join(str(render_mode or os.getenv("VIDEO_RENDER_MODE_DEFAULT", "avatar_conversation")).split()).strip().lower()
        if raw == "classic_slides":
            return "classic_slides"
        return "avatar_conversation"

    def synthesize_audio(
        self,
        *,
        video_payload: VideoPayload,
        language: str = "en",
        slow: bool = False,
    ) -> tuple[bytes | None, str | None]:
        speakers = video_payload.get("speaker_roster", [])
        scripts = video_payload.get("slide_scripts", [])
        if not isinstance(scripts, list):
            return None, "No slide scripts available to synthesize."

        dialogue: list[dict[str, str]] = []
        for script in scripts:
            if not isinstance(script, dict):
                continue
            turns = script.get("dialogue", [])
            if not isinstance(turns, list):
                continue
            for turn in turns:
                if not isinstance(turn, dict):
                    continue
                speaker = " ".join(str(turn.get("speaker", "")).split()).strip()
                text = " ".join(str(turn.get("text", "")).split()).strip()
                if not text:
                    continue
                dialogue.append({"speaker": speaker or "Speaker", "text": text})

        if not dialogue:
            return None, "No dialogue content available in slide scripts."

        overview_payload = cast(
            AudioOverviewPayload,
            {
            "topic": str(video_payload.get("topic", "")).strip(),
            "title": str(video_payload.get("title", "")).strip() or "Narrated Video Audio",
            "speakers": speakers if isinstance(speakers, list) else [],
            "dialogue": dialogue,
            "summary": "Narration track generated from slide scripts.",
            },
        )
        return self._audio_overview_service.synthesize_mp3(
            overview_payload=overview_payload,
            language=language,
            slow=slow,
        )

    def _generate_slide_script(
        self,
        *,
        topic: str,
        slide: Any,
        slide_index: int,
        total_slides: int,
        speaker_roster: list[dict[str, str]],
        conversation_style: str,
        use_youtube_prompt: bool,
        use_hinglish_script: bool,
        settings: GroqSettings,
    ) -> tuple[str, bool]:
        speaker_lines = "\n".join(
            f'- {speaker["name"]}: {speaker["role"]}'
            for speaker in speaker_roster
            if str(speaker.get("name", "")).strip()
        )
        slide_payload = {
            "title": str(slide.get("title", "")).strip(),
            "section": str(slide.get("section", "")).strip(),
            "representation": str(slide.get("representation", "bullet")).strip(),
            "layout_payload": slide.get("layout_payload", {}),
            "bullets": [str(item).strip() for item in slide.get("bullets", []) if str(item).strip()],
            "speaker_notes": str(slide.get("speaker_notes", "")).strip(),
            "code_snippet": str(slide.get("code_snippet", "")).strip(),
            "code_language": str(slide.get("code_language", "")).strip(),
        }
        system_prompt = (
            "You write narration scripts for educational videos. "
            "Return strict JSON only. Do not use markdown."
        )
        user_prompt = (
            f"Topic: {topic}\n"
            f"Slide position: {slide_index}/{total_slides}\n"
            f"Conversation style: {conversation_style}\n\n"
            "Speaker roster (use only these names):\n"
            f"{speaker_lines}\n\n"
            "Slide JSON:\n"
            f"{json.dumps(slide_payload, ensure_ascii=False, indent=2)}\n\n"
            "Return JSON schema:\n"
            "{\n"
            '  "title": "short narration title",\n'
            '  "speakers": [{"name":"Ava","role":"..."}],\n'
            '  "dialogue": [\n'
            '    {"speaker":"Ava","text":"spoken line"},\n'
            '    {"speaker":"Noah","text":"spoken line"}\n'
            "  ],\n"
            '  "summary": "one-line takeaway"\n'
            "}\n\n"
            "Rules:\n"
            f"- Keep the narration focused on this slide only.\n"
            "- Generate 3-6 dialogue turns.\n"
            "- Alternate speakers naturally for multi-voice narration.\n"
            "- Dialogue text must NOT contain speaker name prefixes like `Ava:` or `Ava says`.\n"
            "- If slide has code, explain what the code is doing and why.\n"
            "- Keep each turn concise and spoken-friendly.\n"
            "- Return JSON only."
        )
        if use_hinglish_script:
            user_prompt += "\n\n" + self._HINGLISH_PROMPT_BLOCK
        if use_youtube_prompt:
            user_prompt += "\n\n" + self._YOUTUBE_PROMPT_BLOCK
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        return self._llm_service.call(
            settings=settings,
            messages=messages,
            task="video_slide_script",
            label=f"Video Slide Script: {topic} | {slide_index}",
            topic=f"{topic} | slide {slide_index}",
        )

    @classmethod
    def _speaker_roster(cls, speaker_count: int) -> list[dict[str, str]]:
        count = max(2, min(int(speaker_count), len(cls._DEFAULT_SPEAKERS)))
        roster: list[dict[str, str]] = []
        for idx in range(count):
            name, role = cls._DEFAULT_SPEAKERS[idx]
            roster.append({"name": name, "role": role})
        return roster

    def _normalize_slide_script(
        self,
        *,
        parsed_payload: dict[str, Any],
        slide_title: str,
        slide_index: int,
        speaker_roster: list[dict[str, str]],
    ) -> dict[str, Any]:
        roster_names = [str(item.get("name", "")).strip() for item in speaker_roster if str(item.get("name", "")).strip()]
        roster_name_map = {name.lower(): name for name in roster_names}
        dialogue = parsed_payload.get("dialogue", [])
        normalized_turns: list[dict[str, str]] = []
        if isinstance(dialogue, list):
            for idx, turn in enumerate(dialogue):
                if not isinstance(turn, dict):
                    continue
                raw_speaker = " ".join(str(turn.get("speaker", "")).split()).strip()
                canonical_speaker = roster_name_map.get(raw_speaker.lower(), "")
                if not canonical_speaker:
                    canonical_speaker = roster_names[idx % len(roster_names)] if roster_names else "Speaker"
                text = self._normalize_dialogue_text(
                    raw_text=str(turn.get("text", "")),
                    roster_names=roster_names,
                )
                if not text:
                    continue
                normalized_turns.append({"speaker": canonical_speaker, "text": text})

        return {
            "slide_index": slide_index,
            "slide_title": slide_title,
            "dialogue": normalized_turns,
            "summary": " ".join(str(parsed_payload.get("summary", "")).split()).strip(),
            "estimated_duration_sec": self._estimate_duration_seconds(normalized_turns),
        }

    @staticmethod
    def _normalize_dialogue_text(*, raw_text: str, roster_names: list[str]) -> str:
        text = sanitize_text(raw_text, keep_citations=False)
        if not text:
            return ""
        if roster_names:
            escaped_names = "|".join(re.escape(name) for name in roster_names if name)
            if escaped_names:
                text = re.sub(
                    rf"^\s*(?:{escaped_names})\s*(?::|-|says|said|asks|notes)\s*",
                    "",
                    text,
                    flags=re.IGNORECASE,
                ).strip()
        if len(text) > 360:
            text = text[:360].rsplit(" ", 1)[0].strip() + "..."
        return text

    @staticmethod
    def _estimate_duration_seconds(turns: list[dict[str, str]]) -> int:
        if not turns:
            return 0
        words = 0
        for turn in turns:
            words += len(" ".join(str(turn.get("text", "")).split()).split())
        # Approx spoken pace ~150 words/minute.
        seconds = int(round((max(words, 1) / 150.0) * 60.0))
        return max(12, seconds)
