from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable
import re


_TEXT_LIKE_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".rst",
    ".log",
    ".csv",
    ".json",
    ".yaml",
    ".yml",
    ".py",
    ".sql",
    ".js",
    ".ts",
    ".java",
    ".go",
    ".rs",
    ".xml",
    ".html",
}


@dataclass(frozen=True)
class SourceDocument:
    source_id: str
    name: str
    text: str
    char_count: int
    truncated: bool
    source_type: str = "upload"
    uri: str = ""
    provider: str = ""
    query: str = ""
    retrieved_at: str = ""
    quality_score: float = 0.0


class SourceGroundingService:
    def __init__(
        self,
        *,
        max_sources: int = 8,
        max_chars_per_source: int = 5000,
        max_total_chars: int = 20000,
    ) -> None:
        self._max_sources = max(1, int(max_sources))
        self._max_chars_per_source = max(500, int(max_chars_per_source))
        self._max_total_chars = max(2000, int(max_total_chars))

    @property
    def supported_upload_types(self) -> list[str]:
        return sorted(ext.lstrip(".") for ext in (_TEXT_LIKE_EXTENSIONS | {".pdf"}))

    def extract_sources(
        self,
        uploaded_files: Iterable[Any],
        *,
        max_sources: int | None = None,
    ) -> tuple[list[SourceDocument], list[str]]:
        limit = self._max_sources if max_sources is None else max(1, int(max_sources))
        warnings: list[str] = []
        sources: list[SourceDocument] = []
        total_chars = 0

        for index, uploaded_file in enumerate(uploaded_files):
            if len(sources) >= limit:
                warnings.append(f"Only the first {limit} sources were used.")
                break

            name = self._extract_file_name(uploaded_file, index=index)
            raw_bytes = self._read_bytes(uploaded_file)
            if not raw_bytes:
                warnings.append(f"{name}: empty file, skipped.")
                continue

            ext = self._extension(name)
            text, extraction_warning = self._extract_text(name=name, extension=ext, raw_bytes=raw_bytes)
            if extraction_warning:
                warnings.append(extraction_warning)
            if not text.strip():
                warnings.append(f"{name}: no readable text found, skipped.")
                continue

            normalized = self._normalize_text(text)
            if not normalized:
                warnings.append(f"{name}: text became empty after normalization, skipped.")
                continue

            truncated = False
            if len(normalized) > self._max_chars_per_source:
                normalized = normalized[: self._max_chars_per_source].rstrip()
                truncated = True

            if total_chars >= self._max_total_chars:
                warnings.append(
                    f"Source context reached {self._max_total_chars} characters; extra files were ignored."
                )
                break

            remaining = self._max_total_chars - total_chars
            if len(normalized) > remaining:
                normalized = normalized[:remaining].rstrip()
                truncated = True

            if not normalized:
                continue

            source_id = f"S{len(sources) + 1}"
            source = SourceDocument(
                source_id=source_id,
                name=name,
                text=normalized,
                char_count=len(normalized),
                truncated=truncated,
            )
            sources.append(source)
            total_chars += source.char_count

            if truncated:
                warnings.append(f"{name}: text was truncated to fit grounding limits.")

        return sources, warnings

    def build_grounding_context(self, sources: Iterable[SourceDocument]) -> str:
        blocks: list[str] = []
        for source in sources:
            blocks.append(
                "\n".join(
                    [
                        f"[{source.source_id}] {source.name}",
                        source.text,
                    ]
                )
            )
        return "\n\n---\n\n".join(blocks).strip()

    @staticmethod
    def build_source_manifest(sources: Iterable[SourceDocument]) -> list[dict[str, Any]]:
        manifest: list[dict[str, Any]] = []
        for source in sources:
            manifest.append(
                {
                    "source_id": source.source_id,
                    "name": source.name,
                    "char_count": source.char_count,
                    "truncated": source.truncated,
                    "source_type": source.source_type,
                    "uri": source.uri,
                    "provider": source.provider,
                    "query": source.query,
                    "retrieved_at": source.retrieved_at,
                    "quality_score": source.quality_score,
                }
            )
        return manifest

    @staticmethod
    def _extract_file_name(uploaded_file: Any, *, index: int) -> str:
        raw_name = getattr(uploaded_file, "name", "") or ""
        cleaned = " ".join(str(raw_name).split()).strip()
        return cleaned or f"source_{index + 1}"

    @staticmethod
    def _read_bytes(uploaded_file: Any) -> bytes:
        if hasattr(uploaded_file, "getvalue"):
            value = uploaded_file.getvalue()
            if isinstance(value, bytes):
                return value
            if isinstance(value, bytearray):
                return bytes(value)

        if hasattr(uploaded_file, "read"):
            value = uploaded_file.read()
            if isinstance(value, bytes):
                return value
            if isinstance(value, bytearray):
                return bytes(value)
        return b""

    def _extract_text(self, *, name: str, extension: str, raw_bytes: bytes) -> tuple[str, str | None]:
        if extension == ".pdf":
            return self._extract_pdf_text(name=name, raw_bytes=raw_bytes)
        return self._decode_text(raw_bytes), None

    @staticmethod
    def _extension(name: str) -> str:
        lowered = name.lower()
        dot_idx = lowered.rfind(".")
        if dot_idx == -1:
            return ""
        return lowered[dot_idx:]

    @staticmethod
    def _decode_text(raw_bytes: bytes) -> str:
        for encoding in ("utf-8", "utf-16", "latin-1"):
            try:
                return raw_bytes.decode(encoding)
            except UnicodeDecodeError:
                continue
        return raw_bytes.decode("utf-8", errors="ignore")

    def _extract_pdf_text(self, *, name: str, raw_bytes: bytes) -> tuple[str, str | None]:
        try:
            from pypdf import PdfReader
        except ModuleNotFoundError:
            return "", (
                f"{name}: PDF extraction is unavailable because `pypdf` is not installed."
            )

        try:
            from io import BytesIO

            reader = PdfReader(BytesIO(raw_bytes))
            chunks: list[str] = []
            for page in reader.pages:
                text = page.extract_text() or ""
                if text.strip():
                    chunks.append(text)
            return "\n\n".join(chunks).strip(), None
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
            return "", f"{name}: failed to parse PDF text."

    @staticmethod
    def _normalize_text(text: str) -> str:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        normalized = "\n".join(line.rstrip() for line in normalized.splitlines())
        normalized = re.sub(r"\n{3,}", "\n\n", normalized)
        return normalized.strip()
