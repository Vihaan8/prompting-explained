"""Plain-language findings and "nerd facts", built from templates.

No model writes any of this text. Every number comes from an AnalysisResult or a
scorer, so a finding can never claim something the pipeline didn't compute.
"""

from __future__ import annotations

import re
from functools import lru_cache

from . import scorers as S
from .challenges import get_challenge
from .explain import reference_check
from .judge import part_status
from .types import OVERALL, AnalysisResult, Challenge

METHOD = "Method: remove one part and rerun (occlusion, also called leave-one-out)."


@lru_cache(maxsize=None)
def _challenge(challenge_id: str) -> Challenge:
    return get_challenge(challenge_id)


def f2(x: float) -> str:
    """Two-decimal formatting with a real minus sign and no negative zero."""
    s = f"{x:.2f}"
    if s == "-0.00":
        s = "0.00"
    return s.replace("-", "−")


def short_segment(text: str, max_words: int = 8) -> str:
    """The segment as quoted in a finding: in full if short, else first words + '…'."""
    words = text.strip().split()
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[: max_words - 2]) + "…"


def target_name(challenge: Challenge, target: str) -> str:
    """'overall' or the requirement's short name."""
    return "overall" if target == OVERALL else challenge.requirement(target).short


def target_label(challenge: Challenge, target: str) -> str:
    """Heading-style name: 'Overall' or the requirement's label."""
    return "Overall" if target == OVERALL else challenge.requirement(target).label


def _score_name(challenge: Challenge, target: str) -> str:
    name = target_name(challenge, target)
    return "Overall score" if target == OVERALL else f"{name[0].upper()}{name[1:]} score"


# Segment findings


def segment_numbers(result: AnalysisResult, segment_id: int, target: str) -> dict[str, float]:
    """The numbers behind one segment finding, straight from the result."""
    return {
        "with": result.baseline_mean[target],
        "without": result.ablations[segment_id].mean[target],
        "change": result.attribution[segment_id][target],
        "noise": part_floor(result, segment_id, target),
        "baseline_min": min(r.scores[target] for r in result.baseline_runs),
        "baseline_max": max(r.scores[target] for r in result.baseline_runs),
    }


def shown_change(n: dict[str, float]) -> float:
    """The change as displayed: the difference of the two rounded scores, so the shown
    numbers add up. Verdicts always use the unrounded attribution."""
    return round(n["with"], 2) - round(n["without"], 2)


def part_floor(result: AnalysisResult, segment_id: int, target: str) -> float:
    """The noise floor this part's effect is compared with."""
    if result.part_noise:
        return result.part_noise[segment_id][target]
    return result.noise[target]


def verdict(result: AnalysisResult, segment_id: int, target: str) -> str:
    """'helped' if attr >= noise, 'hurt' if attr <= -noise, else 'no effect'."""
    a, noise = result.attribution[segment_id][target], part_floor(result, segment_id, target)
    if a >= noise:
        return "helped"
    if a <= -noise:
        return "hurt"
    return "no effect"


def finding(result: AnalysisResult, segment_id: int, target: str = OVERALL) -> str:
    """One plain sentence about what a segment did to one target."""
    ch = _challenge(result.challenge_id)
    seg = short_segment(result.segments[segment_id].text)
    v = verdict(result, segment_id, target)
    if v == "helped":
        if target == OVERALL:
            return f'Removing "{seg}" made the answer worse overall.'
        return f'Removing "{seg}" made the answer worse at {target_name(ch, target)}.'
    if v == "hurt":
        what = "the overall score" if target == OVERALL else target_name(ch, target)
        return f'"{seg}" worked against {what}. The answer did better without it.'
    return f'"{seg}" didn\'t change the answer in a way we could measure.'


def nerd_facts(result: AnalysisResult, segment_id: int, target: str = OVERALL) -> str:
    """How the segment finding was calculated, with the actual numbers."""
    ch = _challenge(result.challenge_id)
    seg = short_segment(result.segments[segment_id].text)
    n = segment_numbers(result, segment_id, target)
    runs_b = len(result.baseline_runs)
    runs_a = len(result.ablations[segment_id].runs)
    score_name = _score_name(ch, target)
    v = verdict(result, segment_id, target)
    lines = [
        f'{score_name}: {f2(n["with"])} with "{seg}", {f2(n["without"])} without it (change {f2(shown_change(n))}).',
        f"With it: mean of {runs_b} runs of your full prompt. Without it: mean of {runs_a} runs.",
    ]
    if v == "no effect":
        lines.append(
            f"Your full prompt's score ranged from {f2(n['baseline_min'])} to {f2(n['baseline_max'])} across {runs_b} runs, "
            f"giving a noise floor of {f2(n['noise'])}. A change of {f2(abs(shown_change(n)))} is within normal variation."
        )
    else:
        ratio = abs(n["change"]) / n["noise"]
        lines.append(f"Noise floor: {f2(n['noise'])}. The change is {ratio:.1f}× the noise floor.")
    lines.append(METHOD)
    return "\n".join(lines)


