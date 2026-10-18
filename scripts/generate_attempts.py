"""Generate synthetic user prompts for the eval: 10 per persona, 3 personas, per challenge.

    python scripts/generate_attempts.py

Writes results/attempts.jsonl with one {id, challenge_id, persona, prompt} per line.
These stand in for real user prompts, so no labeling is needed. Challenges that already
have attempts in the file are skipped, so adding a challenge only generates its prompts.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.challenges import load_all  # noqa: E402
from core.config import ROOT, load_config  # noqa: E402
from core.llm import BudgetedLLM, make_llm  # noqa: E402

OUT = ROOT / "results" / "attempts.jsonl"
PER_PERSONA = 10

PERSONAS = {
    "novice": (
        "a novice who rarely uses AI tools. Their prompts are short and vague, often polite "
        "(please, thanks, could you), and they leave out most of the requirements on the checklist"
    ),
    "average": (
        "an average user. Their prompts state the task and include some of the checklist "
        "requirements, but each one misses one or two of them"
    ),
    "expert": (
        "an expert prompt writer. Their prompts are complete and specific and cover every "
        "requirement on the checklist, each phrased in their own way"
    ),
}

SCHEMA = {
    "type": "object",
    "properties": {"prompts": {"type": "array", "items": {"type": "string"}}},
    "required": ["prompts"],
    "additionalProperties": False,
}

REQUEST = """We are studying how people write prompts for AI assistants. Write {n} different prompts that {persona_desc} might type for this task.

Task the user was given:
{scenario}
{context_note}
Checklist the answer will be scored on (the user can see it):
{checklist}

The user is {persona_desc}.

Rules:
- Write each prompt the way that person would actually type it, in their own words.
- Make the {n} prompts differ from each other in wording, order, and which details they include.
- One to five sentences each. No numbering or quotes around them.
- Do not paste the document; it is attached automatically."""


async def main() -> None:
    config = load_config()
    llm = BudgetedLLM(make_llm(config), max_calls=100, max_concurrency=config.max_concurrency)
    existing = [json.loads(line) for line in OUT.read_text().splitlines() if line.strip()] if OUT.exists() else []
    have = {r["challenge_id"] for r in existing}
    jobs = []
    for ch in load_all():
        if ch.id in have:
            continue
        checklist = "\n".join(f"- {r.label}" for r in ch.requirements)
        note = (
            "\nThe relevant document (an email, lease, or posting) is attached to the prompt automatically.\n"
            if ch.fixed_context
            else ""
        )
        for persona, desc in PERSONAS.items():
            req = REQUEST.format(n=PER_PERSONA, persona_desc=desc, scenario=ch.scenario.strip(), context_note=note, checklist=checklist)
            jobs.append((ch.id, persona, llm.complete(req, kind="generate", max_tokens=config.segment_max_tokens, json_schema=SCHEMA)))

    if not jobs:
        print(f"every challenge already has attempts in {OUT.relative_to(ROOT)}")
        return
    responses = await asyncio.gather(*(j[2] for j in jobs))
    rows = []
    for (cid, persona, _), resp in zip(jobs, responses):
        prompts = [p.strip() for p in json.loads(resp.text)["prompts"] if p.strip()]
        if len(prompts) < PER_PERSONA:
            raise RuntimeError(f"{cid}/{persona}: got {len(prompts)} prompts, expected {PER_PERSONA}")
        for i, p in enumerate(prompts[:PER_PERSONA], 1):
            rows.append({"id": f"{cid}__{persona}__{i:02d}", "challenge_id": cid, "persona": persona, "prompt": p})

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("".join(json.dumps(r) + "\n" for r in existing + rows))
    print(f"added {len(rows)} attempts to {OUT.relative_to(ROOT)}")
    print(f"{llm.calls} calls, ~${config.cost_usd(llm.input_tokens, llm.output_tokens):.4f}")


if __name__ == "__main__":
    asyncio.run(main())
