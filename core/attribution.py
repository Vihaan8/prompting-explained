"""Occlusion (leave-one-out) attribution over prompt segments.

For each segment we remove it, rerun the prompt, and compare scores:
    attribution[segment][target] = baseline_mean[target] - ablated_mean[segment][target]
Positive means the segment helped (removing it made the answer worse). Effects smaller
than the noise floor, estimated from reruns of the full prompt, are flagged.

CLI:  python -m core.attribution --challenge 01 --prompt "Explain inflation..."
"""

from __future__ import annotations

import argparse
import asyncio
import math
import re
import statistics
from pathlib import Path
from typing import Awaitable, Callable

from .challenges import get_challenge
from .config import Config, load_config
from .judge import judge_result, part_status
from .llm import LLM, BudgetedLLM, make_llm
from .scorers import score
from .segment import segment_prompt
from .types import OVERALL, Ablation, AnalysisResult, Challenge, RunResult, Segment

FILLER = "[...]"

Progress = Callable[[str, int, int], None]
# explainer(llm, original_answer, ablated_answer) -> one plain sentence
Explainer = Callable[[BudgetedLLM, str, str], Awaitable[str]]


def build_prompt(user_text: str, fixed_context: str | None) -> str:
    """The text sent to the model: the user's prompt, then the attached document if any."""
    if fixed_context:
        return f"{user_text}\n\n<document>\n{fixed_context.strip()}\n</document>"
    return user_text


def _tidy(text: str) -> str:
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def ablate_many(prompt: str, segments: list[Segment], seg_ids, mode: str = "delete") -> str:
    """The user's prompt with several segments deleted (or replaced by '[...]' in filler mode)."""
    drop = set(seg_ids)
    out = []
    for seg in segments:
        if seg.id not in drop:
            out.append(prompt[seg.start : seg.end])
        elif mode == "filler":
            lead = seg.text[: len(seg.text) - len(seg.text.lstrip())]
            trail = seg.text[len(seg.text.rstrip()) :]
            out.append(lead + FILLER + trail)
    return _tidy("".join(out))


def ablate(prompt: str, segments: list[Segment], seg_id: int, mode: str = "delete") -> str:
    """The user's prompt with one segment deleted, or replaced by '[...]' in filler mode."""
    return ablate_many(prompt, segments, [seg_id], mode)


def score_answer(challenge: Challenge, answer: str, stop_reason: str | None = None) -> RunResult:
    """Score one answer on every requirement.

    'overall' is the mean of the regular requirements, multiplied by every gate
    requirement (did the answer actually do the task). A non-answer scores 0.
    """
    scores = {r.id: score(r.scorer, answer, r.params) for r in challenge.requirements}
    regular = [scores[r.id] for r in challenge.requirements if not r.gate]
    gate = math.prod(scores[r.id] for r in challenge.requirements if r.gate)
    scores[OVERALL] = gate * (statistics.fmean(regular) if regular else 1.0)
    return RunResult(answer=answer, scores=scores, stop_reason=stop_reason)


def _mean(runs: list[RunResult], targets: list[str]) -> dict[str, float]:
    return {t: statistics.fmean(r.scores[t] for r in runs) for t in targets}


def _std(runs: list[RunResult], targets: list[str]) -> dict[str, float]:
    """Sample standard deviation (0 for a single run)."""
    if len(runs) < 2:
        return {t: 0.0 for t in targets}
    return {t: statistics.stdev(r.scores[t] for r in runs) for t in targets}


def noise_floor(std: dict[str, float], k: float, minimum: float) -> dict[str, float]:
    """noise[t] = max(k * std[t], minimum)."""
    return {t: max(k * s, minimum) for t, s in std.items()}


def pooled_std(groups: list[list[RunResult]], targets: list[str]) -> dict[str, float]:
    """Run-to-run spread pooled over every group of repeated runs (reported in the eval only)."""
    out = {}
    for t in targets:
        num = den = 0.0
        for g in groups:
            if len(g) > 1:
                num += (len(g) - 1) * statistics.variance(r.scores[t] for r in g)
                den += len(g) - 1
        out[t] = (num / den) ** 0.5 if den else 0.0
    return out


def diff_noise(baseline: list[RunResult], ablated: list[RunResult], targets: list[str], k: float, minimum: float) -> dict[str, float]:
    """Noise floor for one part: k standard errors of (mean with it - mean without it).

    SE = sqrt(var_with / n_with + var_without / n_without). It uses only the full prompt's
    runs and this part's own runs, so a part whose removal makes answers erratic doesn't
    raise the bar for every other part.
    """
    out = {}
    for t in targets:
        vb = statistics.variance(r.scores[t] for r in baseline) if len(baseline) > 1 else 0.0
        va = statistics.variance(r.scores[t] for r in ablated) if len(ablated) > 1 else 0.0
        se = (vb / len(baseline) + va / max(1, len(ablated))) ** 0.5
        out[t] = max(k * se, minimum)
    return out


