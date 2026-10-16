"""Requirement scorers. Each returns a continuous score in [0, 1].

Continuous scores (partial credit) keep attributions from jumping between 0 and 1
when an answer is just over a limit. A requirement passes at score >= PASS.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

import textstat

PASS = 0.999

_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
_FENCE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.DOTALL)


def _clip(x: float) -> float:
    return max(0.0, min(1.0, x))


def words(text: str) -> list[str]:
    """Whitespace tokens that contain a letter or digit (so bullet markers don't count)."""
    return [w for w in text.split() if re.search(r"[A-Za-z0-9]", w)]


def bullet_lines(text: str) -> list[str]:
    """Lines that start with -, *, •, or a number followed by . or )."""
    return [ln for ln in text.splitlines() if _BULLET.match(ln)]


def strip_bullets(text: str) -> str:
    """Remove bullet markers and markdown emphasis so they don't distort reading level."""
    lines = [_BULLET.sub("", ln) for ln in text.splitlines()]
    return re.sub(r"[*_#`]+", "", "\n".join(lines))


def reading_grade(text: str) -> float:
    """Flesch-Kincaid grade level of the text with bullet markers removed."""
    return float(textstat.flesch_kincaid_grade(strip_bullets(text)))


def word_count_max(text: str, max: int) -> float:
    """1 if the answer has at most `max` words, otherwise falls off linearly."""
    wc = len(words(text))
    if wc <= max:
        return 1.0
    return _clip(1 - (wc - max) / max)


def bullet_count(text: str, target: int) -> float:
    """1 if the answer has exactly `target` bullet lines, less the further it is."""
    n = len(bullet_lines(text))
    return _clip(1 - abs(n - target) / target)


def reading_grade_max(text: str, max_grade: float) -> float:
    """1 if the Flesch-Kincaid grade is at most `max_grade`, 0 at five grades above it."""
    if not words(text):
        return 0.0  # an empty answer is not "readable"; textstat would report grade 0
    g = reading_grade(text)
    if g <= max_grade:
        return 1.0
    return _clip(1 - (g - max_grade) / 5)


def keywords_found(text: str, keywords: list[str]) -> list[str]:
    """Keywords that appear in the text, case-insensitive."""
    low = text.lower()
    return [k for k in keywords if k.lower() in low]


def keywords_present(text: str, keywords: list[str]) -> float:
    """Fraction of keywords that appear in the answer."""
    return len(keywords_found(text, keywords)) / len(keywords)


_NEGATION = re.compile(r"\b(?:not|no|never|without|don't|doesn't|won't|didn't|do not|does not|will not)\s+(?:\w+\s+){0,3}$")


def groups_found(text: str, groups: list[list[str]]) -> list[bool]:
    """For each group of alternatives, whether any of them appears (case-insensitive)."""
    low = text.lower().replace("\u2019", "'")
    return [any(k.lower() in low for k in g) for g in groups]


def keyword_groups_present(text: str, groups: list[list[str]]) -> float:
    """Fraction of groups with at least one alternative present ("Nov 22" or "November 22")."""
    return sum(groups_found(text, groups)) / len(groups)


def item_lines(text: str, groups: list[list[str]], max_words: int = 8) -> int:
    """Short lines (bulleted or plain) that name an item from the groups."""
    n = 0
    for line in text.splitlines():
        core = _BULLET.sub("", line).strip()
        if core and len(words(core)) <= max_words and any(k.lower() in core.lower() for g in groups for k in g):
            n += 1
    return n


def lines_naming(text: str, groups: list[list[str]], max_words: int = 8, at_least: int | None = None,
                 target: int | None = None) -> float:
    """Short lines that each name a list item.

    With at_least: a gate, 1 if there are at least that many (a real list, not tips or a question back).
    With target: 1 for exactly that many lines, less the further off.
    """
    if asks_back(text):
        return 0.0
    n = item_lines(text, groups, max_words)
    if at_least is not None:
        return 1.0 if n >= at_least else 0.0
    return _clip(1 - abs(n - target) / target)


def keywords_used(text: str, keywords: list[str]) -> list[str]:
    """Keywords that appear at least once without a negation just before them.

    "I'm sorry" counts; "a reply that doesn't apologize" (the model describing its own
    answer) does not.
    """
    low = text.lower().replace("\u2019", "'")
    used = []
    for k in keywords:
        k_low = k.lower()
        for m in re.finditer(re.escape(k_low), low):
            if not _NEGATION.search(low[max(0, m.start() - 40) : m.start()]):
                used.append(k)
                break
    return used


def keywords_absent(text: str, keywords: list[str], strict: bool = False) -> float:
    """1 if none of the keywords are used, minus a share for each one that is.

    With strict=True any single use scores 0 (for leaks and made-up claims, where one is enough).
    """
    found = len(keywords_used(text, keywords))
    if strict:
        return 0.0 if found else 1.0
    return _clip(1 - found / len(keywords))


def extract_json(text: str) -> tuple[Any, str]:
    """Parse JSON from an answer. Returns (value, how) where how is 'pure', 'wrapped', or 'none'.

    'wrapped' means JSON was found inside code fences or between other text.
    """
    stripped = text.strip()
    try:
        return json.loads(stripped), "pure"
    except json.JSONDecodeError:
        pass
    candidates = [m.group(1) for m in _FENCE.finditer(text)]
    for open_, close in ("{}", "[]"):
        i, j = text.find(open_), text.rfind(close)
        if 0 <= i < j:
            candidates.append(text[i : j + 1])
    for c in candidates:
        try:
            return json.loads(c.strip()), "wrapped"
        except json.JSONDecodeError:
            continue
    return None, "none"


def _json_object(text: str) -> dict | None:
    value, _ = extract_json(text)
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict):
        value = value[0]
    return value if isinstance(value, dict) else None


