import asyncio
import itertools
import json
import statistics

import pytest

from core.attribution import FILLER, ablate, analyze, build_prompt
from core.challenges import get_challenge
from core.config import Config
from core.llm import BudgetExceeded, FakeLLM
from core.segment import align
from core.types import OVERALL, Segment

KID = get_challenge("01")
LANDLORD = get_challenge("02")

PROMPT = "Please explain inflation. Use 3 bullet points. Keep it under 60 words."
PARTS = ["Please explain inflation.", "Use 3 bullet points.", "Keep it under 60 words."]
ROLES = ["task", "format", "constraint"]

SHORT_LINES = ["Prices go up.", "Coins buy less.", "Candy costs more."]
LONG_LINES = ["Prices go up. We pay more. " * 5, "Coins buy less. Our bag is small. " * 5, "Candy costs more. Mom is sad. " * 4]


def kid_answer(prompt: str) -> str:
    """Planted behaviour: '60 words' -> short answer, '3 bullet' -> bullets. Nothing else matters."""
    lines = SHORT_LINES if "60 words" in prompt else LONG_LINES
    if "3 bullet" in prompt:
        return "\n".join(f"- {ln.strip()}" for ln in lines)
    return " ".join(ln.strip() for ln in lines)


def segs(original=PROMPT, parts=PARTS, roles=ROLES):
    return [Segment(id=i, text=original[s:e], role=r, start=s, end=e) for i, ((s, e), r) in enumerate(zip(align(original, parts), roles))]


def cfg(**kw):
    base = dict(baseline_runs=3, ablation_runs=1, max_calls_per_analysis=25, explain_top_n=3, judge_parts=False)
    base.update(kw)
    return Config(**base)


def run(coro):
    return asyncio.run(coro)


def test_fake_answers_score_as_planted():
    from core.attribution import score_answer

    assert score_answer(KID, kid_answer(PROMPT)).scores == {"on_task": 1.0, "bullets": 1.0, "length": 1.0, "reading_level": 1.0, OVERALL: 1.0}
    long = score_answer(KID, kid_answer("Use 3 bullet points."))
    assert long.scores["length"] < 1 and long.scores["bullets"] == 1.0 and long.scores["reading_level"] == 1.0


def test_attribution_sign_and_magnitude():
    fake = FakeLLM(lambda p, s: kid_answer(p))
    res = run(analyze(KID, PROMPT, fake, cfg(), segments=segs()))

    from core.attribution import score_answer

    long_length = score_answer(KID, kid_answer("Use 3 bullet points.")).scores["length"]
    a = res.attribution
    # Task segment: no planted effect.
    assert all(v == 0 for v in a[0].values())
    assert all(res.within_noise[0].values())
    # Bullets segment helped the bullets requirement only.
    assert a[1]["bullets"] == pytest.approx(1.0)
    assert a[1]["length"] == 0 and a[1]["reading_level"] == 0
    assert a[1][OVERALL] == pytest.approx(1 / 3)
    assert not res.within_noise[1]["bullets"] and res.within_noise[1]["length"]
    # Length segment helped length by exactly the lost partial credit.
    assert a[2]["length"] == pytest.approx(1 - long_length)
    assert a[2]["bullets"] == 0
    assert a[2][OVERALL] == pytest.approx((1 - long_length) / 3)
    assert not res.within_noise[2]["length"]


def test_negative_attribution_when_segment_hurts():
    prompt = "Use 3 bullet points. Keep it under 60 words. Also add plenty of detail."
    parts = ["Use 3 bullet points.", "Keep it under 60 words.", "Also add plenty of detail."]

    def respond(p, s):
        ans = kid_answer(p)
        return ans.replace("- Prices go up.", "- " + "Prices go up. " * 30) if "plenty of detail" in p else ans

    res = run(analyze(KID, prompt, FakeLLM(respond), cfg(), segments=segs(prompt, parts, ["format", "constraint", "constraint"])))
    assert res.attribution[2]["length"] < -0.05
    assert not res.within_noise[2]["length"]


def test_noise_floor_with_zero_variance_uses_minimum():
    res = run(analyze(KID, PROMPT, FakeLLM(lambda p, s: kid_answer(p)), cfg(min_noise_floor=0.05), segments=segs()))
    assert all(v == 0 for v in res.baseline_std.values())
    assert all(v == 0.05 for v in res.noise.values())


def test_noise_floor_scales_with_variance():
    flip = itertools.cycle([True, False, True])

    def respond(p, s):
        # Same prompt, different answers: simulates run-to-run randomness on length.
        return kid_answer(p if next(flip) else p.replace("60 words", ""))

    res = run(analyze(KID, PROMPT, FakeLLM(respond), cfg(), segments=segs()))
    lengths = [r.scores["length"] for r in res.baseline_runs]
    assert len(set(lengths)) == 2
    assert res.baseline_std["length"] == pytest.approx(statistics.stdev(lengths))
    assert res.noise["length"] == pytest.approx(max(2 * statistics.stdev(lengths), 0.05))


