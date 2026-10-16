"""Check the tool's colors against hand-written expectations.

    python scripts/validate_expectations.py            # run analyses, then compare
    python scripts/validate_expectations.py --report   # compare saved analyses only

results/expectations.yaml lists prompts as parts, each with the color a person would
expect (green / grey / red), written before running. The tool is run with exactly
those parts (no segmentation), and its colors are compared with the expectations.
Writes results/expectations/<task>__<n>.json and results/expectations_report.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import findings as F  # noqa: E402
from core.attribution import analyze  # noqa: E402
from core.challenges import get_challenge  # noqa: E402
from core.config import ROOT, load_config  # noqa: E402
from core.llm import make_llm  # noqa: E402
from core.segment import align  # noqa: E402
from core.types import OVERALL, AnalysisResult, Segment  # noqa: E402

SPEC = ROOT / "results" / "expectations.yaml"
OUT = ROOT / "results" / "expectations"
REPORT = ROOT / "results" / "expectations_report.md"
COLORS = ("green", "grey", "red")
KIND_COLOR = {"mattered": "green", "hurt": "red"}  # everything else is grey


def cases() -> list[dict]:
    spec = yaml.safe_load(SPEC.read_text())
    out = []
    for task, prompts in spec.items():
        for n, p in enumerate(prompts, 1):
            labels = [c for c, _ in p["parts"]]
            texts = [t for _, t in p["parts"]]
            out.append({"id": f"{task}__{n:02d}", "task": task, "labels": labels, "texts": texts, "prompt": " ".join(texts)})
    return out


def segments_for(prompt: str, texts: list[str]) -> list[Segment]:
    spans = align(prompt, texts)
    if spans is None:
        raise ValueError(f"parts don't tile the prompt: {prompt!r}")
    return [Segment(id=i, text=prompt[s:e], role="other", start=s, end=e) for i, (s, e) in enumerate(spans)]


async def run(config) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    llm = make_llm(config)
    todo = [c for c in cases() if not (OUT / f"{c['id']}.json").exists()]
    print(f"{len(todo)} prompts to analyze")

    async def one(c):
        res = await analyze(get_challenge(c["task"]), c["prompt"], llm, config, segments=segments_for(c["prompt"], c["texts"]))
        (OUT / f"{c['id']}.json").write_text(res.model_dump_json(indent=1))
        return res

    results = await asyncio.gather(*(one(c) for c in todo))
    await llm.aclose()
    calls = sum(r.calls for r in results)
    cost = config.cost_usd(sum(r.input_tokens for r in results), sum(r.output_tokens for r in results))
    print(f"{calls} calls, ~${cost:.3f}")


def kappa(pairs: list[tuple[str, str]]) -> float:
    """Cohen's kappa for two label sequences."""
    n = len(pairs)
    po = sum(a == b for a, b in pairs) / n
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum(ca[c] * cb[c] for c in COLORS) / n**2
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


def report() -> None:
    rows, lines = [], []
    for c in cases():
        path = OUT / f"{c['id']}.json"
        if not path.exists():
            continue
        res = AnalysisResult.model_validate_json(path.read_text())
        for i, (want, text) in enumerate(zip(c["labels"], c["texts"])):
            k = F.kind(res, i)
            rows.append({
                "id": c["id"], "task": c["task"], "part": text, "expected": want, "got": KIND_COLOR.get(k, "grey"),
                "kind": k, "score_with": res.baseline_mean[OVERALL], "score_without": res.ablations[i].mean[OVERALL],
                "noise": res.noise[OVERALL], "did_with": res.follow_with[i] if res.follow_with else None,
                "did_without": res.follow_without[i] if res.follow_without else None,
            })
    pairs = [(r["expected"], r["got"]) for r in rows]
    agree = sum(a == b for a, b in pairs)
    out = lines.append
    out("# Expected vs. measured colors\n")
    out(f"{len(rows)} parts in {len({r['id'] for r in rows})} prompts. Expectations were written by hand before the runs "
        "(results/expectations.yaml). The tool was run with exactly those parts.\n")
    out(f"Agreement: {agree}/{len(rows)} ({100 * agree / len(rows):.0f}%). Cohen's kappa: {kappa(pairs):.2f}.\n")
    out("| Expected \\ Measured | green | grey | red |\n|---|---|---|---|")
    for want in COLORS:
        out(f"| {want} | " + " | ".join(str(sum(1 for a, b in pairs if a == want and b == got)) for got in COLORS) + " |")
    out("")
    for task in dict.fromkeys(r["task"] for r in rows):
        sub = [r for r in rows if r["task"] == task]
        ok = sum(r["expected"] == r["got"] for r in sub)
        out(f"- {task}: {ok}/{len(sub)} ({100 * ok / len(sub):.0f}%)")
    out("\n## Disagreements\n")
    out("| Prompt | Part | Expected | Measured | Score with / without (noise) | Did it with / without |\n|---|---|---|---|---|---|")

    def pct(x):
        return "n/a" if x is None else f"{round(100 * x)}%"

    for r in rows:
        if r["expected"] != r["got"]:
            out(f"| {r['id']} | {r['part']} | {r['expected']} | {r['got']} ({r['kind']}) | "
                f"{r['score_with']:.2f} / {r['score_without']:.2f} ({r['noise']:.2f}) | {pct(r['did_with'])} / {pct(r['did_without'])} |")
    REPORT.write_text("\n".join(lines) + "\n")
    (OUT / "rows.json").write_text(json.dumps(rows, indent=1))
    print("\n".join(lines))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true", help="only compare saved analyses")
    args = ap.parse_args()
    if not args.report:
        asyncio.run(run(load_config()))
    report()
