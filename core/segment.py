"""Split a prompt into role-tagged segments.

The LLM proposes segments; we then align them back onto the original text so every
segment is an exact character span. Spans make ablation exact: removing a segment
removes precisely those characters and nothing else.
"""

from __future__ import annotations

import json
import re
import string
from typing import Sequence

from .types import ROLES, Segment

SEGMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "role": {"type": "string", "enum": list(ROLES)},
                },
                "required": ["text", "role"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["segments"],
    "additionalProperties": False,
}

SEGMENT_INSTRUCTIONS = """You split prompts into parts so each part can be tested on its own.

Split the prompt between the <prompt> tags into 3 to {max_segments} contiguous parts. Each part is one instruction, phrase, or idea (a clause or short sentence).

Rules:
- Copy each part's text exactly from the prompt, character for character. Do not fix typos, rephrase, or drop words.
- Keep the parts in order. Joined together, the parts must reproduce the whole prompt.
- Give each part one role from this list:
  role: tells the AI who to be ("You are a teacher")
  audience: who the answer is for ("for a 10-year-old")
  task: what to do ("Explain inflation")
  context: background facts or situation
  constraint: a limit or rule (length, words to avoid, what to include)
  format: the shape of the output (bullets, JSON, number of items)
  tone: the voice or attitude (firm, friendly)
  example: a sample or illustration to include
  politeness_filler: courtesy with no instruction ("please", "thank you so much")
  other: anything else

<prompt>
{prompt}
</prompt>"""


def _words(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9]+", text))


_CONNECTOR = r"(?:(?:and|or|but|then|also|plus)\s+)?"


def _flex_pattern(text: str) -> re.Pattern | None:
    """A regex matching `text` with any run of whitespace allowed between its tokens.

    A leading connector word the model dropped ("and", "or", ...) is allowed and
    becomes part of the match, so "and exactly 3 bullets" maps to the part "exactly 3 bullets".
    """
    tokens = text.split()
    if not tokens:
        return None
    return re.compile(_CONNECTOR + r"\s+".join(re.escape(t) for t in tokens))


_EDGE = string.whitespace + string.punctuation
_OPENERS = "([{\"'\u201c\u2018"


def _is_gap(text: str) -> bool:
    """True if `text` holds only whitespace and punctuation."""
    return all(c in _EDGE for c in text)


def align_parts(original: str, parts: Sequence[str]) -> list[tuple[int, int, int]] | None:
    """Map proposed segment texts onto contiguous spans that exactly tile `original`.

    Returns (start, end, part_index) per kept part, or None if the parts are not, in
    order, the whole original prompt. Models often drop or move edge punctuation when
    copying ("Keep it short" for "Keep it short."), so whitespace and punctuation at a
    part's edges are not required to match; they stay in the span of the earlier part.
    Parts that are only punctuation are skipped. Words must match exactly.
    """
    cursor = 0
    starts: list[tuple[int, int]] = []
    for idx, part in enumerate(parts):
        pat = _flex_pattern(part.strip(_EDGE))
        if pat is None:
            continue
        while cursor < len(original) and original[cursor] in _EDGE:
            cursor += 1
        m = pat.match(original, cursor)
        if m is None:
            return None
        start = m.start()
        while start > 0 and original[start - 1] in _OPENERS:
            start -= 1  # an opening bracket or quote belongs to the part it opens
        starts.append((start, idx))
        cursor = m.end()
    if not starts or not _is_gap(original[cursor:]) or not _is_gap(original[: starts[0][0]]):
        return None
    starts[0] = (0, starts[0][1])
    ends = [s for s, _ in starts[1:]] + [len(original)]
    return [(s, e, idx) for (s, idx), e in zip(starts, ends)]


def align(original: str, parts: Sequence[str]) -> list[tuple[int, int]] | None:
    """Spans only; see align_parts."""
    spans = align_parts(original, parts)
    return None if spans is None else [(s, e) for s, e, _ in spans]


