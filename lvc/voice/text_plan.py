"""Keep OCR, display, pronunciation and lossless synthesis units distinct."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from lvc.vision.text_gate import TextDecision

CHUNKER_VERSION = "sentence-1"
MAX_UNIT_CODEPOINTS = 280
ABBREVIATIONS = frozenset({"Mr.", "Mrs.", "Ms.", "Dr.", "St.", "etc.", "e.g.", "i.e."})
NEGATION = re.compile(r"\b(?:not|never|no|without)\b|n['’]t\b", re.IGNORECASE)
NUMBER = re.compile(r"(?<!\w)\d+(?:[.,]\d+)*(?!\w)")


class TextTooLong(ValueError):
    """A single word exceeds a validated synthesis-unit limit."""


@dataclass(frozen=True)
class LexiconEntry:
    source: str
    spoken: str
    locale: str
    engine: str
    scope: str
    priority: int
    provenance: str
    reviewer: str

    def __post_init__(self) -> None:
        values = (self.source, self.spoken, self.locale, self.engine,
                  self.scope, self.provenance, self.reviewer)
        if any(not isinstance(value, str) or not value
               or value != unicodedata.normalize("NFC", value)
               for value in values):
            raise ValueError("Lexicon entries require NFC text and provenance")
        if type(self.priority) is not int or not -100 <= self.priority <= 100:
            raise ValueError("Lexicon priority is invalid")
        if any(character in self.source + self.spoken for character in "\r\n\t"):
            raise ValueError("Lexicon entries cannot contain controls")
        if NUMBER.findall(self.source) != NUMBER.findall(self.spoken):
            raise ValueError("Pronunciation cannot change numeric tokens")
        if tuple(x.casefold() for x in NEGATION.findall(self.source)) != tuple(
                x.casefold() for x in NEGATION.findall(self.spoken)):
            raise ValueError("Pronunciation cannot change negation")


@dataclass(frozen=True)
class Replacement:
    start: int
    end: int
    source: str
    spoken: str


@dataclass(frozen=True)
class SpeechPlan:
    raw_ocr: str
    accepted_display: str
    speech_text: str
    lexicon_version: str
    lexicon_sha256: str
    replacements: tuple[Replacement, ...]


@dataclass(frozen=True)
class SpeechUnit:
    start: int
    end: int
    text: str


class Lexicon:
    def __init__(self, version: str, entries: tuple[LexiconEntry, ...]):
        if (not isinstance(version, str) or not version
                or not re.fullmatch(r"[A-Za-z0-9._-]+", version)):
            raise ValueError("Lexicon version is required")
        seen: set[tuple[str, str, str, str]] = set()
        for entry in entries:
            key = (entry.locale, entry.engine, entry.scope, entry.source.casefold())
            if key in seen:
                raise ValueError("Ambiguous duplicate lexicon source")
            seen.add(key)
        for index, left in enumerate(entries):
            for right in entries[index + 1:]:
                if (left.locale == right.locale and left.engine == right.engine
                        and left.source.casefold() == right.source.casefold()
                        and (left.scope == "global" or right.scope == "global")
                        and left.priority == right.priority
                        and left.spoken != right.spoken):
                    raise ValueError("Unresolved equal-priority lexicon overlap")
        self.version = version
        self.entries = entries
        payload = json.dumps([asdict(entry) for entry in entries], ensure_ascii=False,
                             sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.sha256 = hashlib.sha256(payload).hexdigest()

    def apply(self, display: str, *, locale: str, engine: str,
              scope: str = "global") -> tuple[str, tuple[Replacement, ...]]:
        eligible = [entry for entry in self.entries if entry.locale == locale
                    and entry.engine == engine and entry.scope in ("global", scope)]
        candidates: list[tuple[int, int, LexiconEntry]] = []
        for entry in eligible:
            pattern = re.compile(r"(?<!\w)" + re.escape(entry.source) + r"(?!\w)",
                                 re.IGNORECASE)
            candidates.extend((match.start(), match.end(), entry)
                              for match in pattern.finditer(display))
        position = 0
        parts: list[str] = []
        applied: list[Replacement] = []
        while True:
            remaining = [item for item in candidates if item[0] >= position]
            if not remaining:
                parts.append(display[position:])
                break
            start = min(item[0] for item in remaining)
            matches = [item for item in remaining if item[0] == start]
            matches.sort(key=lambda item: (-(item[1] - item[0]), -item[2].priority))
            if (len(matches) > 1 and matches[0][1] == matches[1][1]
                    and matches[0][2].priority == matches[1][2].priority
                    and matches[0][2].spoken != matches[1][2].spoken):
                raise ValueError("Ambiguous lexicon overlap")
            end, entry = matches[0][1], matches[0][2]
            parts.extend((display[position:start], entry.spoken))
            applied.append(Replacement(start, end, display[start:end], entry.spoken))
            position = end
        return "".join(parts), tuple(applied)


def load_lexicon(path: Path) -> Lexicon:
    if path.stat().st_size > 65_536:
        raise ValueError("Lexicon exceeds the bounded data size")
    data = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or set(data) != {"version", "entries"}
            or not isinstance(data["entries"], list) or len(data["entries"]) > 256):
        raise ValueError("Invalid lexicon data shape")
    allowed = set(LexiconEntry.__dataclass_fields__)
    entries: list[LexiconEntry] = []
    for row in data["entries"]:
        if not isinstance(row, dict) or set(row) != allowed:
            raise ValueError("Invalid lexicon entry shape")
        entries.append(LexiconEntry(**row))
    return Lexicon(data["version"], tuple(entries))


def prepare_text(raw_ocr: str, accepted_display: str, lexicon: Lexicon,
                 *, locale: str, engine: str, scope: str = "global") -> SpeechPlan:
    if not accepted_display.strip() or accepted_display != unicodedata.normalize(
            "NFC", accepted_display):
        raise ValueError("A nonempty accepted NFC display passage is required")
    speech, replacements = lexicon.apply(accepted_display, locale=locale,
                                         engine=engine, scope=scope)
    return SpeechPlan(raw_ocr, accepted_display, speech, lexicon.version,
                      lexicon.sha256, replacements)


def prepare_accepted_ocr(decision: TextDecision, lexicon: Lexicon, *,
                         locale: str, engine: str, scope: str = "global") -> SpeechPlan:
    if decision.accepted_text is None or decision.reason != "ACCEPTED":
        raise ValueError("OCR has no automatically accepted passage")
    return prepare_text(decision.raw_text, decision.accepted_text, lexicon,
                        locale=locale, engine=engine, scope=scope)


def _boundaries(text: str, start: int) -> list[tuple[int, str]]:
    boundaries: list[tuple[int, str]] = []
    for match in re.finditer(r"\s+", text[start:]):
        end = start + match.end()
        before = text[start:start + match.start()]
        if not before:
            continue
        preceding_word = before.split()[-1]
        kind = "word"
        if (preceding_word.endswith((".", "!", "?"))
                and preceding_word.casefold() not in {word.casefold() for word in ABBREVIATIONS}):
            kind = "sentence"
        elif preceding_word.endswith((",", ";", ":")):
            kind = "clause"
        boundaries.append((end, kind))
    boundaries.append((len(text), "end"))
    return boundaries


def chunk_speech(text: str, *, max_codepoints: int = MAX_UNIT_CODEPOINTS,
                 max_tokens: int | None = None,
                 count_tokens: Callable[[str], int] | None = None) -> tuple[SpeechUnit, ...]:
    if not text or not text.strip() or max_codepoints < 1:
        raise ValueError("Nonempty text and positive unit limit required")
    if (max_tokens is None) != (count_tokens is None):
        raise ValueError("Backend token limit and token counter must be supplied together")
    if max_tokens is not None and max_tokens < 1:
        raise ValueError("Backend token limit must be positive")

    def fits(part: str) -> bool:
        return len(part) <= max_codepoints and (
            max_tokens is None or (count_tokens is not None and count_tokens(part) <= max_tokens))

    position = 0
    units: list[SpeechUnit] = []
    while position < len(text):
        boundaries = _boundaries(text, position)
        usable = [(end, kind) for end, kind in boundaries if end > position
                  and fits(text[position:end])]
        if not usable:
            raise TextTooLong("A word exceeds the synthesis unit limit")
        sentences = [end for end, kind in usable if kind == "sentence"]
        if sentences:
            end = sentences[0]
        elif usable[-1][1] == "end":
            end = usable[-1][0]
        else:
            clauses = [end for end, kind in usable if kind == "clause"]
            end = clauses[-1] if clauses else usable[-1][0]
        units.append(SpeechUnit(position, end, text[position:end]))
        position = end
    assert "".join(unit.text for unit in units) == text
    return tuple(units)
