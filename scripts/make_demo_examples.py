"""Precompute example analyses for demo mode (2 per challenge).

    python scripts/make_demo_examples.py

Writes demo_examples/<challenge_id>__<n>.json. These are real analyses with the
configured model; demo mode just loads them instead of calling the API.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.attribution import analyze  # noqa: E402
from core.challenges import get_challenge  # noqa: E402
from core.config import ROOT, load_config  # noqa: E402
from core.explain import make_explainer  # noqa: E402
from core.llm import make_llm  # noqa: E402

OUT = ROOT / "demo_examples"

EXAMPLES = {
    "01": [
        "Can you please explain what inflation is? My cousin is 10. Use simple words and exactly 3 bullets. Thanks so much!",
        "You are a friendly teacher. Explain why prices go up, for a kid, in under 60 words, with a candy example.",
    ],
    "02": [
        "Please write a polite email to my landlord about the late fee. Cite the lease section. Thank you!",
        "Write a reply to my landlord disputing the $75 late fee. Mention Section 4.2 and the grace period. Keep it under 120 words.",
    ],
    "03": [
        "Turn this job posting into JSON with title, company, location, work_mode, and salary. Use null if a field is missing. Output only JSON.",
        "Extract the job info as JSON with these keys: title, company, location, work_mode, salary. No code fences.",
    ],
    "04": [
        "summarize this for my boss pls",
        "Give my boss the decision, budget and deadline from these notes in two sentences, under 60 words.",
    ],
    "05": [
        "make a shoping list from this recipe",
        "Shopping list for this recipe. I already have salt, olive oil and oregano. Just the items to buy, one per line.",
    ],
    "06": [
        "subject line?",
        "Write one short subject line for this email. Include the invoice number, no exclamation marks.",
    ],
    "07": [
        "turn this ticket into a bug report",
        "Write a bug report for our public tracker from this ticket. Keep the technical details but remove anything personal about the customer.",
    ],
    "08": [
        "does northside have a pool??",
        "Using only the FAQ, tell me if there's a pool. If it isn't mentioned, say so and don't guess.",
    ],
}


async def main() -> None:
    config = load_config()
    llm = make_llm(config)
    OUT.mkdir(exist_ok=True)
    jobs = [(get_challenge(k), n, p) for k, prompts in EXAMPLES.items() for n, p in enumerate(prompts, 1)]
    results = await asyncio.gather(*(analyze(ch, p, llm, config, explainer=make_explainer(config)) for ch, _, p in jobs))
    await llm.aclose()
    calls = tin = tout = 0
    for (ch, n, _), res in zip(jobs, results):
        path = OUT / f"{ch.id}__{n}.json"
        path.write_text(res.model_dump_json(indent=2))
        calls, tin, tout = calls + res.calls, tin + res.input_tokens, tout + res.output_tokens
        print(f"{path.name}: {res.calls} calls, segmentation={res.segmentation_method}, overall={res.baseline_mean['overall']:.2f}")
    print(f"{calls} calls, {tin} in / {tout} out tokens, ~${config.cost_usd(tin, tout):.4f} ({config.model})")


if __name__ == "__main__":
    asyncio.run(main())