def validate_segments(original: str, items: list[dict]) -> list[Segment] | None:
    """Turn LLM output into Segments, or None if it fails reconstruction or role checks."""
    if not items or any(it.get("role") not in ROLES for it in items):
        return None
    spans = align_parts(original, [it.get("text", "") for it in items])
    if spans is None:
        return None
    return [
        Segment(id=i, text=original[s:e], role=items[idx]["role"], start=s, end=e)
        for i, (s, e, idx) in enumerate(spans)
    ]


_SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n+")
_PUNCT_BREAK = re.compile(r"[,;]\s+")  # cut after the punctuation
_AND_BREAK = re.compile(r"(?<=\s)and\s")  # cut before "and" so it starts the next clause
LONG_SENTENCE_WORDS = 12


def fallback_segments(original: str) -> list[Segment]:
    """Regex split on sentence boundaries, then on , ; and ' and ' inside long sentences."""
    cuts = {0}
    sentence_starts = [0] + [m.end() for m in _SENTENCE_END.finditer(original)]
    bounds = sorted(set(sentence_starts)) + [len(original)]
    for s, e in zip(bounds, bounds[1:]):
        cuts.add(s)
        if _words(original[s:e]) > LONG_SENTENCE_WORDS:
            cuts.update(m.end() for m in _PUNCT_BREAK.finditer(original, s, e))
            cuts.update(m.start() for m in _AND_BREAK.finditer(original, s, e))
    points = sorted(c for c in cuts if c < len(original)) + [len(original)]
    spans = [(s, e) for s, e in zip(points, points[1:]) if original[s:e].strip()]
    if not spans:
        spans = [(0, len(original))]
    # Re-tile so the spans cover the whole text with no gaps.
    starts = [0] + [s for s, _ in spans[1:]]
    ends = starts[1:] + [len(original)]
    return [Segment(id=i, text=original[s:e], role="other", start=s, end=e) for i, (s, e) in enumerate(zip(starts, ends))]


def _merge_pair(original: str, a: Segment, b: Segment) -> Segment:
    role = a.role if _words(a.text) >= _words(b.text) else b.role
    return Segment(id=a.id, text=original[a.start : b.end], role=role, start=a.start, end=b.end)


def _renumber(segs: list[Segment]) -> list[Segment]:
    return [s.model_copy(update={"id": i}) for i, s in enumerate(segs)]


def merge_small(original: str, segs: list[Segment], min_words: int = 2, max_segments: int = 10) -> list[Segment]:
    """Merge segments under `min_words` into a neighbor, then cap the count.

    The cap merges the adjacent pair with the fewest combined words until at most
    `max_segments` remain.
    """
    segs = list(segs)
    i = 0
    while len(segs) > 1 and i < len(segs):
        if _words(segs[i].text) < min_words:
            if i > 0:
                segs[i - 1 : i + 1] = [_merge_pair(original, segs[i - 1], segs[i])]
                i -= 1
            else:
                segs[0:2] = [_merge_pair(original, segs[0], segs[1])]
            continue
        i += 1
    while len(segs) > max_segments:
        k = min(range(len(segs) - 1), key=lambda j: _words(segs[j].text) + _words(segs[j + 1].text))
        segs[k : k + 2] = [_merge_pair(original, segs[k], segs[k + 1])]
    return _renumber(segs)


async def segment_prompt(prompt: str, llm, max_segments: int = 10, max_tokens: int = 2000) -> tuple[list[Segment], str]:
    """Segment a prompt with one LLM call, retrying once, then falling back to regex.

    `llm` is a BudgetedLLM. Returns (segments, method) where method is 'llm' or 'fallback'.
    """
    request = SEGMENT_INSTRUCTIONS.format(prompt=prompt, max_segments=max_segments)
    for _ in range(2):
        resp = await llm.complete(request, kind="segment", max_tokens=max_tokens, json_schema=SEGMENT_SCHEMA)
        try:
            items = json.loads(resp.text).get("segments", [])
        except (json.JSONDecodeError, AttributeError):
            continue
        segs = validate_segments(prompt, items)
        if segs is not None:
            return merge_small(prompt, segs, max_segments=max_segments), "llm"
    return merge_small(prompt, fallback_segments(prompt), max_segments=max_segments), "fallback"
