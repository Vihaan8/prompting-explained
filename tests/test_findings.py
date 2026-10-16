import asyncio

import pytest

from core import findings as F
from core.attribution import analyze, score_answer
from core.challenges import get_challenge
from core.config import Config
from core.explain import compare_roles, word_diff
from core.llm import FakeLLM
from core.types import OVERALL, Segment
from tests.test_attribution import KID, PROMPT, kid_answer, segs


def _result(prompt=PROMPT, parts=None, roles=None, responder=None):
    sg = segs() if parts is None else segs(prompt, parts, roles)
    fake = FakeLLM(responder or (lambda p, s: kid_answer(p)))
    return asyncio.run(analyze(KID, prompt, fake, Config(baseline_runs=3, ablation_runs=1, judge_parts=False), segments=sg))


@pytest.fixture(scope="module")
def res():
    return _result()


@pytest.fixture(scope="module")
def hurt_res():
    prompt = "Use 3 bullet points. Keep it under 60 words. Also add plenty of detail."
    parts = ["Use 3 bullet points.", "Keep it under 60 words.", "Also add plenty of detail."]

    def respond(p, s):
        ans = kid_answer(p)
        return ans.replace("- Prices go up.", "- " + "Prices go up. " * 30) if "plenty of detail" in p else ans

    return _result(prompt, parts, ["format", "constraint", "constraint"], respond)


def _expected_verdict(r, i, t):
    a, n = r.attribution[i][t], r.noise[t]
    return "helped" if a >= n else "hurt" if a <= -n else "no effect"


def test_verdicts_follow_the_rule(res, hurt_res):
    for r in (res, hurt_res):
        for i in range(len(r.segments)):
            for t in r.targets:
                assert F.verdict(r, i, t) == _expected_verdict(r, i, t)
    assert F.verdict(res, 0, OVERALL) == "no effect"
    assert F.verdict(res, 1, "bullets") == "helped"
    assert F.verdict(hurt_res, 2, "length") == "hurt"


def test_finding_templates(res, hurt_res):
    assert F.finding(res, 1, "bullets") == 'Removing "Use 3 bullet points." made the answer worse at bullet points.'
    assert F.finding(res, 1, OVERALL) == 'Removing "Use 3 bullet points." made the answer worse overall.'
    assert F.finding(res, 0, OVERALL) == '"Please explain inflation." didn\'t change the answer in a way we could measure.'
    assert F.finding(hurt_res, 2, "length") == '"Also add plenty of detail." worked against length. The answer did better without it.'


@pytest.mark.parametrize("seg,target", [(0, OVERALL), (1, "bullets"), (2, "length"), (2, OVERALL), (1, "length")])
def test_nerd_fact_numbers_match_result(res, seg, target):
    text = F.nerd_facts(res, seg, target)
    n = F.segment_numbers(res, seg, target)
    # The numbers dict is the result's own values...
    assert n["with"] == res.baseline_mean[target]
    assert n["without"] == res.ablations[seg].mean[target]
    assert n["change"] == res.attribution[seg][target]
    assert n["noise"] == res.noise[target]
    # ...and every number in the text is one of them (or the ratio computed from them).
    allowed = {F.f2(n[k]) for k in ("with", "without", "noise", "baseline_min", "baseline_max")}
    shown = round(n["with"], 2) - round(n["without"], 2)
    assert abs(shown - n["change"]) <= 0.011  # display rounding only
    allowed |= {F.f2(shown), F.f2(abs(shown))}
    if F.verdict(res, seg, target) != "no effect":
        allowed.add(f"{abs(n['change']) / n['noise']:.1f}")
    assert set(F.numbers_in(text)) <= allowed
    assert F.f2(n["with"]) in text and F.f2(n["without"]) in text and F.f2(shown) in text and F.f2(n["noise"]) in text
    assert "occlusion" in text


def test_hurt_nerd_facts_show_negative_change(hurt_res):
    text = F.nerd_facts(hurt_res, 2, "length")
    shown = F.shown_change(F.segment_numbers(hurt_res, 2, "length"))
    assert F.f2(shown) in text and F.f2(shown).startswith("−")


def test_noise_nerd_facts_numbers(res):
    text = F.noise_nerd_facts(res, "length")
    scores = [F.f2(r.scores["length"]) for r in res.baseline_runs]
    assert all(s in text for s in scores)
    assert F.f2(res.noise["length"]) in text and F.f2(res.baseline_std["length"]) in text


def test_requirement_details_match_scores():
    ch = KID
    long_ans = kid_answer("Use 3 bullet points.")
    sc = score_answer(ch, long_ans).scores
    d = F.requirement_detail(ch, "length", long_ans, sc["length"])
    from core.scorers import words

    assert f"{len(words(long_ans))} words, limit 60" in d and F.f2(sc["length"]) in d
    d = F.requirement_detail(ch, "bullets", "- a\n- b", 2 / 3)
    assert "Bullet points: 2" in d and "0.67" in d


def test_json_requirement_details():
    ch = get_challenge("03")
    ans = '```json\n{"title": "Data Analyst", "company": "Brightline Health", "location": "Raleigh, NC", "work_mode": "Hybrid (3 days in)", "salary": "$70,000"}\n```'
    sc = score_answer(ch, ans).scores
    assert "inside code fences" in F.requirement_detail(ch, "json_only", ans, sc["json_only"])
    assert "5 of 5 expected keys" in F.requirement_detail(ch, "fields", ans, sc["fields"])
    acc = F.requirement_detail(ch, "accuracy", ans, sc["accuracy"])
    assert "3 of 4 fields" in acc and 'work_mode was "Hybrid (3 days in)"' in acc
    sal = F.requirement_detail(ch, "no_invented_salary", ans, sc["no_invented_salary"])
    assert '"$70,000"' in sal and "invented" in sal and "0.00" in sal