async def run_prompt(challenge: Challenge, user_text: str, llm: BudgetedLLM, kind: str) -> RunResult:
    """Send one prompt (with the fixed context attached) and score the answer.

    An empty user prompt with no attached document is scored as an empty answer
    without calling the model.
    """
    if not user_text.strip() and not challenge.fixed_context:
        return score_answer(challenge, "", stop_reason="empty_prompt")
    resp = await llm.complete(build_prompt(user_text, challenge.fixed_context), kind=kind)
    return score_answer(challenge, resp.text, resp.stop_reason)


async def analyze(
    challenge: Challenge,
    user_prompt: str,
    llm: LLM,
    config: Config,
    *,
    segments: list[Segment] | None = None,
    explainer: Explainer | None = None,
    progress: Progress | None = None,
) -> AnalysisResult:
    """Run the full pipeline: segment, baseline, noise floor, occlusion, attribution.

    Pass `segments` to skip segmentation (used by tests and the stability eval).
    Raises BudgetExceeded before making task calls if the analysis would exceed
    `max_calls_per_analysis`.
    """
    user_prompt = user_prompt.strip()
    if not user_prompt:
        raise ValueError("the prompt is empty")
    budget = BudgetedLLM(llm, config.max_calls_per_analysis, config.max_concurrency)
    targets = challenge.targets

    if segments is None:
        if progress:
            progress("segment", 0, 1)
        segments, method = await segment_prompt(
            user_prompt, budget, max_segments=config.max_segments, max_tokens=config.segment_max_tokens
        )
    else:
        method = "given"
    n_explain = min(config.explain_top_n, len(segments)) if explainer else 0
    n_runs = config.baseline_runs + len(segments) * config.ablation_runs
    budget.reserve(n_runs + (n_runs if config.judge_parts else 0) + n_explain)

    total = {"baseline": config.baseline_runs, "ablation": len(segments) * config.ablation_runs}
    done = {"baseline": 0, "ablation": 0}

    async def tracked(stage: str, coro: Awaitable[RunResult]) -> RunResult:
        result = await coro
        done[stage] += 1
        if progress:
            progress(stage, done[stage], total[stage])
        return result

    ablated_prompts = [ablate(user_prompt, segments, s.id, config.ablation_mode) for s in segments]
    baseline_tasks = [tracked("baseline", run_prompt(challenge, user_prompt, budget, "baseline")) for _ in range(config.baseline_runs)]
    ablation_tasks = [
        tracked("ablation", run_prompt(challenge, p, budget, "ablation"))
        for p in ablated_prompts
        for _ in range(config.ablation_runs)
    ]
    results = await asyncio.gather(*baseline_tasks, *ablation_tasks)
    baseline = list(results[: config.baseline_runs])
    ablation_runs = list(results[config.baseline_runs :])

    groups = [ablation_runs[s.id * config.ablation_runs : (s.id + 1) * config.ablation_runs] for s in segments]
    sc = score_runs(challenge, baseline, groups, config)
    base_mean, attribution, within = sc["baseline_mean"], sc["attribution"], sc["within_noise"]
    ablations = [Ablation(segment_id=s.id, prompt=p, runs=g, mean=m) for s, p, g, m in zip(segments, ablated_prompts, groups, sc["means"])]

    result = AnalysisResult(
        challenge_id=challenge.id,
        user_prompt=user_prompt,
        final_prompt=build_prompt(user_prompt, challenge.fixed_context),
        segments=segments,
        segmentation_method=method,
        targets=targets,
        baseline_runs=baseline,
        baseline_mean=base_mean,
        baseline_std=sc["baseline_std"],
        pooled_std=sc["pooled_std"],
        noise=sc["noise"],
        part_noise=sc["part_noise"],
        ablations=ablations,
        attribution=attribution,
        within_noise=within,
        model=getattr(llm, "model", ""),
        config=config.model_dump(),
    )

    if config.judge_parts:
        if progress:
            progress("judge", 0, n_runs)
        result = await judge_result(budget, challenge, result, config.judge_max_tokens)

    if explainer and n_explain:
        # Explain the parts that mattered: by the task checks first, then by the per-part check.
        by_score = sorted((s for s in segments if not within[s.id][OVERALL]), key=lambda s: -abs(attribution[s.id][OVERALL]))
        by_judge = [
            s for s in segments
            if result.follow_with and part_status(result.follow_with[s.id], result.follow_without[s.id]) == "needed"
        ]
        top_ids = list(dict.fromkeys(s.id for s in by_score + by_judge))[:n_explain]
        top = [segments[i] for i in top_ids]
        if top:
            if progress:
                progress("explain", 0, len(top))
            sentences = await asyncio.gather(
                *(explainer(budget, baseline[0].answer, ablations[s.id].runs[0].answer) for s in top)
            )
            result.explanations = {s.id: text for s, text in zip(top, sentences)}

    result.call_counts = dict(budget.by_kind)
    result.calls = budget.calls
    result.input_tokens = budget.input_tokens
    result.output_tokens = budget.output_tokens
    return result


