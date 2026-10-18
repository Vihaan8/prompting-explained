import sys
from pathlib import Path

from core.challenges import get_challenge

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from run_eval import kappa, matching_check  # noqa: E402


def check_id(challenge: str, text: str):
    req = matching_check(get_challenge(challenge), text)
    return req.id if req else None


def test_matching_check_maps_parts_onto_one_check():
    assert check_id("explain_to_kid", "Use exactly three bullet points.") == "bullets"
    assert check_id("explain_to_kid", "keep it under 60 words") == "length"
    assert check_id("job_extraction", "Return only the JSON, no other text.") == "json_only"
    assert check_id("landlord_reply", "Don't apologize.") == "no_apology"
    assert check_id("privacy_bug_report", "Leave out the customer's personal details.") == "no_personal_info"


def test_matching_check_skips_vague_or_double_parts():
    assert check_id("explain_to_kid", "Use bullet points.") is None  # no count, so not the same as the check
    assert check_id("explain_to_kid", "Keep it short.") is None
    assert check_id("explain_to_kid", "3 bullets, under 60 words") is None  # two checks at once
    assert check_id("landlord_reply", "Sorry to bother you!") is None  # an apology, not a rule against one


def test_kappa():
    assert kappa([True, False, True, False], [True, False, True, False]) == 1.0
    assert kappa([True, True, False, False], [True, False, True, False]) == 0.0