def test_cost_nerd_facts(res):
    text = F.cost_nerd_facts(res)
    assert text.startswith(f"{res.calls} calls to fake-llm")
    assert "3 runs of your full prompt" in text and "3 runs with one part removed (1 per part)" in text
    assert F.cost_label(14, 6200) == "14 model calls · 6.2k tokens"


def test_short_segment():
    assert F.short_segment("please thank you") == "please thank you"
    assert F.short_segment("one two three four five six seven eight nine") == "one two three four five six…"


def test_compare_roles_ignores_filler_and_other():
    def seg(role):
        return Segment(id=0, text="x", role=role, start=0, end=1)

    out = compare_roles([seg("task"), seg("politeness_filler"), seg("tone")], [seg("task"), seg("constraint"), seg("other")])
    assert out == {"included": ["task"], "missing": ["constraint"], "extra": ["tone"]}


def test_word_diff():
    d = word_diff("Explain inflation please", "Explain inflation in 3 bullets")
    assert d == [("same", "Explain inflation"), ("yours", "please"), ("reference", "in 3 bullets")]


def test_headline_and_why(res):
    assert F.headline(res, 1) == '"Use 3 bullet points." mattered'
    assert F.headline(res, 0) == '"Please explain inflation." didn\'t matter'
    # No model-written sentence in this result, so the hidden check that moved most is named.
    assert F.why(res, 1) == "Without it, the answer did worse on bullet points (exactly 3 bullet points)."
    assert F.why(res, 0).startswith("The answer was just as good with or without it.")


def test_why_for_politeness_and_explanations(res):
    polite = res.model_copy(deep=True)
    polite.segments[0] = polite.segments[0].model_copy(update={"role": "politeness_filler"})
    assert "courtesy, not an instruction" in F.why(polite, 0)
    polite.explanations = {1: "Without this part, the answer was a paragraph."}
    assert F.why(polite, 1) == "Without this part, the answer was a paragraph."


def test_hurt_headline(hurt_res):
    assert F.headline(hurt_res, 2) == '"Also add plenty of detail." worked against you'
    assert F.why(hurt_res, 2) == "Without it, the answer did better on length (60 words or fewer)."


def test_simple_items_groups_quiet_parts(res):
    rows = F.simple_items(res)
    assert rows[0] == ("mattered", '"Use 3 bullet points." mattered most', F.why(res, 1))
    assert rows[1][0] == "mattered" and "most" not in rows[1][1]
    assert rows[-1] == ("quiet", '"Please explain inflation." didn\'t matter', F.why(res, 0))
    many = res.model_copy(deep=True)
    many.attribution = [{t: 0.0 for t in res.targets} for _ in res.segments]
    rows = F.simple_items(many)
    assert len(rows) == 1 and rows[0][1].endswith("didn't matter here")
    assert '"Use 3 bullet points."' in rows[0][1] and " and " in rows[0][1]


def test_unclear_when_answers_vary_a_lot(res):
    noisy = res.model_copy(deep=True)
    noisy.noise = {**noisy.noise, OVERALL: 0.45}
    noisy.attribution[1] = {**noisy.attribution[1], OVERALL: 0.3}  # moved, but within a large floor
    assert F.verdict(noisy, 1, OVERALL) == "no effect"
    assert F.headline(noisy, 1) == '"Use 3 bullet points.": not clear'
    assert "can't say if it helped" in F.why(noisy, 1)
    assert any(h == '"Use 3 bullet points.": not clear' for _, h, _ in F.simple_items(noisy))
    # A real zero with a large floor is still "didn't matter".
    assert F.headline(noisy, 0) == '"Please explain inflation." didn\'t matter'


def _with_judge(res, with_, without):
    r = res.model_copy(deep=True)
    r.attribution = [{t: 0.0 for t in res.targets} for _ in res.segments]
    r.follow_with, r.follow_without = with_, without
    return r


def test_per_part_check_drives_kinds(res):
    r = _with_judge(res, [1.0, 1.0, 0.0], [1.0, 0.0, 0.0])
    assert [F.kind(r, i) for i in range(3)] == ["anyway", "mattered", "ignored"]
    assert F.headline(r, 1) == '"Use 3 bullet points." mattered'
    assert F.why(r, 1) == "Without it, the answer stopped doing this."
    assert F.headline(r, 2) == '"Keep it under 60 words." was ignored'
    assert F.why(r, 0).startswith("The AI did this anyway.")
    kinds = [k for k, _, _ in F.simple_items(r)]
    assert kinds == ["mattered", "ignored", "anyway"]


def test_anyway_parts_are_grouped(res):
    r = _with_judge(res, [1.0, 1.0, 1.0], [1.0, 1.0, 1.0])
    rows = F.simple_items(r)
    assert len(rows) == 1 and rows[0][0] == "anyway" and rows[0][1].endswith("didn't matter here")
    assert "Without each one" in rows[0][2]


def test_score_hurt_beats_per_part_check(hurt_res):
    r = hurt_res.model_copy(deep=True)
    r.follow_with, r.follow_without = [1.0, 1.0, 1.0], [0.0, 0.0, 0.0]
    assert F.kind(r, 2) == "hurt"


def test_hurt_uses_measured_reason_not_model_sentence(hurt_res):
    r = hurt_res.model_copy(deep=True)
    r.explanations = {2: "Without this part, the answer dropped a sentence."}
    assert F.why(r, 2) == "Without it, the answer did better on length (60 words or fewer)."
