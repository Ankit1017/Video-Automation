from __future__ import annotations

import re
import unicodedata


_CITATION_PATTERN = re.compile(r"\s*\[S\d+\]")
_MOJIBAKE_MAP = {
    "\u00e2\u20ac\u00a2": "-",   # â€¢
    "\u00e2\u20ac\u201c": "-",   # â€“
    "\u00e2\u20ac\u201d": "-",   # â€”
    "\u00e2\u20ac\u02dc": "'",   # â€˜
    "\u00e2\u20ac\u2122": "'",   # â€™
    "\u00e2\u20ac\u0153": '"',   # â€œ
    "\u00e2\u20ac\ufffd": '"',   # â€�
    "\u00e2\u20ac\u00a6": "...", # â€¦
    "\u00ef\u00ac\u0080": "ff",  # ï¬
    "\u00ef\u00ac\u0081": "fi",  # ï¬
    "\u00ef\u00ac\u0082": "fl",  # ï¬‚
    "\u00ef\u00ac\u0083": "ffi", # ï¬ƒ
    "\u00ef\u00ac\u0084": "ffl", # ï¬„
}
_BAD_CHAR_MAP = {
    "\u00a0": " ",
    "\u200b": "",
    "\u200c": "",
    "\u200d": "",
    "\ufeff": "",
    "\u2010": "-",
    "\u2011": "-",
    "\u2012": "-",
    "\u2013": "-",
    "\u2014": "-",
    "\u2212": "-",
    "\u2264": "<=",
    "\u2265": ">=",
    "\u2260": "!=",
    "\u2248": "~=",
    "\u00b7": "*",
    "\u2219": "*",
    "\u2022": "-",
    "\u2080": "0",
    "\u2081": "1",
    "\u2082": "2",
    "\u2083": "3",
    "\u2084": "4",
    "\u2085": "5",
    "\u2086": "6",
    "\u2087": "7",
    "\u2088": "8",
    "\u2089": "9",
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
    "\ufb05": "ft",
    "\ufb06": "st",
    "\u25a0": "",
    "\u25aa": "",
    "\u25ab": "",
    "\ufffd": "",
}


def sanitize_text(value: object, *, keep_citations: bool = False, preserve_newlines: bool = False) -> str:
    text = str(value or "")
    text = unicodedata.normalize("NFKC", text)
    for src, dest in _MOJIBAKE_MAP.items():
        text = text.replace(src, dest)
    text = _recover_ligature_placeholders(text)
    text = text.replace("⌈", "ceil(").replace("⌉", ")")
    text = text.replace("⌊", "floor(").replace("⌋", ")")
    text = text.replace("âŒˆ", "ceil(").replace("âŒ‰", ")")
    text = text.replace("âŒŠ", "floor(").replace("âŒ‹", ")")
    for src, dest in _BAD_CHAR_MAP.items():
        text = text.replace(src, dest)

    cleaned_chars: list[str] = []
    for ch in text:
        code = ord(ch)
        if ch in {"\n", "\t"}:
            cleaned_chars.append(ch)
            continue
        if code < 32 or code == 127:
            cleaned_chars.append(" ")
            continue
        cleaned_chars.append(ch)
    text = "".join(cleaned_chars)

    if not keep_citations:
        text = _CITATION_PATTERN.sub("", text)

    if preserve_newlines:
        lines = [" ".join(line.split()).strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
        return "\n".join(line for line in lines if line)
    return " ".join(text.split()).strip()


def _recover_ligature_placeholders(text: str) -> str:
    # Some PDF extractions insert square placeholders where fi/fl ligatures belonged.
    placeholder_chars = {"\u25a0", "\u25aa", "\u25ab", "\ufffd"}
    chars = list(text)
    result: list[str] = []
    for index, ch in enumerate(chars):
        if ch not in placeholder_chars:
            result.append(ch)
            continue

        prev_alpha = ""
        for prev in reversed(result):
            if prev.isalpha():
                prev_alpha = prev.lower()
                break

        next_alpha = ""
        for candidate in chars[index + 1 :]:
            if candidate.isalpha():
                next_alpha = candidate.lower()
                break

        if not prev_alpha or not next_alpha:
            continue
        if next_alpha in {"o", "a", "u"}:
            result.append("fl")
            continue
        if next_alpha in {"n", "r", "l", "t", "x", "m"}:
            result.append("fi")
            continue
        if prev_alpha == "w" and next_alpha == "o":
            result.append("fl")
            continue
        result.append("fi")
    return "".join(result)
