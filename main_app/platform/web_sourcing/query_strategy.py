from __future__ import annotations

import re


_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_TYPO_FIXES = {
    "tranformers": "transformers",
    "tranformer": "transformer",
    "tranformar": "transformer",
    "llm,s": "llms",
    "llm's": "llms",
}


def build_query_variants(query: str, *, max_variants: int = 3) -> list[str]:
    normalized = normalize_query_text(query)
    if not normalized:
        return []

    limit = max(1, int(max_variants))
    base_corrected = _apply_typo_fixes(normalized)
    raw_variants = [
        normalized,
        base_corrected,
        f"{base_corrected} overview fundamentals explained",
        f"{base_corrected} architecture implementation best practices",
    ]
    return _dedupe_ordered(raw_variants)[:limit]


def normalize_query_text(query: str) -> str:
    return " ".join(str(query or "").split()).strip()


def tokenize_text(text: str) -> list[str]:
    return [token for token in _TOKEN_PATTERN.findall(str(text or "").lower()) if len(token) >= 2]


def _apply_typo_fixes(query: str) -> str:
    tokens = str(query or "").split()
    fixed = [_TYPO_FIXES.get(token.lower(), token) for token in tokens]
    return " ".join(fixed).strip()


def _dedupe_ordered(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        normalized = normalize_query_text(value)
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(normalized)
    return output
