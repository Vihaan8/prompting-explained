"""Check that every reference prompt passes all requirements on 5 of 5 runs.

Also segments each reference prompt once and saves the result for the
prompt-components comparison in the UI.

    python scripts/verify_references.py [--runs 5]

Writes results/reference_check.json and results/reference_segments.json.
Exits with status 1 if any reference fails, so the prompt can be revised.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.attribution import run_prompt  # noqa: E402
from core.challenges import load_all  # noqa: E402
from core.config import ROOT, load_config  # noqa: E402
from core.llm import BudgetedLLM, make_llm  # noqa: E402
from core.scorers import PASS  # noqa: E402
from core.segment import segment_prompt  # noqa: E402

RESULTS = ROOT / "results"


async def main(runs: int) -> int:
    config = load_config()
    llm = make_llm(config)
    budget = BudgetedLLM(llm, max_calls=10_000, max_concurrency=config.max_concurrency)
    report, segments, failed = {}, {}, []

    for ch in load_all():
        results = await asyncio.gather(*(run_prompt(ch, ch.reference_prompt, budget, "reference") for _ in range(runs)))
        passes = {r.id: sum(res.scores[r.id] >= PASS for res in results) for r in ch.requirements}
        ok = all(n == runs for n in passes.values())
        print(f"\n[{ch.id}] {'PASS' if ok else 'FAIL'}")
        for i, res in enumerate(results, 1):
            cells = "  ".join(f"{r.id}={res.scores[r.id]:.2f}" for r in ch.requirements)
            print(f"  run {i}: {cells}")
        for r in ch.requirements:
            print(f"  {r.label}: {passes[r.id]}/{runs}")
        if not ok:
            failed.append(ch.id)
            print("  first failing answer:")
            bad = next(res for res in results if res.scores["overall"] < PASS)
            print("    " + bad.answer.replace("\n", "\n    "))
        report[ch.id] = {
            "reference_prompt": ch.reference_prompt,
            "runs": runs,
            "passes": passes,
            "all_passed": ok,
            "answers": [res.answer for res in results],
            "scores": [res.scores for res in results],
        }
        segs, method = await segment_prompt(
            ch.reference_prompt, budget, max_segments=config.max_segments, max_tokens=config.segment_max_tokens
        )
        segments[ch.id] = {"method": method, "segments": [s.model_dump() for s in segs]}

    RESULTS.mkdir(exist_ok=True)
    meta = {"model": config.model, "calls": budget.calls, "input_tokens": budget.input_tokens, "output_tokens": budget.output_tokens}
    (RESULTS / "reference_check.json").write_text(json.dumps({"meta": meta, "challenges": report}, indent=2))
    (RESULTS / "reference_segments.json").write_text(json.dumps({"meta": meta, "challenges": segments}, indent=2))
    cost = config.cost_usd(budget.input_tokens, budget.output_tokens)
    print(f"\n{budget.calls} calls, {budget.input_tokens} in / {budget.output_tokens} out tokens, ~${cost:.4f} ({config.model})")
    if failed:
        print(f"References that need revising: {', '.join(failed)}")
        return 1
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=5)
    sys.exit(asyncio.run(main(ap.parse_args().runs)))
