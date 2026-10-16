"""Evaluate the explanations: noise floor, faithfulness, stability, and role analysis.

    python scripts/run_eval.py                 # run every stage, then write the report
    python scripts/run_eval.py --stage report  # redraw plots and summary from saved files

Stages (each saves its raw outputs, and skips work already saved, so a stage can be
resumed after a failure):
  analyses      full analysis of every attempt         -> results/analyses/<id>.json
  faithfulness  deletion test, top-k vs random          -> results/faithfulness.jsonl
  stability     rerun 30 analyses with the same parts   -> results/analyses_rerun/<id>.json
                and re-segment those prompts 3 times    -> results/segmentation_stability.jsonl
  judge         per-part check on every saved answer    -> fills follow_with / follow_without
  rescore       recompute scores from saved answers after a scorer change (no model calls)
  report        CSVs, PNGs, and results/summary.md
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.attribution import ablate_many, analyze, run_prompt  # noqa: E402
from core.challenges import get_challenge  # noqa: E402
from core.config import ROOT, Config, load_config  # noqa: E402
from core.findings import verdict  # noqa: E402
from core.llm import BudgetedLLM, make_llm  # noqa: E402
from core.segment import segment_prompt  # noqa: E402
from core.types import OVERALL, AnalysisResult  # noqa: E402

RESULTS = ROOT / "results"
ATTEMPTS = RESULTS / "attempts.jsonl"
ANALYSES = RESULTS / "analyses"
RERUNS = RESULTS / "analyses_rerun"
FAITH = RESULTS / "faithfulness.jsonl"
SEGSTAB = RESULTS / "segmentation_stability.jsonl"
ERRORS = RESULTS / "eval_errors.jsonl"

KS = (2, 3)
TOPK_RUNS = 2  # fresh runs of the top-k-removed prompt
RANDOM_DRAWS = 5  # random k-subsets, one fresh run each
SEG_REPEATS = 3
GLOBAL_CONCURRENCY = 12

# Palette (see app/styles.css): sage ink for top-k / main series, grey for random, lavender for highlights.
SAGE = "#2F6340"
GREY = "#B5B0A8"
LAVENDER = "#3F3577"
INK = "#2B2A28"
MUTED = "#76726C"
BORDER = "#E8E4DE"


class Limited:
    """Caps in-flight calls across all concurrent analyses."""

    def __init__(self, inner, n: int):
        self.inner, self.model = inner, inner.model
        self.sem = asyncio.Semaphore(n)

    async def complete(self, prompt: str, **kw):
        async with self.sem:
            return await self.inner.complete(prompt, **kw)


class Meter:
    """Totals calls and tokens across a stage."""

    def __init__(self):
        self.calls = self.input_tokens = self.output_tokens = 0

    def add(self, calls: int, tin: int, tout: int) -> None:
        self.calls += calls
        self.input_tokens += tin
        self.output_tokens += tout


def load_attempts() -> list[dict]:
    return [json.loads(line) for line in ATTEMPTS.read_text().splitlines() if line.strip()]


def load_result(path: Path) -> AnalysisResult:
    return AnalysisResult.model_validate_json(path.read_text())


def log_error(stage: str, attempt_id: str, exc: Exception) -> None:
    with ERRORS.open("a") as f:
        f.write(json.dumps({"stage": stage, "id": attempt_id, "error": f"{type(exc).__name__}: {exc}"}) + "\n")
    print(f"  ERROR {stage} {attempt_id}: {type(exc).__name__}: {exc}")


def stability_subset(attempts: list[dict]) -> list[dict]:
    """30 attempts: per challenge, novice 1-4, average 1-3, expert 1-3."""
    take = {"novice": 4, "average": 3, "expert": 3}
    return [a for a in attempts if int(a["id"].rsplit("__", 1)[1]) <= take[a["persona"]]]


# Stage: analyses


async def stage_analyses(attempts, llm, config: Config, out_dir: Path, segments_from: Path | None = None) -> Meter:
    out_dir.mkdir(parents=True, exist_ok=True)
    meter = Meter()
    todo = [a for a in attempts if not (out_dir / f"{a['id']}.json").exists()]
    print(f"{out_dir.name}: {len(attempts) - len(todo)} saved, {len(todo)} to run")
    done = 0

    async def one(a):
        nonlocal done
        ch = get_challenge(a["challenge_id"])
        segs = load_result(segments_from / f"{a['id']}.json").segments if segments_from else None
        try:
            res = await analyze(ch, a["prompt"], llm, config, segments=segs)
        except Exception as e:  # keep going; failures are reported
            log_error(out_dir.name, a["id"], e)
            return
        (out_dir / f"{a['id']}.json").write_text(res.model_dump_json(indent=1))
        meter.add(res.calls, res.input_tokens, res.output_tokens)
        done += 1
        if done % 10 == 0:
            print(f"  {done}/{len(todo)}")

    await asyncio.gather(*(one(a) for a in todo))
    return meter


# Stage: faithfulness


def top_k(res: AnalysisResult, k: int) -> list[int]:
    """Segment ids with the largest |overall attribution|; ties go to the earlier segment."""
    order = sorted(range(len(res.segments)), key=lambda i: (-abs(res.attribution[i][OVERALL]), i))
    return sorted(order[:k])


async def stage_faithfulness(attempts, llm, config: Config) -> Meter:
    done_ids = set()
    if FAITH.exists():
        done_ids = {(r["id"], r["k"]) for r in map(json.loads, FAITH.read_text().splitlines())}
    budget = BudgetedLLM(llm, max_calls=100_000, max_concurrency=GLOBAL_CONCURRENCY)
    jobs = []
    for a in attempts:
        path = ANALYSES / f"{a['id']}.json"
        if not path.exists():
            continue
        res = load_result(path)
        if len(res.segments) < 4:
            continue
        for k in KS:
            if (a["id"], k) not in done_ids:
                jobs.append((a, res, k))
    print(f"faithfulness: {len(done_ids)} saved, {len(jobs)} to run")
    ch_cache = {}

    async def one(a, res, k):
        ch = ch_cache.setdefault(res.challenge_id, get_challenge(res.challenge_id))
        rng = random.Random(f"{a['id']}|{k}")
        ids = list(range(len(res.segments)))
        top = top_k(res, k)
        draws = [sorted(rng.sample(ids, k)) for _ in range(RANDOM_DRAWS)]
        try:
            top_prompt = ablate_many(res.user_prompt, res.segments, top, config.ablation_mode)
            top_runs = await asyncio.gather(*(run_prompt(ch, top_prompt, budget, "faith_top") for _ in range(TOPK_RUNS)))
            rand_runs = await asyncio.gather(
                *(run_prompt(ch, ablate_many(res.user_prompt, res.segments, d, config.ablation_mode), budget, "faith_random") for d in draws)
            )
        except Exception as e:
            log_error("faithfulness", a["id"], e)
            return None
        base = res.baseline_mean[OVERALL]
        top_scores = [r.scores[OVERALL] for r in top_runs]
        rand_scores = [r.scores[OVERALL] for r in rand_runs]
        return {
            "id": a["id"], "challenge_id": res.challenge_id, "persona": a["persona"], "k": k,
            "n_segments": len(res.segments), "baseline": base,
            "top_ids": top, "top_scores": top_scores, "top_drop": base - statistics.fmean(top_scores),
            "random_ids": draws, "random_scores": rand_scores, "random_drop": base - statistics.fmean(rand_scores),
            "top_answers": [r.answer for r in top_runs], "random_answers": [r.answer for r in rand_runs],
        }

    rows = await asyncio.gather(*(one(*j) for j in jobs))
    with FAITH.open("a") as f:
        for r in rows:
            if r:
                f.write(json.dumps(r) + "\n")
    meter = Meter()
    meter.add(budget.calls, budget.input_tokens, budget.output_tokens)
    return meter


# Stage: stability


async def stage_segmentation(subset, llm, config: Config) -> Meter:
    done_ids = set()
    if SEGSTAB.exists():
        done_ids = {r["id"] for r in map(json.loads, SEGSTAB.read_text().splitlines())}
    todo = [a for a in subset if a["id"] not in done_ids]
    print(f"segmentation stability: {len(done_ids)} saved, {len(todo)} to run")
    budget = BudgetedLLM(llm, max_calls=100_000, max_concurrency=GLOBAL_CONCURRENCY)

    async def one(a):
        prompt = a["prompt"].strip()
        outs = await asyncio.gather(
            *(segment_prompt(prompt, budget, config.max_segments, config.segment_max_tokens) for _ in range(SEG_REPEATS))
        )
        return {
            "id": a["id"], "challenge_id": a["challenge_id"],
            "runs": [{"method": m, "spans": [[s.start, s.end] for s in segs], "roles": [s.role for s in segs]} for segs, m in outs],
        }

    rows = await asyncio.gather(*(one(a) for a in todo))
    with SEGSTAB.open("a") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    meter = Meter()
    meter.add(budget.calls, budget.input_tokens, budget.output_tokens)
    return meter


# Stage: judge (per-part check on saved answers)


async def stage_judge(llm, config: Config) -> Meter:
    """Run the per-part check over every saved analysis and rerun that doesn't have it yet."""
    from core.judge import judge_result

    budget = BudgetedLLM(llm, max_calls=100_000, max_concurrency=GLOBAL_CONCURRENCY)
    paths = [p for d in (ANALYSES, RERUNS) if d.exists() for p in sorted(d.glob("*.json"))]
    todo = [p for p in paths if not load_result(p).follow_with]
    print(f"judge: {len(paths) - len(todo)} done, {len(todo)} to run")

    async def one(path: Path):
        res = load_result(path)
        try:
            res = await judge_result(budget, get_challenge(res.challenge_id), res, config.judge_max_tokens)
        except Exception as e:
            log_error("judge", path.stem, e)
            return
        path.write_text(res.model_dump_json(indent=1))

    await asyncio.gather(*(one(p) for p in todo))
    meter = Meter()
    meter.add(budget.calls, budget.input_tokens, budget.output_tokens)
    return meter