def test_call_budget_enforced_before_spending():
    fake = FakeLLM(lambda p, s: kid_answer(p))
    with pytest.raises(BudgetExceeded):
        run(analyze(KID, PROMPT, fake, cfg(max_calls_per_analysis=5), segments=segs()))
    assert fake.prompts == []  # 3 baseline + 3 ablations = 6 > 5, so nothing was sent


def test_call_counts_and_full_pipeline_with_segmentation():
    payload = {"segments": [{"text": t, "role": r} for t, r in zip(PARTS, ROLES)]}

    def respond(p, schema):
        return json.dumps(payload) if schema is not None else kid_answer(p)

    res = run(analyze(KID, PROMPT, FakeLLM(respond), cfg()))
    assert res.segmentation_method == "llm"
    assert [s.role for s in res.segments] == ROLES
    assert res.calls == 1 + 3 + 3
    assert res.call_counts == {"segment": 1, "baseline": 3, "ablation": 3}
    assert res.input_tokens > 0 and res.output_tokens > 0


def test_fixed_context_is_never_ablated():
    prompt = "Reply to my landlord. Dispute the $75 fee. Keep it short."
    parts = ["Reply to my landlord.", "Dispute the $75 fee.", "Keep it short."]
    fake = FakeLLM(lambda p, s: "Dear Dana, the $75 fee is not allowed under Section 4.2 and its grace period.")
    res = run(analyze(LANDLORD, prompt, fake, cfg(), segments=segs(prompt, parts, ["task", "task", "constraint"])))
    doc = f"<document>\n{LANDLORD.fixed_context.strip()}\n</document>"
    assert len(fake.prompts) == 6
    assert all(p.endswith(doc) for p in fake.prompts)
    # Each ablated prompt lost exactly its segment and kept the others.
    for s, abl in zip(res.segments, res.ablations):
        assert s.display not in abl.prompt
        assert all(o.display in abl.prompt for o in res.segments if o.id != s.id)


def test_ablate_delete_and_filler():
    sg = segs()
    assert ablate(PROMPT, sg, 1, "delete") == "Please explain inflation. Keep it under 60 words."
    assert ablate(PROMPT, sg, 2, "delete") == "Please explain inflation. Use 3 bullet points."
    assert ablate(PROMPT, sg, 1, "filler") == f"Please explain inflation. {FILLER} Keep it under 60 words."


def test_ablate_many_removes_a_set():
    from core.attribution import ablate_many

    assert ablate_many(PROMPT, segs(), [0, 2]) == "Use 3 bullet points."
    assert ablate_many(PROMPT, segs(), []) == PROMPT


def test_build_prompt():
    assert build_prompt("hi", None) == "hi"
    assert build_prompt("hi", "doc\n") == "hi\n\n<document>\ndoc\n</document>"


def test_empty_ablation_skips_call():
    prompt = "Keep it under 60 words."
    fake = FakeLLM(lambda p, s: kid_answer(p))
    res = run(analyze(KID, prompt, fake, cfg(), segments=segs(prompt, [prompt], ["constraint"])))
    assert len(fake.prompts) == 3  # baseline only; removing the only segment leaves nothing to send
    assert res.ablations[0].runs[0].answer == ""
    assert res.ablations[0].runs[0].stop_reason == "empty_prompt"


def test_explainer_runs_for_top_segments():
    async def explainer(llm, original, ablated):
        await llm.complete("compare", kind="explain")
        return "Without this, the answer changed."

    res = run(analyze(KID, PROMPT, FakeLLM(lambda p, s: kid_answer(p)), cfg(explain_top_n=2), segments=segs(), explainer=explainer))
    assert set(res.explanations) == {1, 2}  # the two segments with nonzero overall effect
    assert res.call_counts["explain"] == 2


def test_result_round_trips_through_json():
    from core.types import AnalysisResult

    res = run(analyze(KID, PROMPT, FakeLLM(lambda p, s: kid_answer(p)), cfg(), segments=segs()))
    again = AnalysisResult.model_validate_json(res.model_dump_json())
    assert again.attribution == res.attribution


def test_non_answer_scores_zero_overall():
    from core.attribution import score_answer

    question_back = "It looks like your message got cut off. Could you tell me what you'd like me to explain?"
    sc = score_answer(KID, question_back).scores
    assert sc["length"] == 1.0 and sc["on_task"] == 0.0
    assert sc[OVERALL] == 0.0  # short and simple, but it didn't do the task


def test_gate_multiplies_mean_of_regular_requirements():
    from core.attribution import score_answer

    sc = score_answer(KID, kid_answer("Use 3 bullet points.")).scores
    regular = [sc[r] for r in ("bullets", "length", "reading_level")]
    assert sc[OVERALL] == pytest.approx(sum(regular) / 3)
