"""Per-part check: does an answer do what each part of the prompt asked?

One model call reads one answer and rates every part of the user's prompt:
yes (1.0), partly (0.5), no (0.0), or n/a (the part gives nothing to act on, such as
"thanks"). Comparing the ratings for answers with and without a part shows whether
that part is why the answer does something, or whether the AI did it anyway.
"""

from __future__ import annotations

import json

from .types import Challenge, Segment

RATING = {"yes": 1.0, "partly": 0.5, "no": 0.0, "n/a": None}

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "ratings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "part": {"type": "integer"},
                    "rating": {"type": "string", "enum": list(RATING)},
                },
                "required": ["part", "rating"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["ratings"],
    "additionalProperties": False,
}

JUDGE_PROMPT = """Someone wrote a prompt for an AI. It is split into numbered parts below.{document}

<prompt_parts>
{parts}
</prompt_parts>

<answer>
{answer}
</answer>

For each part, rate whether the answer does what that part asks for or says:
- yes: the answer clearly does it or includes it
- partly: only some of it
- no: the answer doesn't do it
- n/a: the part gives nothing the answer could act on: courtesy ("please", "thanks"), a greeting, a side remark that doesn't bear on the answer, or gibberish with no clear meaning (like "asdkjh")

Rate every part on its own, even if the answer seems to come from a version of the prompt that didn't include it. Return one rating per part."""


def judge_request(challenge: Challenge, segments: list[Segment], answer: str) -> str:
    """The judge prompt for one answer."""
    doc = (
        f"\n\nThis document was attached to the prompt:\n<document>\n{challenge.fixed_context.strip()}\n</document>"
        if challenge.fixed_context
        else ""
    )
    parts = "\n".join(f"{s.id + 1}. {s.display}" for s in segments)
    return JUDGE_PROMPT.format(document=doc, parts=parts, answer=answer.strip())


def parse_ratings(text: str, n_parts: int) -> list[float | None] | None:
    """Ratings in part order, or None if the judge's output can't be used."""
    try:
        items = json.loads(text)["ratings"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
    out: list[float | None] = [None] * n_parts
    seen = set()
    for it in items:
        i = it.get("part", 0) - 1
        if 0 <= i < n_parts and it.get("rating") in RATING:
            out[i] = RATING[it["rating"]]
            seen.add(i)
    return out if len(seen) == n_parts else None


async def judge_answer(llm, challenge: Challenge, segments: list[Segment], answer: str, max_tokens: int = 600) -> list[float | None] | None:
    """Rate one answer against every part. An empty answer follows nothing."""
    if not answer.strip():
        return [0.0] * len(segments)
    resp = await llm.complete(
        judge_request(challenge, segments, answer), kind="judge", max_tokens=max_tokens, json_schema=JUDGE_SCHEMA
    )
    return parse_ratings(resp.text, len(segments))


def mean_rating(ratings: list[list[float | None] | None], part: int) -> float | None:
    """Mean rating of one part over several answers, ignoring n/a and failed judgements."""
    vals = [r[part] for r in ratings if r is not None and r[part] is not None]
    return sum(vals) / len(vals) if vals else None


FOLLOWED = 0.5  # mean rating at or above this counts as "the answer does it"
NEEDED_GAP = 0.5  # with minus without at or above this means the part is why the answer does it


def part_status(with_: float | None, without: float | None) -> str | None:
    """'needed', 'anyway', 'ignored', or None when the part gives nothing to act on."""
    if with_ is None:
        return None
    if with_ < FOLLOWED:
        return "ignored"
    if without is not None and with_ - without >= NEEDED_GAP:
        return "needed"
    return "anyway"


async def judge_result(llm, challenge: Challenge, result, max_tokens: int = 600):
    """Rate every saved answer of an AnalysisResult and fill in its per-part fields."""
    import asyncio

    segs = result.segments
    base = await asyncio.gather(*(judge_answer(llm, challenge, segs, r.answer, max_tokens) for r in result.baseline_runs))
    abl = await asyncio.gather(
        *(asyncio.gather(*(judge_answer(llm, challenge, segs, r.answer, max_tokens) for r in a.runs)) for a in result.ablations)
    )
    abl = [list(x) for x in abl]
    return result.model_copy(update={
        "judge_baseline": list(base),
        "judge_ablation": abl,
        "follow_with": [mean_rating(list(base), s.id) for s in segs],
        "follow_without": [mean_rating(abl[s.id], s.id) for s in segs],
    })