def what_mattered(result: AnalysisResult, target: str = OVERALL) -> list[int]:
    """Segment ids ordered by effect size (largest |attribution| first)."""
    return sorted(range(len(result.segments)), key=lambda i: abs(result.attribution[i][target]), reverse=True)



# Simple view: one headline and one "why" per part


UNCLEAR_NOISE = 0.2  # a noise floor this large means "we can't tell", not "no effect"


def unclear(result: AnalysisResult, segment_id: int) -> bool:
    """No verdict because the answers varied too much, though removing the part did move the score."""
    a, noise = abs(result.attribution[segment_id][OVERALL]), part_floor(result, segment_id, OVERALL)
    floor = result.config.get("min_noise_floor", 0.05)
    return verdict(result, segment_id, OVERALL) == "no effect" and noise >= UNCLEAR_NOISE and a >= floor


def status(result: AnalysisResult, segment_id: int) -> str | None:
    """The per-part check's status ('needed', 'anyway', 'ignored'), or None if unavailable or n/a."""
    if not result.follow_with:
        return None
    return part_status(result.follow_with[segment_id], result.follow_without[segment_id])


def kind(result: AnalysisResult, segment_id: int) -> str:
    """What one part did, combining the task checks and the per-part check.

    'mattered'  the task score dropped without it
    'followed'  answers did it with the part and mostly stopped without it, but the task score didn't move
    'hurt'      the score was better without it
    'ignored'   answers didn't do it even with it in the prompt
    'anyway'    answers did it with or without it
    'unclear'   the score moved but run-to-run variation was too large to tell
    'quiet'     nothing to act on (e.g. "thanks") and no measurable effect
    """
    v = verdict(result, segment_id, OVERALL)
    st = status(result, segment_id)
    if v == "hurt":
        return "hurt"
    if v == "helped":
        return "mattered"
    if st == "needed":
        return "followed"
    if st == "ignored":
        return "ignored"
    if unclear(result, segment_id):
        return "unclear"
    if st == "anyway":
        return "anyway"
    return "quiet"


def checks_passed(result: AnalysisResult) -> tuple[int, int]:
    """How many of the task's checks the full prompt passed on average across its runs."""
    reqs = _challenge(result.challenge_id).requirements
    return sum(result.baseline_mean[r.id] >= S.PASS for r in reqs), len(reqs)


def did_task(result: AnalysisResult) -> float:
    """Share of the full prompt's runs where the answer actually did the task (every gate passed)."""
    gates = [r for r in _challenge(result.challenge_id).requirements if r.gate]
    if not gates:
        return 1.0
    ok = [all(run.scores[g.id] >= S.PASS for g in gates) for run in result.baseline_runs]
    return sum(ok) / len(ok)


def summary_line(result: AnalysisResult) -> str:
    """One plain sentence on how the full prompt did overall."""
    passed, total = checks_passed(result)
    done = did_task(result)
    if done == 0:
        return "With this prompt the AI didn't do the task. It asked what you meant or answered something else."
    if done < 1:
        n = len(result.baseline_runs)
        return f"The AI did the task in {round(done * n)} of {n} runs. It passed {passed} of {total} checks on average."
    return f"Your prompt passed {passed} of {total} checks for this task."


def strength(result: AnalysisResult, segment_id: int) -> float:
    """How big a part's effect was, 0 to 1: the larger of the score change and the per-part gap."""
    a = abs(result.attribution[segment_id][OVERALL])
    if result.follow_with and result.follow_with[segment_id] is not None and result.follow_without[segment_id] is not None:
        a = max(a, result.follow_with[segment_id] - result.follow_without[segment_id])
    return a


def headline(result: AnalysisResult, segment_id: int) -> str:
    """A short verdict for one part."""
    seg = short_segment(result.segments[segment_id].text)
    k = kind(result, segment_id)
    return {
        "mattered": f'"{seg}" mattered',
        "followed": f'"{seg}": the AI followed it',
        "hurt": f'"{seg}" worked against you',
        "ignored": f'"{seg}" was ignored',
        "unclear": f'"{seg}": not clear',
    }.get(k, f'"{seg}" didn\'t matter')


