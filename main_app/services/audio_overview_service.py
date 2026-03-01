from __future__ import annotations

import asyncio
from io import BytesIO
from typing import Any, cast

from main_app.contracts import AudioOverviewPayload
from main_app.models import AudioOverviewGenerationResult, GroqSettings
from main_app.parsers.audio_overview_parser import AudioOverviewParser
from main_app.services.asset_history_service import AssetHistoryService
from main_app.services.cached_llm_service import CachedLLMService


class AudioOverviewService:
    _YOUTUBE_PROMPT_BLOCK = (
        "Optional YouTube educational creator style:\n"
        "- Open with a strong practical hook in the first turn.\n"
        "- Maintain high-retention pacing with tight, spoken-friendly turns.\n"
        "- Prefer concrete examples and audience-oriented clarity.\n"
        "- Avoid aggressive like/subscribe/click CTA language.\n"
    )
    _HINGLISH_PROMPT_BLOCK = (
        "Optional script language mode: Roman Hinglish.\n"
        "- Write natural spoken Hinglish with Hindi + English mixed in each dialogue turn.\n"
        "- Use only Latin/Roman script (no Devanagari).\n"
        "- Keep lines concise, educational, and spoken-friendly.\n"
        "- Preserve technical terms in English when clearer.\n"
    )

    _VOICE_POOL_BY_LANGUAGE = {
        "en": [
            "en-US-AriaNeural",
            "en-US-GuyNeural",
            "en-GB-SoniaNeural",
            "en-GB-RyanNeural",
            "en-AU-NatashaNeural",
            "en-AU-WilliamNeural",
        ],
        "hi": [
            "hi-IN-SwaraNeural",
            "hi-IN-MadhurNeural",
        ],
        "es": [
            "es-ES-ElviraNeural",
            "es-ES-AlvaroNeural",
        ],
        "fr": [
            "fr-FR-DeniseNeural",
            "fr-FR-HenriNeural",
        ],
        "de": [
            "de-DE-KatjaNeural",
            "de-DE-ConradNeural",
        ],
        "ja": [
            "ja-JP-NanamiNeural",
            "ja-JP-KeitaNeural",
        ],
    }

    def __init__(
        self,
        llm_service: CachedLLMService,
        parser: AudioOverviewParser,
        history_service: AssetHistoryService | None = None,
    ) -> None:
        self._llm_service = llm_service
        self._parser = parser
        self._history_service = history_service

    def generate(
        self,
        *,
        topic: str,
        speaker_count: int,
        turn_count: int,
        conversation_style: str,
        constraints: str,
        use_youtube_prompt: bool = False,
        use_hinglish_script: bool = False,
        settings: GroqSettings,
    ) -> AudioOverviewGenerationResult:
        requested_speakers = max(2, min(int(speaker_count), 6))
        requested_turns = max(6, min(int(turn_count), 28))
        minimum_required_turns = max(4, min(10, requested_turns))

        system_prompt = (
            "You are a podcast producer creating educational audio overviews. "
            "Return strict JSON only."
        )
        user_prompt = (
            f"Create an audio overview script for topic: {topic.strip()}\n"
            f"Conversation style: {conversation_style}\n\n"
            "Return JSON schema:\n"
            "{\n"
            '  "topic": "topic name",\n'
            '  "title": "episode title",\n'
            '  "speakers": [\n'
            '    {"name": "Host Name", "role": "brief persona"}\n'
            "  ],\n"
            '  "dialogue": [\n'
            '    {"speaker": "Host Name", "text": "single spoken turn"}\n'
            "  ],\n"
            '  "summary": "short one-paragraph takeaway"\n'
            "}\n\n"
            "Rules:\n"
            f"- Generate exactly {requested_speakers} speakers when possible.\n"
            f"- Generate exactly {requested_turns} dialogue turns when possible.\n"
            "- Keep each dialogue turn concise (1-3 sentences) and natural for spoken audio.\n"
            "- Ensure all speaker names used in dialogue are defined in `speakers`.\n"
            "- Keep the conversation informative, practical, and coherent end-to-end.\n"
            "- Do not include markdown, code blocks, or extra text.\n"
            "- Return JSON only."
        )

        if constraints.strip():
            user_prompt += f"\n\nAdditional constraints:\n{constraints.strip()}"
        if use_hinglish_script:
            user_prompt += "\n\n" + self._HINGLISH_PROMPT_BLOCK
        if use_youtube_prompt:
            user_prompt += "\n\n" + self._YOUTUBE_PROMPT_BLOCK

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        raw_text, cache_hit = self._llm_service.call(
            settings=settings,
            messages=messages,
            task="audio_overview_script",
            label=f"Audio Overview: {topic.strip()}",
            topic=topic.strip(),
        )

        parsed_overview, parse_error, parse_note = self._parser.parse(
            raw_text,
            settings=settings,
            min_speakers=max(2, min(requested_speakers, 6)),
            max_speakers=6,
            min_turns=minimum_required_turns,
            max_turns=40,
        )

        if parsed_overview and not parse_error:
            actual_turns = len(parsed_overview.get("dialogue", []))
            if actual_turns < requested_turns:
                gap_note = (
                    f"Requested {requested_turns} dialogue turns; model returned {actual_turns}. "
                    "You can regenerate to get a longer conversation."
                )
                parse_note = f"{parse_note} {gap_note}".strip() if parse_note else gap_note

        result = AudioOverviewGenerationResult(
            raw_text=raw_text,
            parsed_overview=cast(AudioOverviewPayload | None, parsed_overview),
            parse_error=parse_error,
            parse_note=parse_note,
            cache_hit=cache_hit,
        )
        if self._history_service is not None:
            self._history_service.record_generation(
                asset_type="audio_overview",
                topic=topic.strip(),
                title=f"Audio Overview: {topic.strip()}",
                model=settings.normalized_model,
                request_payload={
                    "topic": topic.strip(),
                    "speaker_count": requested_speakers,
                    "turn_count": requested_turns,
                    "conversation_style": conversation_style.strip(),
                    "constraints": constraints.strip(),
                    "youtube_prompt": bool(use_youtube_prompt),
                    "hinglish_script": bool(use_hinglish_script),
                },
                result_payload=parsed_overview if parsed_overview is not None else {},
                status="error" if parse_error else "success",
                cache_hit=cache_hit,
                parse_note=parse_note or "",
                error=parse_error or "",
                raw_text=raw_text if parse_error else "",
            )
        return result

    def synthesize_mp3(
        self,
        *,
        overview_payload: AudioOverviewPayload,
        language: str = "en",
        slow: bool = False,
    ) -> tuple[bytes | None, str | None]:
        turns = self._extract_dialogue_turns(overview_payload)
        if not turns:
            return None, "No dialogue content available to synthesize."

        try:
            import edge_tts  # type: ignore
        except (ImportError, ModuleNotFoundError):
            edge_tts = None

        if edge_tts is not None:
            try:
                audio_bytes = self._run_async(
                    self._synthesize_multi_voice_with_edge_tts(
                        turns=turns,
                        overview_payload=overview_payload,
                        language=language,
                        slow=slow,
                        edge_tts_module=edge_tts,
                    )
                )
                if audio_bytes:
                    return audio_bytes, None
            except (RuntimeError, OSError, AttributeError, ValueError):
                # Fall back to single-voice gTTS when multi-voice provider is unavailable.
                pass

        try:
            from gtts import gTTS  # type: ignore
        except (ImportError, ModuleNotFoundError):
            return None, "TTS dependencies are not installed. Install requirements to enable audio generation."

        spoken_text = self._to_spoken_script(overview_payload)
        if not spoken_text:
            return None, "No dialogue content available to synthesize."

        # Avoid oversized requests for TTS providers.
        max_chars = 9000
        if len(spoken_text) > max_chars:
            spoken_text = spoken_text[:max_chars].rsplit(" ", 1)[0] + "."

        try:
            audio_buffer = BytesIO()
            tts = gTTS(text=spoken_text, lang=language, slow=slow)
            tts.write_to_fp(audio_buffer)
            return (
                audio_buffer.getvalue(),
                "Multi-voice engine unavailable; generated single-voice audio fallback.",
            )
        except (RuntimeError, ValueError, TypeError, OSError, AssertionError) as exc:
            return None, f"Failed to synthesize audio: {exc}"

    @staticmethod
    def _to_spoken_script(overview_payload: AudioOverviewPayload) -> str:
        title = " ".join(str(overview_payload.get("title", "")).split()).strip()
        topic = " ".join(str(overview_payload.get("topic", "")).split()).strip()
        dialogue = overview_payload.get("dialogue") or []

        lines: list[str] = []
        if title:
            lines.append(title + ".")
        elif topic:
            lines.append(f"Audio overview on {topic}.")

        for turn in dialogue:
            if not isinstance(turn, dict):
                continue
            text = " ".join(str(turn.get("text", "")).split()).strip()
            if not text:
                continue
            lines.append(text)

        summary = " ".join(str(overview_payload.get("summary", "")).split()).strip()
        if summary:
            lines.append(f"Summary: {summary}")

        return " ".join(lines).strip()

    def _extract_dialogue_turns(self, overview_payload: AudioOverviewPayload) -> list[tuple[str, str]]:
        raw_dialogue = overview_payload.get("dialogue") or []
        turns: list[tuple[str, str]] = []
        if not isinstance(raw_dialogue, list):
            return turns

        for turn in raw_dialogue:
            if not isinstance(turn, dict):
                continue
            speaker = " ".join(str(turn.get("speaker", "")).split()).strip() or "Speaker"
            text = " ".join(str(turn.get("text", "")).split()).strip()
            if not text:
                continue
            if len(text) > 500:
                text = text[:500].rsplit(" ", 1)[0] + "."
            turns.append((speaker, text))

        return turns

    def _speaker_voice_map(
        self,
        *,
        overview_payload: AudioOverviewPayload,
        language: str,
        observed_speakers: list[str],
    ) -> dict[str, str]:
        language_code = (language or "en").strip().lower()
        voice_pool = self._VOICE_POOL_BY_LANGUAGE.get(language_code) or self._VOICE_POOL_BY_LANGUAGE["en"]

        ordered_speakers: list[str] = []
        raw_speakers = overview_payload.get("speakers") or []
        if isinstance(raw_speakers, list):
            for item in raw_speakers:
                if isinstance(item, dict):
                    name = " ".join(str(item.get("name", "")).split()).strip()
                else:
                    name = " ".join(str(item).split()).strip()
                if name and name not in ordered_speakers:
                    ordered_speakers.append(name)

        for name in observed_speakers:
            if name not in ordered_speakers:
                ordered_speakers.append(name)

        if not ordered_speakers:
            ordered_speakers = ["Speaker 1", "Speaker 2"]

        voice_map: dict[str, str] = {}
        for index, speaker_name in enumerate(ordered_speakers):
            voice_map[speaker_name] = voice_pool[index % len(voice_pool)]
        return voice_map

    async def _synthesize_multi_voice_with_edge_tts(
        self,
        *,
        turns: list[tuple[str, str]],
        overview_payload: AudioOverviewPayload,
        language: str,
        slow: bool,
        edge_tts_module: Any,
    ) -> bytes:
        observed_speakers = [speaker for speaker, _ in turns]
        voice_map = self._speaker_voice_map(
            overview_payload=overview_payload,
            language=language,
            observed_speakers=observed_speakers,
        )
        default_voice = next(iter(voice_map.values()), self._VOICE_POOL_BY_LANGUAGE["en"][0])
        rate = "-12%" if slow else "+0%"

        audio_parts: list[bytes] = []
        for speaker, text in turns:
            voice = voice_map.get(speaker, default_voice)
            communicator = edge_tts_module.Communicate(text=text, voice=voice, rate=rate)
            chunk_buffer = bytearray()
            async for chunk in communicator.stream():
                if chunk.get("type") == "audio":
                    chunk_buffer.extend(chunk.get("data", b""))
            if chunk_buffer:
                audio_parts.append(bytes(chunk_buffer))

        return b"".join(audio_parts)

    @staticmethod
    def _run_async(coro: Any) -> Any:
        try:
            return asyncio.run(coro)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(coro)
            finally:
                loop.close()