# Stage: rescore (after a scorer change; no model calls)


def stage_rescore(attempts, config: Config) -> None:
    """Rescore saved analyses, reruns and faithfulness runs from their saved answers.

    Faithfulness rows whose top-k set changed under the new scores are dropped so the
    faithfulness stage reruns them with fresh calls.
    """
    from core.attribution import rescore, score_answer

    for d in (ANALYSES, RERUNS):
        for path in sorted(d.glob("*.json")) if d.exists() else []:
            res = load_result(path)
            path.write_text(rescore(res, get_challenge(res.challenge_id), config).model_dump_json(indent=1))
        print(f"rescored {d.name}")
    if not FAITH.exists():
        return
    kept = dropped = 0
    rows = []
    for r in map(json.loads, FAITH.read_text().splitlines()):
        res = load_result(ANALYSES / f"{r['id']}.json")
        if top_k(res, r["k"]) != r["top_ids"] or "top_answers" not in r:
            dropped += 1
            continue
        ch = get_challenge(r["challenge_id"])
        r["baseline"] = res.baseline_mean[OVERALL]
        r["top_scores"] = [score_answer(ch, a).scores[OVERALL] for a in r["top_answers"]]
        r["random_scores"] = [score_answer(ch, a).scores[OVERALL] for a in r["random_answers"]]
        r["top_drop"] = r["baseline"] - statistics.fmean(r["top_scores"])
        r["random_drop"] = r["baseline"] - statistics.fmean(r["random_scores"])
        rows.append(r)
        kept += 1
    FAITH.write_text("".join(json.dumps(r) + "\n" for r in rows))
    print(f"faithfulness: rescored {kept}, dropped {dropped} for rerun")