def why(result: AnalysisResult, segment_id: int) -> str:
    """One plain sentence on why a part did or didn't matter.

    Parts that mattered get the model-written comparison of the two answers when there is
    one; everything else is fixed text chosen by the measurements.
    """
    k = kind(result, segment_id)
    v = verdict(result, segment_id, OVERALL)
    if k == "followed":
        lead = result.explanations.get(segment_id, "Without it, the answer stopped doing this.")
        return f"{lead} The task checks scored about the same either way."
    if k in ("mattered", "hurt"):
        if k == "mattered" and segment_id in result.explanations:
            return result.explanations[segment_id]
        ch = _challenge(result.challenge_id)
        attr = result.attribution[segment_id]
        req = max(ch.requirements, key=lambda r: abs(attr[r.id]))
        if req.gate and v == "helped":
            return "Without it, the AI didn't do the task. It asked what you meant or answered something else."
        return f"Without it, the answer did {'worse' if v == 'helped' else 'better'} on {req.short} ({req.label[0].lower()}{req.label[1:]})."
    if k == "ignored":
        return "The answer didn't do this, even with it in your prompt."
    if k == "unclear":
        return (
            "Removing it changed the answer, but your answers also varied a lot from run to run, "
            "so we can't say if it helped. More specific prompts usually give steadier answers."
        )
    if k == "anyway":
        return "The AI did this anyway. " + _anyway_reason(result)
    if result.segments[segment_id].role == "politeness_filler":
        return (
            "The answer was just as good with or without it. It's a courtesy, not an instruction, "
            "so it gave the AI nothing new to act on."
        )
    return "The answer was just as good with or without it."


def _anyway_reason(result: AnalysisResult) -> str:
    if _challenge(result.challenge_id).fixed_context:
        return "Without it, the answer still did it, probably because the attached document or the rest of your prompt made it clear."
    return "Without it, the answer still did it, probably because the rest of your prompt made it clear."


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + f" and {names[-1]}"


ROW_ORDER = ("mattered", "hurt", "followed", "ignored", "unclear")


def simple_items(result: AnalysisResult) -> list[tuple[str, str, str]]:
    """The 'What mattered' list as (kind, headline, why) rows.

    Parts that mattered or hurt come first (largest effect first), then ignored and unclear
    parts. Parts the AI did anyway are grouped into one row; politeness gets its own row.
    """
    by_kind: dict[str, list[int]] = {}
    for i in sorted(range(len(result.segments)), key=lambda i: -strength(result, i)):
        by_kind.setdefault(kind(result, i), []).append(i)
    rows: list[tuple[str, str, str]] = []
    for k in ROW_ORDER:
        for n, i in enumerate(by_kind.get(k, [])):
            head = headline(result, i) + (" most" if k == "mattered" and n == 0 and len(by_kind[k]) > 1 else "")
            rows.append((k, head, why(result, i)))
    anyway = sorted(by_kind.get("anyway", []))
    if len(anyway) == 1:
        rows.append(("anyway", headline(result, anyway[0]), why(result, anyway[0])))
    elif anyway:
        names = [f'"{short_segment(result.segments[i].text)}"' for i in anyway]
        reason = _anyway_reason(result).replace("Without it, the answer still did it", "Without each one, the answer still did it")
        rows.append(("anyway", f"{_join(names)} didn't matter here", "The AI did these anyway. " + reason))
    quiet = sorted(by_kind.get("quiet", []))
    polite = [i for i in quiet if result.segments[i].role == "politeness_filler"]
    other = [i for i in quiet if i not in polite]
    for i in polite:
        rows.append(("quiet", headline(result, i), why(result, i)))
    if len(other) == 1:
        rows.append(("quiet", headline(result, other[0]), why(result, other[0])))
    elif other:
        names = [f'"{short_segment(result.segments[i].text)}"' for i in other]
        rows.append(("quiet", f"{_join(names)} didn't matter here", "The answer was just as good without each of them."))
    return rows


# Requirement scores


