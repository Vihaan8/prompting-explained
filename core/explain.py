"""Explanations around the attribution numbers.

- what_changed: one plain sentence, written by the model, comparing two answers.
- compare_roles / word_diff: how the user's prompt differs from the reference prompt.
"""

from __future__ import annotations

import difflib
import json
from functools import lru_cache

from .config import ROOT, Config
from .llm import BudgetedLLM
from .scorers import words
from .types import Segment

REFERENCE_SEGMENTS = ROOT / "results" / "reference_segments.json"
REFERENCE_CHECK = ROOT / "results" / "reference_check.json"

# Roles that say nothing about what a prompt is missing.
UNSCORED_ROLES = {"other", "politeness_filler"}

ROLE_NAMES = {
    "role": "role",
    "audience": "audience",
    "task": "task",
    "context": "context",
    "constraint": "constraint",
    "format": "format",
    "tone": "tone",
    "example": "example",
    "politeness_filler": "politeness",
    "other": "other",
}

WHAT_CHANGED_PROMPT = """Below are two answers an AI gave to the same prompt. For the second one, one part of the prompt was removed.

<answer_with_the_part words="{wa}">
{a}
</answer_with_the_part>

<answer_without_the_part words="{wb}">
{b}
</answer_without_the_part>

Write one sentence, under 20 words, describing the biggest visible way the answer without the part differs from the answer with it: length, format, tone, or content. Start with "Without this part, the answer". Write only that sentence."""


def make_explainer(config: Config):
    """Build the async explainer that analyze() calls for the top segments."""

    async def what_changed(llm: BudgetedLLM, original: str, ablated: str) -> str:
        """One model-written sentence describing how the ablated answer differs."""
        resp = await llm.complete(
            WHAT_CHANGED_PROMPT.format(
                a=original.strip() or "(empty)",
                b=ablated.strip() or "(empty)",
                wa=len(words(original)),
                wb=len(words(ablated)),
            ),
            kind="explain",
            max_tokens=config.explain_max_tokens,
        )
        return " ".join(resp.text.split())

    return what_changed


@lru_cache(maxsize=1)
def _reference_segments() -> dict:
    if not REFERENCE_SEGMENTS.exists():
        return {}
    return json.loads(REFERENCE_SEGMENTS.read_text())["challenges"]


@lru_cache(maxsize=1)
def reference_check() -> dict:
    """The saved verify_references.py report, or {} if it hasn't been run."""
    if not REFERENCE_CHECK.exists():
        return {}
    return json.loads(REFERENCE_CHECK.read_text())


def reference_segments(challenge_id: str) -> list[Segment]:
    """The reference prompt's segments, saved by scripts/verify_references.py."""
    entry = _reference_segments().get(challenge_id)
    return [Segment(**s) for s in entry["segments"]] if entry else []


def compare_roles(user: list[Segment], reference: list[Segment]) -> dict[str, list[str]]:
    """Roles in both prompts, only in the reference (missing), and only in the user's (extra)."""
    mine = {s.role for s in user} - UNSCORED_ROLES
    ref = {s.role for s in reference} - UNSCORED_ROLES
    order = list(ROLE_NAMES)
    return {
        "included": [r for r in order if r in mine & ref],
        "missing": [r for r in order if r in ref - mine],
        "extra": [r for r in order if r in mine - ref],
    }


def word_diff(user: str, reference: str) -> list[tuple[str, str]]:
    """Word-level diff as (op, text) pairs. op is 'same', 'yours' (only in yours) or 'reference'."""
    a, b = user.split(), reference.split()
    out: list[tuple[str, str]] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op == "equal":
            out.append(("same", " ".join(a[i1:i2])))
            continue
        if i2 > i1:
            out.append(("yours", " ".join(a[i1:i2])))
        if j2 > j1:
            out.append(("reference", " ".join(b[j1:j2])))
    return out
