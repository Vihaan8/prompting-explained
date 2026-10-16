"""Phase 2 go/no-go: run 3 hand-written prompts per challenge and check that an
obvious segment's attribution clears the noise floor.

    python scripts/phase2_checkpoint.py [--ablation-runs N]

Each case names a phrase and the requirement it should drive. The check passes for
a challenge if, in at least one of its prompts, the segment containing that phrase
has attribution >= noise floor for that requirement. Saves every AnalysisResult to
results/phase2/ and a summary to results/phase2/summary.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.attribution import analyze, format_table  # noqa: E402
from core.challenges import get_challenge  # noqa: E402
from core.config import ROOT, load_config  # noqa: E402
from core.llm import make_llm  # noqa: E402

OUT = ROOT / "results" / "phase2"

# (challenge, prompt, phrase in the obvious segment, requirement it should help)
CASES = [
    ("01", "Explain inflation to a 10-year-old. Keep it under 60 words. Use 3 bullet points.", "under 60 words", "length"),
    ("01", "Can you please explain what inflation is? My cousin is 10. Use simple words and exactly 3 bullets. Thanks so much!", "exactly 3 bullets", "bullets"),
    ("01", "You are a friendly teacher. Explain why prices go up, for a kid, in under 60 words, with a candy example.", "under 60 words", "length"),
    ("02", "Write a reply to my landlord disputing the $75 late fee. Mention Section 4.2 and the grace period. Keep it under 120 words.", "under 120 words", "length"),
    ("02", "Help me respond to this email. I paid on the 3rd, which is inside the grace period. Be firm and don't apologize.", "don't apologize", "no_apology"),
    ("02", "Please write a polite email to my landlord about the late fee. Cite the lease section. Thank you!", "Cite the lease section", "cites_facts"),
    ("03", "Turn this job posting into JSON with title, company, location, work_mode, and salary. Use null if a field is missing. Output only JSON.", "Use null if a field is missing", "no_invented_salary"),
    ("03", "Extract the job info as JSON with these keys: title, company, location, work_mode, salary. No code fences.", "No code fences", "json_only"),
    ("03", "Pull the job details into JSON: title, company, location, work_mode, salary. Write work_mode as a single word.", "single word", "accuracy"),
]


async def run_case(i, key, prompt, phrase, req, config, llm, out):
    ch = get_challenge(key)
    try:
        res = await analyze(ch, prompt, llm, config)
    except Exception as e:  # report failures instead of hiding them
        return {"case": i, "challenge": ch.id, "prompt": prompt, "error": f"{type(e).__name__}: {e}"}
    (out / f"case{i:02d}_{ch.id}.json").write_text(res.model_dump_json(indent=2))
    seg = next((s for s in res.segments if phrase.lower() in s.text.lower()), None)
    row = {
        "case": i, "challenge": ch.id, "prompt": prompt, "phrase": phrase, "requirement": req,
        "segments": [(s.role, s.display) for s in res.segments], "segmentation": res.segmentation_method,
        "baseline_mean": res.baseline_mean, "baseline_std": res.baseline_std, "noise": res.noise,
        "calls": res.calls, "input_tokens": res.input_tokens, "output_tokens": res.output_tokens,
        "table": format_table(res),
    }
    if seg is None:
        row.update(found=False, clears_noise=False, note="phrase was split across segments")
    else:
        a = res.attribution[seg.id][req]
        row.update(found=True, segment=seg.display, attribution=a, noise_floor=res.noise[req], clears_noise=a >= res.noise[req])
    return row


async def main(ablation_runs: int) -> None:
    config = load_config(**({"ablation_runs": ablation_runs} if ablation_runs else {}))
    ablation_runs = config.ablation_runs
    llm = make_llm(config)
    out = OUT
    out.mkdir(parents=True, exist_ok=True)
    rows = await asyncio.gather(*(run_case(i, *c, config, llm, out) for i, c in enumerate(CASES, 1)))

    for r in rows:
        print(f"\n=== case {r['case']} [{r['challenge']}] {r['prompt']}")
        if "error" in r:
            print("  ERROR:", r["error"])
            continue
        print(r["table"])
        if r["found"]:
            verdict = "clears" if r["clears_noise"] else "does NOT clear"
            print(f"  check: '{r['segment']}' -> {r['requirement']}: {r['attribution']:+.2f} vs noise {r['noise_floor']:.2f} ({verdict} the floor)")
        else:
            print(f"  check: {r['note']}")

    by_ch: dict[str, bool] = {}
    for r in rows:
        by_ch[r["challenge"]] = by_ch.get(r["challenge"], False) or bool(r.get("clears_noise"))
    calls = sum(r.get("calls", 0) for r in rows)
    tin = sum(r.get("input_tokens", 0) for r in rows)
    tout = sum(r.get("output_tokens", 0) for r in rows)
    go = sum(by_ch.values()) >= 2
    print("\nper challenge (obvious segment clears noise in at least one prompt):", by_ch)
    print(f"checkpoint: {'GO' if go else 'NO-GO'} ({sum(by_ch.values())}/3 challenges)")
    print(f"{calls} calls, {tin} in / {tout} out tokens, ~${config.cost_usd(tin, tout):.4f} ({config.model}, ablation_runs={ablation_runs})")
    (out / "summary.json").write_text(json.dumps(
        {"model": config.model, "ablation_runs": ablation_runs, "go": go, "by_challenge": by_ch, "cases": rows,
         "calls": calls, "input_tokens": tin, "output_tokens": tout}, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--ablation-runs", type=int, default=None, help="default: config.yaml")
    asyncio.run(main(ap.parse_args().ablation_runs))