def requirement_detail(challenge: Challenge, req_id: str, answer: str, score: float) -> str:
    """How one requirement score was computed for one answer."""
    req = challenge.requirement(req_id)
    p = req.params
    sc = f2(score)
    if req.scorer == "word_count_max":
        wc, mx = len(S.words(answer)), p["max"]
        if wc <= mx:
            return f"Length: {wc} words, limit {mx}. Within the limit, so score = {sc}."
        return (
            f"Length: {wc} words, limit {mx}. Score = 1 − ({wc} − {mx}) / {mx} = {sc}. "
            "Partial credit so small changes still register."
        )
    if req.scorer == "bullet_count":
        n, t = len(S.bullet_lines(answer)), p["target"]
        return (
            f"Bullet points: {n} (lines starting with -, *, • or a number), target {t}. "
            f"Score = 1 − |{n} − {t}| / {t} = {sc}, floored at 0."
        )
    if req.scorer == "reading_grade_max":
        if not S.words(answer):
            return "The answer is empty, so it scores 0.00 on reading level."
        g, mx = S.reading_grade(answer), p["max_grade"]
        base = f"Flesch–Kincaid grade {g:.1f} (textstat), target ≤ {mx}. "
        formula = f"Within the target, so score = {sc}." if g <= mx else f"Score = 1 − ({g:.1f} − {mx}) / 5 = {sc}."
        return (
            base + f"{formula} "
            "The formula uses words per sentence and syllables per word. It's a rough measure."
        )
    if req.scorer == "keywords_present":
        kws = p["keywords"]
        found = S.keywords_found(answer, kws)
        missing = [k for k in kws if k not in found]
        msg = f"Found {len(found)} of {len(kws)}: {_quote(found) or 'none'}."
        if missing:
            msg += f" Missing: {_quote(missing)}."
        return msg + f" Score = {len(found)} / {len(kws)} = {sc}. Case-insensitive text match."
    if req.scorer == "keyword_groups_present":
        hits = S.groups_found(answer, p["groups"])
        missing = [g[0] for g, ok in zip(p["groups"], hits) if not ok]
        msg = f"Found {sum(hits)} of {len(hits)} required details."
        if missing:
            msg += f" Missing: {_quote(missing)}."
        return msg + f" Score = {sum(hits)} / {len(hits)} = {sc}. Each detail can match any of its spellings."
    if req.scorer == "lines_naming":
        n = S.item_lines(answer, p["groups"], p.get("max_words", 8))
        if p.get("at_least") is not None:
            return f"{n} short lines name a list item; at least {p['at_least']} are needed to count as a list. Score = {sc}."
        t = p["target"]
        return f"{n} short lines name an item, target {t}. Score = 1 − |{n} − {t}| / {t} = {sc}, floored at 0."
    if req.scorer == "keywords_absent":
        kws = p["keywords"]
        used = S.keywords_used(answer, kws)
        if not used:
            return f"None of {_quote(kws)} appear, so score = {sc}."
        if p.get("strict"):
            return f"Found {_quote(used)}. Any one of these fails the check, so score = {sc}."
        return (
            f"Found {_quote(used)}. Score = 1 − {len(used)} / {len(kws)} = {sc}. "
            "Mentions right after a negation, like \"doesn't apologize\", don't count."
        )
    if req.scorer == "json_only":
        _, how = S.extract_json(answer)
        if how == "pure":
            return f"Parsed with Python's json module. The whole answer is JSON, so score = {sc}."
        if how == "wrapped":
            return f"Parsed with Python's json module. JSON was found inside code fences or extra text, so score = {sc}."
        return f"No JSON could be parsed from the answer, so score = {sc}."
    if req.scorer == "json_keys_present":
        obj = S._json_object(answer)
        if obj is None:
            return f"No JSON object could be parsed, so score = {sc}."
        keys = p["keys"]
        missing = [k for k in keys if k not in obj]
        msg = f"Parsed with Python's json module. {len(keys) - len(missing)} of {len(keys)} expected keys present"
        msg += f" (missing: {', '.join(missing)})." if missing else "."
        return msg + f" Score = {sc}."
    if req.scorer == "json_field_accuracy":
        obj = S._json_object(answer)
        if obj is None:
            return f"No JSON object could be parsed, so score = {sc}."
        matches = S.json_field_matches(answer, p["expected"])
        wrong = [k for k, ok in matches.items() if not ok]
        msg = f"{sum(matches.values())} of {len(matches)} fields match after ignoring case and punctuation."
        for k in wrong:
            got = obj.get(k, "missing")
            msg += f' {k} was "{got}", expected "{p["expected"][k]}".'
        return msg + f" Score = {sc}."
    if req.scorer == "json_field_null":
        obj = S._json_object(answer)
        field = p["field"]
        if obj is None:
            return f"No JSON object could be parsed, so {field} can't be checked. Score = {sc}."
        if field not in obj:
            return f"There is no {field} key, so nothing was invented (the keys check counts the missing key). Score = {sc}."
        val = obj[field]
        if S.is_null_like(val):
            return f"{field} was {_show(val)}, which counts as empty. Nothing was invented. Score = {sc}."
        return f"{field} was {_show(val)} but the posting has no {field}, so this counts as invented. Score = {sc}."
    return f"Score = {sc}."


