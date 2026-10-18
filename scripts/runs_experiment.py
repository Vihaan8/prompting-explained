"""How many runs are enough? Verdict stability as a function of runs per analysis.

    python scripts/runs_experiment.py            # run what's missing, then write the report
    python scripts/runs_experiment.py --report   # report only, no model calls

For each prompt in the stability subset, this runs the full prompt POOL times and each
shortened prompt POOL times, with the same parts as the main analysis. Then, for each
setting (b full runs, a runs per removed part), it draws two disjoint random subsets of
those runs, scores each subset as its own analysis, and checks whether the two agree:
the same verdict per part (helped / hurt / no effect) and the same top part. Both halves
of a pair come from the same model, so disagreement is run-to-run noise only.

Outputs: results/runs_experiment/<id>.json (the pooled runs), results/runs_experiment.csv,
results/runs_experiment.md, results/runs_experiment.png.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.attribution import analyze, score_runs  # noqa: E402
from core.challenges import get_challenge  # noqa: E402
from core.config import ROOT, load_config  # noqa: E402
from core.llm import make_llm  # noqa: E402
from core.types import OVERALL, AnalysisResult  # noqa: E402
from run_eval import ANALYSES, GREY, INK, LAVENDER, SAGE, Limited, _fig, _style, load_attempts, stability_subset  # noqa: E402

OUT_DIR = ROOT / "results" / "runs_experiment"
POOL = 12  # runs of the full prompt and of each shortened prompt; settings use disjoint halves of these
SETTINGS = [(3, 2), (4, 3), (5, 4), (6, 6)]  # (full-prompt runs, runs per removed part); (3, 2) is the app's setting
DRAWS = 25  # random disjoint pairs per prompt and setting


def verdicts(sc: dict, n_parts: int) -> list[str]:
    out = []
    for i in range(n_parts):
        a, floor = sc["attribution"][i][OVERALL], sc["part_noise"][i][OVERALL]
        out.append("helped" if a >= floor else "hurt" if a <= -floor else "no effect")
    return out


def top_part(sc: dict, n_parts: int) -> int:
    return max(range(n_parts), key=lambda i: (abs(sc["attribution"][i][OVERALL]), -i))


def compare(res: AnalysisResult, b: int, a: int, rng: random.Random, config) -> dict:
    """Score two disjoint subsets of the pooled runs as separate analyses and compare them."""
    ch = get_challenge(res.challenge_id)
    n = len(res.segments)
    base = rng.sample(res.baseline_runs, 2 * b)
    parts = [rng.sample(abl.runs, 2 * a) for abl in res.ablations]
    sc1 = score_runs(ch, base[:b], [p[:a] for p in parts], config)
    sc2 = score_runs(ch, base[b:], [p[a:] for p in parts], config)
    v1, v2 = verdicts(sc1, n), verdicts(sc2, n)
    return {
        "verdict_agreement": sum(x == y for x, y in zip(v1, v2)) / n,
        "top_same": top_part(sc1, n) == top_part(sc2, n) if n > 1 else float("nan"),  # trivial with one part
        "grey_share": (v1.count("no effect") + v2.count("no effect")) / (2 * n),
    }


async def collect(todo: list[dict], config) -> None:
    llm = Limited(make_llm(config), 12)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    done = 0

    async def one(att: dict) -> None:
        nonlocal done
        segs = AnalysisResult.model_validate_json((ANALYSES / f"{att['id']}.json").read_text()).segments
        try:
            res = await analyze(get_challenge(att["challenge_id"]), att["prompt"], llm, config, segments=segs)
        except Exception as e:  # keep going; the report covers what finished
            print(f"  ERROR {att['id']}: {type(e).__name__}: {e}")
            return
        (OUT_DIR / f"{att['id']}.json").write_text(res.model_dump_json(indent=1))
        done += 1
        if done % 10 == 0:
            print(f"  {done}/{len(todo)}")

    await asyncio.gather(*(one(a) for a in todo))


def report(config) -> None:
    import pandas as pd

    results = {p.stem: AnalysisResult.model_validate_json(p.read_text()) for p in sorted(OUT_DIR.glob("*.json"))}
    rows = []
    for aid, res in results.items():
        for b, a in SETTINGS:
            rng = random.Random(f"{aid}|{b}|{a}")
            draws = [compare(res, b, a, rng, config) for _ in range(DRAWS)]
            rows.append({
                "id": aid, "challenge_id": res.challenge_id, "n_parts": len(res.segments), "setting": f"{b}/{a}",
                "calls": b + a * len(res.segments),
                **{k: statistics.fmean(d[k] for d in draws) if len(res.segments) > 1 or k != "top_same" else float("nan") for k in draws[0]},
            })
    df = pd.DataFrame(rows)
    df.to_csv(ROOT / "results" / "runs_experiment.csv", index=False)
    agg = df.groupby("setting", sort=False).agg(
        prompts=("id", "nunique"), calls=("calls", "mean"), verdict=("verdict_agreement", "mean"),
        top=("top_same", "mean"), grey=("grey_share", "mean"),
    )

    lines = [
        "# How many runs are enough?\n",
        f"Model: {config.model}. {agg.prompts.iloc[0]} prompts from the stability subset, "
        f"each run {POOL} times in full and {POOL} times per removed part, with the same parts as the main analysis. "
        f"For each setting, two disjoint random subsets of those runs were scored as separate analyses and compared "
        f"({DRAWS} random pairs per prompt). The app uses 3/2. \"Same top part\" counts only the "
        f"{df[df.n_parts > 1].id.nunique()} prompts with at least 2 parts.\n",
        "| Full runs / runs per part | Task calls per analysis (mean) | Same verdict per part | Same top part | Parts shown as no effect |",
        "|---|---|---|---|---|",
    ]
    for setting, r in agg.iterrows():
        lines.append(f"| {setting} | {r.calls:.1f} | {100 * r.verdict:.0f}% | {100 * r.top:.0f}% | {100 * r.grey:.0f}% |")
    by_task = df.pivot_table(index="challenge_id", columns="setting", values="verdict_agreement", sort=False)
    lines += ["", "Same verdict per part, by task:\n", "| Task | " + " | ".join(by_task.columns) + " |",
              "|---|" + "---|" * len(by_task.columns)]
    for cid, r in by_task.iterrows():
        lines.append(f"| {cid} | " + " | ".join(f"{100 * x:.0f}%" for x in r) + " |")
    (ROOT / "results" / "runs_experiment.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))

    fig, ax, plt = _fig(6.4, 3.8)
    ax.plot(agg.calls, 100 * agg.verdict, marker="o", color=SAGE, linewidth=2, label="Same verdict per part")
    ax.plot(agg.calls, 100 * agg.top, marker="o", color=LAVENDER, linewidth=2, label="Same top part")
    ax.plot(agg.calls, 100 * agg.grey, marker="o", color=GREY, linewidth=2, linestyle="--", label="Parts shown as no effect")
    for (setting, r) in agg.iterrows():
        ax.annotate(setting, (r.calls, 100 * r.verdict), textcoords="offset points", xytext=(0, 8), ha="center", fontsize=9, color=INK)
    ax.set_xlabel("Task calls per analysis (mean)")
    ax.set_ylabel("% of parts / prompts")
    ax.set_ylim(0, 100)
    ax.legend(frameon=False, fontsize=9, labelcolor=INK, loc="lower right")
    ax.set_title("More runs per analysis vs. how often two analyses agree", fontsize=12, color=INK, loc="left", pad=10)
    _style(ax)
    fig.tight_layout()
    fig.savefig(ROOT / "results" / "runs_experiment.png")
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true", help="skip model calls and only write the report")
    args = ap.parse_args()
    config = load_config(baseline_runs=POOL, ablation_runs=POOL, judge_parts=False, max_calls_per_analysis=500)
    if not args.report:
        subset = [a for a in stability_subset(load_attempts()) if (ANALYSES / f"{a['id']}.json").exists()]
        todo = [a for a in subset if not (OUT_DIR / f"{a['id']}.json").exists()]
        print(f"runs experiment: {len(subset) - len(todo)} saved, {len(todo)} to run")
        asyncio.run(collect(todo, config))
    report(load_config())


if __name__ == "__main__":
    main()