def json_only(text: str) -> float:
    """1 for pure JSON, 0.5 for JSON in fences or surrounded by text, 0 if unparseable."""
    value, how = extract_json(text)
    if how == "pure" and isinstance(value, (dict, list)):
        return 1.0
    if how in ("pure", "wrapped") and value is not None:
        return 0.5
    return 0.0


def json_keys_present(text: str, keys: list[str]) -> float:
    """Fraction of the expected keys present in the JSON object (0 if unparseable)."""
    obj = _json_object(text)
    if obj is None:
        return 0.0
    return sum(k in obj for k in keys) / len(keys)


def normalize(value: Any) -> str:
    """Lowercase, punctuation to spaces, collapsed whitespace."""
    s = re.sub(r"[^a-z0-9]+", " ", str(value).lower())
    return " ".join(s.split())


def json_field_matches(text: str, expected: dict[str, str]) -> dict[str, bool]:
    """Per-field match result after normalization."""
    obj = _json_object(text) or {}
    return {k: k in obj and obj[k] is not None and normalize(obj[k]) == normalize(v) for k, v in expected.items()}


def json_field_accuracy(text: str, expected: dict[str, str]) -> float:
    """Fraction of expected fields whose value matches after normalization."""
    if _json_object(text) is None:
        return 0.0
    matches = json_field_matches(text, expected)
    return sum(matches.values()) / len(matches)


_NULL_WORDS = {
    "", "null", "none", "n a", "na", "nil", "unknown", "unspecified", "not specified",
    "not provided", "not listed", "not mentioned", "not stated", "not available",
    "not disclosed", "not given", "not included", "tbd", "not specified in posting",
}
_NOT_PHRASE = re.compile(r"\bnot\s+(specified|provided|listed|mentioned|stated|available|disclosed|given|included)\b")


def is_null_like(value: Any) -> bool:
    """True for null, empty, and 'not specified'-style values, including nested ones."""
    if value is None:
        return True
    if isinstance(value, dict):
        return all(is_null_like(v) for v in value.values())
    if isinstance(value, list):
        return all(is_null_like(v) for v in value)
    if isinstance(value, (int, float)):
        return False
    s = normalize(value)
    if re.search(r"\d", s):
        return False
    return s in _NULL_WORDS or bool(_NOT_PHRASE.search(s))


def json_field_null(text: str, field: str) -> float:
    """1 if `field` is absent or null-like, 0 if it holds a value (or the JSON can't be parsed)."""
    obj = _json_object(text)
    if obj is None:
        return 0.0
    return 1.0 if is_null_like(obj.get(field)) else 0.0


_CLARIFY = re.compile(
    r"could you (tell|share|clarify|provide|paste|let)|can you (tell|share|clarify|provide|paste)|what would you like|"
    r"what you'?d like|let me know (what|which)|(got|was) cut off|came through without|missing what|"
    r"which (topic|email|posting|document)|not sure what .{0,20} refers? to"
)
CLARIFY_MAX_WORDS = 90


def asks_back(text: str) -> bool:
    """True if a short answer mostly asks the user a clarifying question instead of doing the task."""
    return len(words(text)) < CLARIFY_MAX_WORDS and bool(_CLARIFY.search(text.lower().replace("\u2019", "'")))


def on_topic(text: str, any_of: list[str]) -> float:
    """1 if the answer mentions at least one topic word and isn't a question back, else 0."""
    if asks_back(text):
        return 0.0
    low = text.lower()
    return 1.0 if any(re.search(rf"\b{re.escape(k.lower())}", low) for k in any_of) else 0.0


def starts_line_with(text: str, any_of: list[str]) -> float:
    """1 if some line starts with one of the given words (e.g. a greeting), and it isn't a question back."""
    if asks_back(text):
        return 0.0
    pat = re.compile(r"^\s*(?:" + "|".join(re.escape(k.lower()) for k in any_of) + r")\b", re.M)
    return 1.0 if pat.search(text.lower()) else 0.0


SCORERS: dict[str, Callable[..., float]] = {
    "on_topic": on_topic,
    "starts_line_with": starts_line_with,
    "word_count_max": word_count_max,
    "bullet_count": bullet_count,
    "reading_grade_max": reading_grade_max,
    "keywords_present": keywords_present,
    "keyword_groups_present": keyword_groups_present,
    "lines_naming": lines_naming,
    "keywords_absent": keywords_absent,
    "json_only": json_only,
    "json_keys_present": json_keys_present,
    "json_field_accuracy": json_field_accuracy,
    "json_field_null": json_field_null,
}


def score(scorer: str, text: str, params: dict[str, Any]) -> float:
    """Run a registered scorer by name."""
    return SCORERS[scorer](text, **params)