# Stage: report


def _style(ax, *, xgrid=False, ygrid=True):
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(BORDER)
    ax.tick_params(colors=MUTED, labelsize=10)
    ax.yaxis.label.set_color(INK)
    ax.xaxis.label.set_color(INK)
    ax.grid(axis="y" if ygrid and not xgrid else "x", color="#EEECE8", linewidth=0.8)
    ax.set_axisbelow(True)


def _fig(w=7.0, h=4.0):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.family": ["Helvetica Neue", "Arial", "DejaVu Sans"], "font.size": 11})
    fig, ax = plt.subplots(figsize=(w, h), dpi=160)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    return fig, ax, plt


def bootstrap_ci(xs: list[float], n: int = 5000, seed: int = 0) -> tuple[float, float]:
    """95% bootstrap confidence interval for the mean."""
    if len(xs) < 2:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    means = sorted(statistics.fmean(rng.choices(xs, k=len(xs))) for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n) - 1]


def report(config: Config) -> None:
    import pandas as pd
    from scipy import stats

    attempts = {a["id"]: a for a in load_attempts()}
    results = {p.stem: load_result(p) for p in sorted(ANALYSES.glob("*.json"))}
    lines: list[str] = []
    out = lines.append

    # Overview
    n_seg = [len(r.segments) for r in results.values()]
    methods = pd.Series([r.segmentation_method for r in results.values()]).value_counts().to_dict()
    calls = sum(r.calls for r in results.values())
    out("# Evaluation summary\n")
    out(f"Model: {config.model}. Settings: {config.baseline_runs} baseline runs, {config.ablation_runs} runs per removed part, "
        f"noise floor = max({config.noise_floor_k:g} × std, {config.min_noise_floor}).")
    out(f"Attempts: {len(attempts)} synthetic prompts (3 challenges × 3 personas × 10). Analyses completed: {len(results)}.")
    out(f"Parts per prompt: median {statistics.median(n_seg):g}, range {min(n_seg)}–{max(n_seg)}. "
        f"Segmentation: {methods.get('llm', 0)} by the model, {methods.get('fallback', 0)} by the regex fallback.")
    errs = ERRORS.read_text().splitlines() if ERRORS.exists() else []
    out(f"Failed calls or analyses logged: {len(errs)}.\n")

    by_persona = defaultdict(list)
    for aid, r in results.items():
        by_persona[(r.challenge_id, attempts[aid]["persona"])].append(r.baseline_mean[OVERALL])
    out("Mean overall score of the full prompt, by persona (sanity check on the synthetic prompts):\n")
    out("| Challenge | Novice | Average | Expert |\n|---|---|---|---|")
    for cid in ("explain_to_kid", "landlord_reply", "job_extraction"):
        cells = [f"{statistics.fmean(by_persona[(cid, p)]):.2f}" if by_persona[(cid, p)] else "–" for p in ("novice", "average", "expert")]
        out(f"| {cid} | " + " | ".join(cells) + " |")
    out("")

    # A. Noise floor
    rows = []
    for aid, r in results.items():
        for t in r.targets:
            above = [not r.within_noise[s.id][t] for s in r.segments]
            rows.append({"id": aid, "challenge_id": r.challenge_id, "target": t, "baseline_std": r.baseline_std[t],
                         "noise_floor": r.noise[t], "n_segments": len(above), "n_above": sum(above)})
    noise = pd.DataFrame(rows)
    noise.to_csv(RESULTS / "noise_floor.csv", index=False)
    agg = noise.groupby(["challenge_id", "target"]).agg(
        mean_std=("baseline_std", "mean"), median_std=("baseline_std", "median"), max_std=("baseline_std", "max"),
        share_zero_std=("baseline_std", lambda s: (s == 0).mean()), mean_floor=("noise_floor", "mean"),
        segments=("n_segments", "sum"), above=("n_above", "sum"),
    ).reset_index()
    agg["pct_above"] = 100 * agg["above"] / agg["segments"]
    agg.to_csv(RESULTS / "noise_floor_summary.csv", index=False)
    out("## A. Noise floor\n")
    out("Baseline std is the run-to-run spread of a score over 3 runs of the same prompt.\n")
    out("| Challenge | Target | Mean std | Max std | Runs with zero std | Mean floor | Parts above floor |\n|---|---|---|---|---|---|---|")
    for _, row in agg.iterrows():
        out(f"| {row.challenge_id} | {row.target} | {row.mean_std:.3f} | {row.max_std:.3f} | {100 * row.share_zero_std:.0f}% | "
            f"{row.mean_floor:.3f} | {row.above}/{row.segments} ({row.pct_above:.0f}%) |")
    ov = noise[noise.target == OVERALL]
    out(f"\nOverall score: {ov.n_above.sum()} of {ov.n_segments.sum()} parts ({100 * ov.n_above.sum() / ov.n_segments.sum():.0f}%) "
        "had an effect above the noise floor.\n")

    fig, ax, plt = _fig(7.2, 0.32 * len(agg) + 1.0)
    labels = [f"{r.challenge_id} · {r.target}" for _, r in agg.iterrows()]
    data = [noise[(noise.challenge_id == r.challenge_id) & (noise.target == r.target)].baseline_std.values for _, r in agg.iterrows()]
    for i, d in enumerate(data):
        jitter = [i + (j % 7 - 3) * 0.05 for j in range(len(d))]
        ax.scatter(d, jitter, s=12, color=SAGE, alpha=0.55, linewidths=0)
        ax.plot([d.mean(), d.mean()], [i - 0.3, i + 0.3], color=LAVENDER, linewidth=2)
    ax.set_yticks(range(len(labels)), labels)
    ax.invert_yaxis()
    ax.set_xlabel("Baseline std across 3 runs (dots: prompts; line: mean)")
    _style(ax, xgrid=True)
    fig.tight_layout()
    fig.savefig(RESULTS / "noise_floor.png")
    plt.close(fig)

    # B. Faithfulness
    out("## B. Faithfulness (deletion test)\n")
    if FAITH.exists():
        faith = pd.DataFrame([json.loads(x) for x in FAITH.read_text().splitlines()])
        faith = faith.drop_duplicates(subset=["id", "k"], keep="last")
        faith.drop(columns=[c for c in ("top_ids", "random_ids", "top_scores", "random_scores", "top_answers", "random_answers") if c in faith]).to_csv(RESULTS / "faithfulness.csv", index=False)
        out(f"Attempts with at least 4 parts: {faith.id.nunique()}. For each, we removed the top-k parts by |overall attribution| "
            f"together ({TOPK_RUNS} fresh runs) and k random parts ({RANDOM_DRAWS} random draws, one fresh run each), and measured "
            "the drop in overall score from the full prompt.\n")
        out("| k | n | Mean drop, top-k [95% CI] | Mean drop, random [95% CI] | Top-k larger | Wilcoxon p (one-sided) |\n|---|---|---|---|---|---|")
        bars = []
        for k in KS:
            sub = faith[faith.k == k]
            t, r = sub.top_drop.tolist(), sub.random_drop.tolist()
            tci, rci = bootstrap_ci(t), bootstrap_ci(r)
            diffs = [a - b for a, b in zip(t, r)]
            try:
                p = stats.wilcoxon(t, r, alternative="greater").pvalue
            except ValueError:
                p = float("nan")
            wins = sum(d > 0 for d in diffs)
            out(f"| {k} | {len(sub)} | {statistics.fmean(t):.3f} [{tci[0]:.3f}, {tci[1]:.3f}] | {statistics.fmean(r):.3f} "
                f"[{rci[0]:.3f}, {rci[1]:.3f}] | {wins}/{len(diffs)} | {p:.2g} |")
            bars.append((k, statistics.fmean(t), tci, statistics.fmean(r), rci))
        out("")
        for cid in ("explain_to_kid", "landlord_reply", "job_extraction"):
            sub = faith[(faith.challenge_id == cid) & (faith.k == 2)]
            if len(sub):
                out(f"- {cid}, k = 2: top-k drop {sub.top_drop.mean():.3f}, random drop {sub.random_drop.mean():.3f} (n = {len(sub)})")
        out("")

        fig, ax, plt = _fig(6.4, 3.8)
        w = 0.36
        for i, (k, tm, tci, rm, rci) in enumerate(bars):
            for dx, m, ci, color, name in ((-w / 2, tm, tci, SAGE, "Top-k parts"), (w / 2, rm, rci, GREY, "Random parts")):
                ax.bar(i + dx, m, width=w - 0.03, color=color, label=name if i == 0 else None)
                ax.errorbar(i + dx, m, yerr=[[m - ci[0]], [ci[1] - m]], color=INK, capsize=3, linewidth=1)
                ax.text(i + dx, ci[1] + 0.01, f"{m:.2f}", ha="center", va="bottom", fontsize=9, color=INK)
        ax.set_xticks(range(len(bars)), [f"k = {b[0]}" for b in bars])
        ax.set_ylabel("Drop in overall score")
        ax.axhline(0, color=BORDER, linewidth=1)
        top = max(max(b[2][1], b[4][1]) for b in bars)
        ax.set_ylim(0, top * 1.35)
        ax.legend(frameon=False, fontsize=10, labelcolor=INK, loc="upper center", ncol=2)
        ax.set_title("Removing the top-k parts vs. k random parts", fontsize=12, color=INK, loc="left", pad=10)
        _style(ax)
        fig.tight_layout()
        fig.savefig(RESULTS / "faithfulness.png")
        plt.close(fig)
    else:
        out("Not run.\n")

    # C. Stability
    out("## C. Stability\n")
    reruns = {p.stem: load_result(p) for p in sorted(RERUNS.glob("*.json"))} if RERUNS.exists() else {}
    srows = []
    for aid, r2 in reruns.items():
        r1 = results.get(aid)
        if r1 is None:
            continue
        a1 = [r1.attribution[i][OVERALL] for i in range(len(r1.segments))]
        a2 = [r2.attribution[i][OVERALL] for i in range(len(r2.segments))]
        rho = float("nan")
        if len(a1) >= 3 and len(set(a1)) > 1 and len(set(a2)) > 1:
            rho = stats.spearmanr(a1, a2).statistic
        top1 = max(range(len(a1)), key=lambda i: abs(a1[i]))
        top2 = max(range(len(a2)), key=lambda i: abs(a2[i]))
        cleared = not r1.within_noise[top1][OVERALL]
        verdict_match = sum(verdict(r1, i, OVERALL) == verdict(r2, i, OVERALL) for i in range(len(a1)))
        srows.append({"id": aid, "challenge_id": r1.challenge_id, "n_segments": len(a1), "spearman": rho,
                      "top1_same": top1 == top2, "top1_cleared_noise": cleared, "verdict_agreement": verdict_match / len(a1)})
    if srows:
        st = pd.DataFrame(srows)
        st.to_csv(RESULTS / "stability.csv", index=False)
        valid = st.spearman.dropna()
        cl = st[st.top1_cleared_noise]
        out(f"{len(st)} attempts were analyzed a second time with the same parts (fresh model calls).\n")
        out(f"- Spearman correlation of overall attributions between the two runs: mean {valid.mean():.2f}, median {valid.median():.2f} "
            f"(n = {len(valid)}; {len(st) - len(valid)} attempts had fewer than 3 parts or constant attributions).")
        out(f"- Same top-1 part in both runs: {st.top1_same.sum()}/{len(st)} ({100 * st.top1_same.mean():.0f}%). "
            f"Among attempts whose top part cleared the noise floor in run 1: {cl.top1_same.sum()}/{len(cl)}"
            + (f" ({100 * cl.top1_same.mean():.0f}%)." if len(cl) else "."))
        out(f"- Same verdict (helped / hurt / no effect) per part: {100 * st.verdict_agreement.mean():.0f}% of parts.")
        fig, ax, plt = _fig(6.0, 3.4)
        ax.hist(valid, bins=[x / 10 for x in range(-10, 11)], color=SAGE, edgecolor="white", linewidth=1.5)
        ax.axvline(valid.median(), color=LAVENDER, linewidth=2)
        ax.text(valid.median(), ax.get_ylim()[1] * 0.95, f" median {valid.median():.2f}", color=LAVENDER, fontsize=9, va="top")
        ax.set_xlabel("Spearman correlation, run 1 vs run 2")
        ax.set_ylabel("Attempts")
        _style(ax)
        fig.tight_layout()
        fig.savefig(RESULTS / "stability.png")
        plt.close(fig)
    else:
        out("Attribution reruns not run.")
    if SEGSTAB.exists():
        seg = [json.loads(x) for x in SEGSTAB.read_text().splitlines()]
        all_same = sum(all(r["spans"] == s["runs"][0]["spans"] for r in s["runs"]) for s in seg)
        all_same_roles = sum(all(r["spans"] == s["runs"][0]["spans"] and r["roles"] == s["runs"][0]["roles"] for r in s["runs"]) for s in seg)
        pairs = [(a, b) for s in seg for i, a in enumerate(s["runs"]) for b in s["runs"][i + 1 :]]
        pair_same = sum(a["spans"] == b["spans"] for a, b in pairs)
        fb = sum(r["method"] == "fallback" for s in seg for r in s["runs"])
        out(f"- Segmentation: each of {len(seg)} prompts was segmented {SEG_REPEATS} times. Identical boundaries in all {SEG_REPEATS}: "
            f"{all_same}/{len(seg)} ({100 * all_same / len(seg):.0f}%); identical boundaries and roles: {all_same_roles}/{len(seg)} "
            f"({100 * all_same_roles / len(seg):.0f}%). Pairwise identical boundaries: {pair_same}/{len(pairs)} "
            f"({100 * pair_same / len(pairs):.0f}%). Regex fallback used in {fb} of {len(seg) * SEG_REPEATS} segmentations.")
    out("")

    # D. Roles
    rrows = []
    for aid, r in results.items():
        for s in r.segments:
            rrows.append({"id": aid, "challenge_id": r.challenge_id, "persona": attempts[aid]["persona"], "role": s.role,
                          "text": s.display, "attribution": r.attribution[s.id][OVERALL], "abs_attribution": abs(r.attribution[s.id][OVERALL]),
                          "noise_floor": r.noise[OVERALL], "above_noise": not r.within_noise[s.id][OVERALL]})
    roles = pd.DataFrame(rrows)
    roles.to_csv(RESULTS / "segments_by_role.csv", index=False)
    ragg = roles.groupby("role").agg(n=("abs_attribution", "size"), mean_abs=("abs_attribution", "mean"),
                                     pct_above=("above_noise", "mean"), mean_signed=("attribution", "mean")).reset_index()
    ragg["pct_above"] *= 100
    ragg = ragg.sort_values("mean_abs", ascending=False)
    ragg.to_csv(RESULTS / "roles.csv", index=False)
    out("## D. Which prompt parts mattered, by role\n")
    out(f"All {len(roles)} parts from the {len(results)} analyses, grouped by the role the segmenter gave them. "
        "Effect = |overall attribution|.\n")
    out("| Role | Parts | Mean effect | Mean signed effect | Above noise floor |\n|---|---|---|---|---|")
    for _, row in ragg.iterrows():
        out(f"| {row.role} | {row.n} | {row.mean_abs:.3f} | {row.mean_signed:+.3f} | {row.pct_above:.0f}% |")
    out("")

    fig, ax, plt = _fig(7.0, 0.42 * len(ragg) + 1.2)
    ys = range(len(ragg))
    ax.barh(list(ys), ragg.mean_abs, color=SAGE, height=0.62)
    for y, (_, row) in zip(ys, ragg.iterrows()):
        ax.text(row.mean_abs + 0.004, y, f"{row.mean_abs:.2f}  ·  {row.pct_above:.0f}% above noise  ·  n = {row.n}", va="center", fontsize=9, color=INK)
    ax.set_yticks(list(ys), [r.replace("_", " ") for r in ragg.role])
    ax.invert_yaxis()
    ax.set_xlim(0, max(ragg.mean_abs) * 1.9)
    ax.set_xlabel("Mean |overall attribution| (score lost when the part is removed)")
    ax.set_title("Which parts of a prompt changed the score", fontsize=12, color=INK, loc="left")
    _style(ax, xgrid=True)
    fig.tight_layout()
    fig.savefig(RESULTS / "roles.png")
    plt.close(fig)

    # E. Per-part check
    from core.findings import kind

    judged = {aid: r for aid, r in results.items() if r.follow_with}
    out("## E. Per-part check (did the answers do what each part asked?)\n")
    if judged:
        krows = []
        for aid, r in judged.items():
            for s_ in r.segments:
                failed = sum(j is None for j in r.judge_baseline) + sum(j is None for runs in r.judge_ablation for j in runs)
                krows.append({"id": aid, "challenge_id": r.challenge_id, "persona": attempts[aid]["persona"], "role": s_.role,
                              "text": s_.display, "kind": kind(r, s_.id), "follow_with": r.follow_with[s_.id],
                              "follow_without": r.follow_without[s_.id], "failed_judgements": failed})
        kd = pd.DataFrame(krows)
        kd.to_csv(RESULTS / "part_kinds.csv", index=False)
        n_fail = sum(sum(j is None for j in r.judge_baseline) + sum(j is None for runs in r.judge_ablation for j in runs) for r in judged.values())
        n_judge = sum(len(r.judge_baseline) + sum(len(x) for x in r.judge_ablation) for r in judged.values())
        out(f"An AI rated every answer against every part of its prompt (yes / partly / no / n/a). {len(judged)} analyses, "
            f"{n_judge} judged answers, {n_fail} judgements unusable. A part is shown as mattered if the task score dropped "
            "without it, or if answers did it with the part but mostly stopped without it (mean rating gap ≥ 0.5).\n")
        order = ["mattered", "hurt", "anyway", "ignored", "unclear", "quiet"]
        tab = pd.crosstab(kd.role, kd.kind).reindex(columns=order, fill_value=0)
        tab["n"] = tab.sum(axis=1)
        tab = tab.sort_values("n", ascending=False)
        out("| Role | Parts | Mattered | Hurt | AI did it anyway | Ignored | Not clear | Nothing to act on |\n|---|---|---|---|---|---|---|---|")
        for role, row in tab.iterrows():
            cells = " | ".join(f"{100 * row[k] / row.n:.0f}%" for k in order)
            out(f"| {role} | {row.n} | {cells} |")
        tot = kd.kind.value_counts()
        out("\nAll parts: " + ", ".join(f"{k} {tot.get(k, 0)}" for k in order) + f" (of {len(kd)}).")
        by_ch = pd.crosstab(kd.challenge_id, kd.kind).reindex(columns=order, fill_value=0)
        for cid, row in by_ch.iterrows():
            out(f"- {cid}: " + ", ".join(f"{k} {row[k]}" for k in order))
        pairs = [(results[a], reruns[a]) for a in reruns if a in judged and reruns[a].follow_with]
        if pairs:
            same = sum(kind(a, i) == kind(b, i) for a, b in pairs for i in range(len(a.segments)))
            total = sum(len(a.segments) for a, _ in pairs)
            out(f"\nStability: in the {len(pairs)} attempts analyzed twice, {same}/{total} parts ({100 * same / total:.0f}%) got the same verdict both times.")
        out("")
    else:
        out("Not run.\n")

    tin = sum(r.input_tokens for r in results.values())
    tout = sum(r.output_tokens for r in results.values())
    out("## Cost\n")
    out(f"The {len(results)} main analyses used {calls} calls and {tin + tout:,} tokens (~${config.cost_usd(tin, tout):.2f}). "
        "Faithfulness, stability, and segmentation reruns are counted in results/eval_cost.json.")
    (RESULTS / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


async def run_stages(stages: set[str], config: Config) -> None:
    llm = Limited(make_llm(config), GLOBAL_CONCURRENCY)
    attempts = load_attempts()
    cost_path = RESULTS / "eval_cost.json"
    cost = json.loads(cost_path.read_text()) if cost_path.exists() else {}

    def record(name: str, m: Meter) -> None:
        prev = cost.get(name, {"calls": 0, "input_tokens": 0, "output_tokens": 0})
        cost[name] = {k: prev[k] + getattr(m, k) for k in prev}
        cost[name]["usd"] = config.cost_usd(cost[name]["input_tokens"], cost[name]["output_tokens"])
        cost_path.write_text(json.dumps(cost, indent=2))
        print(f"  {name}: +{m.calls} calls, ~${config.cost_usd(m.input_tokens, m.output_tokens):.4f}")

    if "analyses" in stages:
        record("analyses", await stage_analyses(attempts, llm, config, ANALYSES))
    if "faithfulness" in stages:
        record("faithfulness", await stage_faithfulness(attempts, llm, config))
    if "stability" in stages:
        subset = [a for a in stability_subset(attempts) if (ANALYSES / f"{a['id']}.json").exists()]
        record("stability_reruns", await stage_analyses(subset, llm, config, RERUNS, segments_from=ANALYSES))
        record("segmentation_stability", await stage_segmentation(subset, llm, config))
    if "judge" in stages:
        record("judge", await stage_judge(llm, config))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["all", "analyses", "faithfulness", "stability", "judge", "rescore", "report"], default="all")
    args = ap.parse_args()
    config = load_config()
    if args.stage == "rescore":
        stage_rescore(load_attempts(), config)
        report(config)
        return
    stages = {"analyses", "faithfulness", "stability", "judge"} if args.stage == "all" else {args.stage} - {"report"}
    if stages:
        asyncio.run(run_stages(stages, config))
    report(config)


if __name__ == "__main__":
    main()
