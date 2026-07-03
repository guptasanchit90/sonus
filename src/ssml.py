from __future__ import annotations

import re

_MIN_CHARS = 300

_ABBREVIATIONS = frozenset(
    {
        "mr",
        "mrs",
        "ms",
        "dr",
        "prof",
        "sr",
        "jr",
        "st",
        "vs",
        "etc",
        "approx",
        "dept",
        "est",
        "govt",
        "capt",
        "lt",
        "col",
        "gen",
        "sgt",
        "rev",
        "hon",
        "ave",
        "blvd",
        "rd",
        "jan",
        "feb",
        "mar",
        "apr",
        "may",
        "jun",
        "jul",
        "aug",
        "sep",
        "oct",
        "nov",
        "dec",
        "am",
        "pm",
        "inc",
        "ltd",
        "co",
        "corp",
        "llc",
    }
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?。！？])\s+")


def _abbrev_continues(last_word: str) -> bool:
    """True if last_word is an abbreviation suggesting sentence continues."""
    return last_word in _ABBREVIATIONS and last_word not in ("am", "pm", "etc", "vs")


def _split_sentences(text: str) -> list[str]:
    parts = _SENTENCE_SPLIT.split(text.strip())
    sentences: list[str] = []
    buffer = ""
    for part in parts:
        if not part:
            continue
        if buffer:
            buffer += " " + part
        else:
            buffer = part
        lw = _last_word(buffer)
        if lw in _ABBREVIATIONS and _abbrev_continues(lw):
            continue
        sentences.append(buffer)
        buffer = ""
    if buffer:
        sentences.append(buffer)
    return sentences


def _last_word(part: str) -> str:
    stripped = part.rstrip("。！？.!?").strip()
    if not stripped:
        return ""
    return stripped.split()[-1].lower().replace(".", "")


def needs_ssml(text: str) -> bool:
    return len(text) >= _MIN_CHARS


def to_ssml(text: str) -> str:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]

    if len(paragraphs) <= 1:
        sentences = _split_sentences(text.strip())
        inner = "\n  ".join(f"<s>{s.strip()}</s>" for s in sentences if s.strip())
        return f"<speak>\n  {inner}\n</speak>"

    parts = []
    for para in paragraphs:
        sentences = _split_sentences(para)
        inner = "\n    ".join(f"<s>{s.strip()}</s>" for s in sentences)
        parts.append(f"  <p>\n    {inner}\n  </p>")
    return "<speak>\n" + "\n".join(parts) + "\n</speak>"
