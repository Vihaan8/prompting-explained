import asyncio
import json
import re

from core.attribution import analyze
from core.config import Config
from core.judge import parse_ratings, part_status
from core.llm import FakeLLM
from tests.test_attribution import KID, PROMPT, kid_answer, segs


def test_parse_ratings():
    text = json.dumps({"ratings": [{"part": 1, "rating": "yes"}, {"part": 2, "rating": "n/a"}, {"part": 3, "rating": "partly"}]})
    assert parse_ratings(text, 3) == [1.0, None, 0.5]
    assert parse_ratings(text, 4) is None  # a part was not rated
    assert parse_ratings("nope", 3) is None


def test_part_status():
    assert part_status(1.0, 0.0) == "needed"
    assert part_status(1.0, 1.0) == "anyway"
    assert part_status(1.0, 0.75) == "anyway"
    assert part_status(0.0, 0.0) == "ignored"
    assert part_status(None, 1.0) is None


def judging_fake():
    """Answers by kid_answer; as a judge, says part 'bullets' is followed only if the answer has bullets,
    and part 1 (the task) is always followed."""

    def respond(prompt, schema):
        if schema is None:
            return kid_answer(prompt)
        answer = prompt.split("<answer>")[1].split("</answer>")[0]
        bullets = "yes" if re.search(r"^- ", answer, re.M) else "no"
        return json.dumps({"ratings": [{"part": 1, "rating": "yes"}, {"part": 2, "rating": bullets}, {"part": 3, "rating": "n/a"}]})

    return FakeLLM(respond)


def test_analyze_fills_per_part_ratings():
    cfg = Config(baseline_runs=3, ablation_runs=2, judge_parts=True, max_calls_per_analysis=40)
    res = asyncio.run(analyze(KID, PROMPT, judging_fake(), cfg, segments=segs()))
    assert res.call_counts["judge"] == 3 + 3 * 2
    assert res.follow_with == [1.0, 1.0, None]
    assert res.follow_without[1] == 0.0  # without "Use 3 bullet points." the answers have no bullets
    assert res.follow_without[0] == 1.0
    assert part_status(res.follow_with[1], res.follow_without[1]) == "needed"
    assert part_status(res.follow_with[0], res.follow_without[0]) == "anyway"