def score_runs(
    challenge: Challenge, baseline: list[RunResult], ablation_runs: list[list[RunResult]], config: Config
) -> dict:
    """Means, std, noise floor, attribution and noise flags from scored runs."""
    targets = challenge.targets
    base_mean, base_std = _mean(baseline, targets), _std(baseline, targets)
    pooled = pooled_std([baseline, *ablation_runs], targets)
    noise = noise_floor(base_std, config.noise_floor_k, config.min_noise_floor)  # full prompt only, for reference
    part_noise = [diff_noise(baseline, runs, targets, config.noise_floor_k, config.min_noise_floor) for runs in ablation_runs]
    means = [_mean(runs, targets) for runs in ablation_runs]
    attribution = [{t: base_mean[t] - m[t] for t in targets} for m in means]
    within = [{t: abs(a[t]) < pn[t] for t in targets} for a, pn in zip(attribution, part_noise)]
    return {"baseline_mean": base_mean, "baseline_std": base_std, "pooled_std": pooled, "noise": noise,
            "part_noise": part_noise, "means": means, "attribution": attribution, "within_noise": within}


def rescore(result: AnalysisResult, challenge: Challenge, config: Config) -> AnalysisResult:
    """Recompute every score and attribution from the saved answers, with no model calls.

    Used when a scorer changes: the answers stay the same, only their scores move.
    """
    baseline = [score_answer(challenge, r.answer, r.stop_reason) for r in result.baseline_runs]
    ablated = [[score_answer(challenge, r.answer, r.stop_reason) for r in a.runs] for a in result.ablations]
    s = score_runs(challenge, baseline, ablated, config)
    ablations = [a.model_copy(update={"runs": runs, "mean": m}) for a, runs, m in zip(result.ablations, ablated, s["means"])]
    return result.model_copy(update={
        "targets": challenge.targets, "baseline_runs": baseline, "baseline_mean": s["baseline_mean"],
        "baseline_std": s["baseline_std"], "pooled_std": s["pooled_std"], "noise": s["noise"],
        "part_noise": s["part_noise"], "ablations": ablations,
        "attribution": s["attribution"], "within_noise": s["within_noise"],
    })


def format_table(result: AnalysisResult) -> str:
    """Plain-text table of attributions for the CLI. '~' marks values within noise."""
    targets = result.targets
    lines = []
    lines.append("baseline mean: " + "  ".join(f"{t}={result.baseline_mean[t]:.2f}" for t in targets))
    lines.append("noise floor:   " + "  ".join(f"{t}={result.noise[t]:.2f}" for t in targets))
    lines.append("")
    lines.append(f"{'#':>2}  {'role':<17} " + " ".join(f"{t[:12]:>13}" for t in targets) + "  segment")
    for s in result.segments:
        cells = []
        for t in targets:
            v = result.attribution[s.id][t]
            mark = "~" if result.within_noise[s.id][t] else " "
            cells.append(f"{v:+12.2f}{mark}")
        text = s.display if len(s.display) <= 60 else s.display[:57] + "..."
        lines.append(f"{s.id:>2}  {s.role:<17} " + " ".join(cells) + f"  {text}")
    lines.append("")
    lines.append(
        f"segmentation: {result.segmentation_method} | calls: {result.calls} {result.call_counts} | "
        f"tokens: {result.input_tokens} in / {result.output_tokens} out | model: {result.model}"
    )
    return "\n".join(lines)


def main() -> None:
    """Run one analysis from the command line and print the attribution table."""
    import logging

    ap = argparse.ArgumentParser(description="Run one prompting-explained analysis.")
    ap.add_argument("--challenge", required=True, help="id or numeric prefix, e.g. 01")
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--ablation-runs", type=int, default=None)
    ap.add_argument("--save", type=Path, default=None, help="write the AnalysisResult JSON here")
    ap.add_argument("--show-answers", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true", help="log every call's token count")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(message)s")

    overrides = {"ablation_runs": args.ablation_runs} if args.ablation_runs else {}
    config = load_config(**overrides)
    challenge = get_challenge(args.challenge)
    async def go():
        llm = make_llm(config)
        try:
            return await analyze(challenge, args.prompt, llm, config)
        finally:
            await llm.aclose()

    result = asyncio.run(go())
    print(f"[{challenge.id}] {args.prompt}\n")
    print(format_table(result))
    if args.show_answers:
        print("\n--- baseline answer 1 ---\n" + result.baseline_runs[0].answer)
    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_text(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
