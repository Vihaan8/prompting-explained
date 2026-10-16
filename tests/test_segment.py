import asyncio
import json

from core.llm import BudgetedLLM, FakeLLM
from core.segment import align, fallback_segments, merge_small, segment_prompt, validate_segments
from core.types import Segment

PROMPT = "Please explain inflation to a 10-year-old. Use exactly 3 bullet points, under 60 words. Thank you!"


def _join(segs):
    return "".join(s.text for s in segs)


def test_align_exact_and_whitespace_tolerant():
    parts = ["Please explain inflation to a 10-year-old.", "Use exactly 3 bullet points,", "under 60 words.", "Thank you!"]
    spans = align(PROMPT, parts)
    assert spans is not None
    assert "".join(PROMPT[s:e] for s, e in spans) == PROMPT
    # The model dropped a space and added a newline: still aligns.
    assert align(PROMPT, ["Please explain inflation to a\n10-year-old.", "Use exactly 3 bullet points, under 60 words. Thank you!"])


def test_align_rejects_edits_reorders_and_gaps():
    assert align(PROMPT, ["Please explain inflation to a 10 year old.", "rest"]) is None  # edited
    assert align(PROMPT, ["Thank you!", "Please explain inflation to a 10-year-old."]) is None  # reordered
    assert align(PROMPT, ["Please explain inflation to a 10-year-old."]) is None  # missing the rest
    assert align(PROMPT, []) is None


def test_validate_segments_checks_roles():
    items = [{"text": PROMPT, "role": "task"}]
    assert validate_segments(PROMPT, items)[0].role == "task"
    assert validate_segments(PROMPT, [{"text": PROMPT, "role": "vibes"}]) is None


def test_fallback_reconstructs_and_tags_other():
    segs = fallback_segments(PROMPT)
    assert _join(segs) == PROMPT
    assert all(s.role == "other" for s in segs)
    assert len(segs) == 3  # three sentences


def test_fallback_splits_long_sentences_on_clauses():
    long = "Write a short reply to my landlord, keep it under 120 words and cite the lease section about the grace period; be firm."
    segs = fallback_segments(long)
    assert _join(segs) == long
    assert len(segs) >= 3
    assert any(s.display.startswith("and ") for s in segs)


def _segs(original, parts, roles=None):
    spans = align(original, parts)
    roles = roles or ["other"] * len(parts)
    return [Segment(id=i, text=original[s:e], role=r, start=s, end=e) for i, ((s, e), r) in enumerate(zip(spans, roles))]


def test_merge_small_folds_one_word_segments():
    text = "Hi. Explain inflation simply. Thanks"
    segs = merge_small(text, _segs(text, ["Hi.", "Explain inflation simply.", "Thanks"], ["politeness_filler", "task", "politeness_filler"]))
    assert _join(segs) == text
    assert len(segs) == 1 and segs[0].role == "task"
    assert [s.id for s in segs] == [0]


def test_merge_cap():
    text = " ".join(f"part{i} word." for i in range(15))
    parts = [f"part{i} word." for i in range(15)]
    segs = merge_small(text, _segs(text, parts), max_segments=10)
    assert len(segs) == 10
    assert _join(segs) == text
    assert [s.id for s in segs] == list(range(10))


def _seg_responder(payload):
    def respond(prompt, schema):
        return payload if isinstance(payload, str) else json.dumps(payload)
    return respond


def test_segment_prompt_llm_path():
    payload = {"segments": [
        {"text": "Please", "role": "politeness_filler"},
        {"text": "explain inflation to a 10-year-old.", "role": "task"},
        {"text": "Use exactly 3 bullet points,", "role": "format"},
        {"text": "under 60 words.", "role": "constraint"},
        {"text": "Thank you!", "role": "politeness_filler"},
    ]}
    fake = FakeLLM(_seg_responder(payload))
    budget = BudgetedLLM(fake, max_calls=5)
    segs, method = asyncio.run(segment_prompt(PROMPT, budget))
    assert method == "llm"
    assert _join(segs) == PROMPT
    # "Please" (1 word) is merged into the task segment, which keeps the task role.
    assert [s.role for s in segs] == ["task", "format", "constraint", "politeness_filler"]
    assert budget.calls == 1


def test_segment_prompt_retries_then_falls_back():
    fake = FakeLLM(_seg_responder({"segments": [{"text": "something else entirely", "role": "task"}]}))
    budget = BudgetedLLM(fake, max_calls=5)
    segs, method = asyncio.run(segment_prompt(PROMPT, budget))
    assert method == "fallback"
    assert budget.calls == 2
    assert _join(segs) == PROMPT


def test_segment_prompt_handles_invalid_json():
    fake = FakeLLM(_seg_responder("not json"))
    segs, method = asyncio.run(segment_prompt(PROMPT, BudgetedLLM(fake, max_calls=5)))
    assert method == "fallback"


def test_align_tolerates_dropped_edge_punctuation():
    text = "Explain inflation to a 10-year-old. Keep it under 60 words. Use 3 bullet points."
    for parts in (
        ["Explain inflation", "to a 10-year-old", "Keep it under 60 words", "Use 3 bullet points"],
        ["Explain inflation", " to a 10-year-old", ". Keep it under 60 words", ". Use 3 bullet points", "."],
    ):
        segs = validate_segments(text, [{"text": p, "role": "other"} for p in parts])
        assert segs is not None and len(segs) == 4
        assert _join(segs) == text
        assert segs[1].display == "to a 10-year-old."


def test_align_still_requires_every_word():
    text = "Explain inflation to a 10-year-old. Keep it short."
    assert align(text, ["Explain inflation to a 10-year-old", "Keep it"]) is None
    assert align(text, ["inflation to a 10-year-old", "Keep it short"]) is None


def test_align_attaches_dropped_connector_to_next_part():
    text = "Use simple words and exactly 3 bullets. Be firm and don't apologize."
    segs = validate_segments(text, [{"text": t, "role": "other"} for t in ["Use simple words", "exactly 3 bullets.", "Be firm", "don't apologize."]])
    assert segs is not None
    assert [s.display for s in segs] == ["Use simple words", "and exactly 3 bullets.", "Be firm", "and don't apologize."]
    assert _join(segs) == text