def requirement_finding(challenge: Challenge, req_id: str, score: float) -> str:
    """'Passed' or 'Not met (0.67)'."""
    return "Passed" if score >= S.PASS else f"Not met ({f2(score)})"


def _quote(items: list[str]) -> str:
    return ", ".join(f'"{i}"' for i in items)


def _show(value) -> str:
    return "null" if value is None else f'"{value}"' if isinstance(value, str) else str(value)


# Pipeline-level nerd facts


def noise_nerd_facts(result: AnalysisResult, target: str = OVERALL) -> str:
    """How the noise floor for one target was set."""
    scores = [r.scores[target] for r in result.baseline_runs]
    k = result.config.get("noise_floor_k", 2.0)
    floor_min = result.config.get("min_noise_floor", 0.05)
    return (
        f"We ran your exact prompt {len(scores)} times. Scores: {', '.join(f2(s) for s in scores)}.\n"
        f"Each part is compared with its own noise floor: {k:g} standard errors of the difference between "
        f"the runs with it and the runs without it, and never less than {f2(floor_min)}. "
        "Changes smaller than that are shown in grey."
    )


def segmentation_nerd_facts(result: AnalysisResult) -> str:
    """How the prompt was split into parts."""
    n = len(result.segments)
    if result.segmentation_method == "fallback":
        return (
            f"The AI's split didn't match your text exactly, so your prompt was split into {n} parts "
            "at sentence and comma boundaries instead, and every part is labeled \"other\"."
        )
    return (
        f"Your prompt was split into {n} parts by an AI model, and each part was given a role "
        "(task, audience, constraint…). The split is itself a model output and can vary."
    )


WHAT_CHANGED_NERD_FACTS = (
    "This sentence was written by an AI model comparing the two answers. "
    "It is a description, not a measurement. The scores above are the measurement."
)

HEATMAP_NERD_FACTS = (
    "Color strength = size of the change relative to the largest change in your prompt. "
    "Colors show this model's behavior on this run, not a general rule about prompting."
)


def reference_nerd_facts(challenge: Challenge) -> str:
    """Where the reference prompt's claim comes from."""
    rep = reference_check()
    entry = rep.get("challenges", {}).get(challenge.id)
    if not entry:
        return "This reference prompt has not been checked yet (run scripts/verify_references.py)."
    model = rep.get("meta", {}).get("model", "the model")
    runs = entry["runs"]
    passed = sum(all(s[r.id] >= S.PASS for r in challenge.requirements) for s in entry["scores"])
    return (
        f"This prompt passed every check in {passed} of {runs} runs with {model}. "
        "It's one working example, not the only right answer."
    )


def cost_nerd_facts(result: AnalysisResult) -> str:
    """What the model calls were spent on."""
    c = result.call_counts
    per_part = result.config.get("ablation_runs", 1)
    parts = []
    if c.get("segment"):
        parts.append(f"{c['segment']} to split the prompt")
    if c.get("baseline"):
        parts.append(f"{c['baseline']} runs of your full prompt")
    if c.get("ablation"):
        parts.append(f"{c['ablation']} runs with one part removed ({per_part} per part)")
    if c.get("explain"):
        parts.append(f"{c['explain']} \"what changed\" sentences")
    return (
        f"{result.calls} calls to {result.model}: {', '.join(parts)}. "
        f"{result.input_tokens:,} input and {result.output_tokens:,} output tokens."
    )


def cost_label(calls: int, tokens: int) -> str:
    """'14 model calls · 6.2k tokens'."""
    tok = f"{tokens / 1000:.1f}k" if tokens >= 1000 else str(tokens)
    return f"{calls} model call{'s' if calls != 1 else ''} · {tok} tokens"


def numbers_in(text: str) -> list[str]:
    """Every decimal number in a string, minus signs normalized (used by tests)."""
    return re.findall(r"−?\d+\.\d+", text)

