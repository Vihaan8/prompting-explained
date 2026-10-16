import pytest

from core import scorers as S
from core.challenges import load_all


@pytest.mark.parametrize(
    "text,expected",
    [
        ("- Prices go up.\n- Coins buy less.", 1.0),
        ("Inflation means your money buys less.", 1.0),
        ("It looks like your message got cut off. Could you tell me what you'd like me to explain?", 0.0),
        ("Sure! What would you like me to explain about prices?", 0.0),
        ("Here is a poem about the sea.", 0.0),
    ],
)
def test_on_topic(text, expected):
    assert S.on_topic(text, ["price", "cost", "money", "expensive", "inflation"]) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Subject: Re: Late fee\n\nHi Dana,\nThe fee is invalid.", 1.0),
        ("Here's a reply:\n\nDear Dana,\nThe fee is invalid.", 1.0),
        ("Based on the lease, the $75 late fee appears to be improper, and you should dispute it.", 0.0),
        ("Could you tell me what you'd like the reply to say?", 0.0),
    ],
)
def test_starts_line_with(text, expected):
    assert S.starts_line_with(text, ["hi", "hello", "dear", "subject"]) == expected


def test_all_challenges_load_and_reference_registered_scorers():
    chs = load_all()
    assert [c.id for c in chs][:3] == ["explain_to_kid", "landlord_reply", "job_extraction"]
    assert len(chs) == len({c.id for c in chs}) >= 8
    assert all(c.category and c.subtitle for c in chs)


# word_count_max


def test_word_count_under_and_over():
    assert S.word_count_max("one two three", max=3) == 1.0
    assert S.word_count_max(" ".join(["w"] * 74), max=60) == pytest.approx(1 - 14 / 60)
    assert S.word_count_max(" ".join(["w"] * 500), max=60) == 0.0


def test_word_count_ignores_bullet_markers_and_empty():
    assert len(S.words("- one\n- two\n* three\n•")) == 3
    assert S.word_count_max("", max=10) == 1.0


# bullet_count


@pytest.mark.parametrize(
    "text,n",
    [
        ("- a\n- b\n- c", 3),
        ("* a\n* b\n* c", 3),
        ("• a\n• b\n• c", 3),
        ("1. a\n2. b\n3) c", 3),
        ("Intro line\n- a\n- b\nOutro", 2),
        ("no bullets here", 0),
        ("-not a bullet\n2.5 percent", 0),
    ],
)
def test_bullet_styles(text, n):
    assert len(S.bullet_lines(text)) == n


def test_bullet_count_score():
    assert S.bullet_count("- a\n- b\n- c", target=3) == 1.0
    assert S.bullet_count("- a\n- b", target=3) == pytest.approx(2 / 3)
    assert S.bullet_count("", target=3) == 0.0
    assert S.bullet_count("\n".join(["- x"] * 9), target=3) == 0.0


# reading_grade_max


def test_reading_grade_simple_and_hard():
    simple = "- Prices go up.\n- Your coins buy less.\n- Candy costs more now."
    hard = (
        "Inflation represents a sustained macroeconomic increase in the general price level "
        "of goods and services, diminishing the purchasing power of currency."
    )
    assert S.reading_grade_max(simple, max_grade=5) == 1.0
    assert S.reading_grade_max(hard, max_grade=5) < 0.2


def test_reading_grade_empty_is_zero():
    assert S.reading_grade_max("", max_grade=5) == 0.0


def test_strip_bullets_removes_markdown():
    assert S.strip_bullets("- **Bold** word\n2. _x_") == "Bold word\nx"


# keywords


def test_keywords_case_insensitive():
    text = "The $75 fee breaks Section 4.2 and the Grace Period."
    assert S.keywords_present(text, ["$75", "4.2", "grace period"]) == 1.0
    assert S.keywords_present("only $75 here", ["$75", "4.2", "grace period"]) == pytest.approx(1 / 3)
    assert S.keywords_absent("I am SORRY", ["sorry", "apologize", "apologise"]) == pytest.approx(2 / 3)
    assert S.keywords_absent("All good.", ["sorry", "apologize"]) == 1.0
    assert S.keywords_absent("", ["sorry"]) == 1.0
    assert S.keywords_present("", ["a", "b"]) == 0.0


# JSON

GOOD = '{"title": "Data Analyst", "company": "Brightline Health", "location": "Raleigh, NC", "work_mode": "Hybrid", "salary": null}'


def test_json_only_levels():
    assert S.json_only(GOOD) == 1.0
    assert S.json_only("  \n" + GOOD + "\n") == 1.0
    assert S.json_only("```json\n" + GOOD + "\n```") == 0.5
    assert S.json_only("```\n" + GOOD + "\n```") == 0.5
    assert S.json_only("Here is the JSON:\n" + GOOD) == 0.5
    assert S.json_only("not json at all") == 0.0
    assert S.json_only("") == 0.0
    assert S.json_only('"just a string"') == 0.5  # parses, but not an object


def test_json_keys_and_accuracy():
    expected = {"title": "Data Analyst", "company": "Brightline Health", "location": "Raleigh, NC", "work_mode": "hybrid"}
    keys = ["title", "company", "location", "work_mode", "salary"]
    assert S.json_keys_present(GOOD, keys) == 1.0
    assert S.json_keys_present('{"title": "x"}', keys) == pytest.approx(1 / 5)
    assert S.json_keys_present("nope", keys) == 0.0
    assert S.json_field_accuracy(GOOD, expected) == 1.0
    assert S.json_field_accuracy("```json\n" + GOOD + "\n```", expected) == 1.0
    wrong = GOOD.replace("Raleigh, NC", "Durham, NC").replace('"Hybrid"', "null")
    assert S.json_field_accuracy(wrong, expected) == pytest.approx(2 / 4)
    assert S.json_field_accuracy("garbage", expected) == 0.0


def test_json_field_accuracy_normalizes():
    expected = {"location": "Raleigh, NC"}
    assert S.json_field_accuracy('{"location": "  raleigh NC "}', expected) == 1.0


@pytest.mark.parametrize(
    "value,expected",
    [
        ("null", 1.0),
        ('""', 1.0),
        ('"Not specified"', 1.0),
        ('"N/A"', 1.0),
        ('"not listed in posting"', 1.0),
        ('"Unknown"', 1.0),
        ('{"min": null, "max": null}', 1.0),
        ('"$70,000"', 0.0),
        ("70000", 0.0),
        ('"Competitive"', 0.0),
        ('"$60k-$75k"', 0.0),
    ],
)
def test_json_field_null(value, expected):
    assert S.json_field_null('{"title": "x", "salary": %s}' % value, field="salary") == expected


def test_json_field_null_missing_key_and_unparseable():
    assert S.json_field_null('{"title": "x"}', field="salary") == 1.0
    assert S.json_field_null("no json", field="salary") == 0.0


def test_registry_complete():
    assert set(S.SCORERS) == {
        "word_count_max", "bullet_count", "reading_grade_max", "keywords_present", "keywords_absent",
        "json_only", "json_keys_present", "json_field_accuracy", "json_field_null", "on_topic", "starts_line_with",
        "keyword_groups_present", "lines_naming",
    }


@pytest.mark.parametrize(
    "text,score",
    [
        ("Here's a firm reply that doesn't apologize:\n\nHi Dana, the fee is invalid.", 1.0),
        ("Without apologizing, I must point out the fee is invalid.", 1.0),
        ("Here\u2019s a reply that doesn\u2019t apologize.", 1.0),
        ("I don't need to say sorry here.", 1.0),
        ("I'm sorry, but the fee is invalid.", 2 / 3),
        ("I apologize for the confusion. Sorry again.", 1 / 3),
        ("This reply doesn't apologize. I'm sorry though.", 2 / 3),
    ],
)
def test_keywords_absent_ignores_negated_mentions(text, score):
    assert S.keywords_absent(text, ["sorry", "apologize", "apologise"]) == pytest.approx(score)


def test_keyword_groups_present():
    groups = [["Nov 22", "November 22"], ["$18,500", "18,500", "18.5k"], ["Vendor B"]]
    assert S.keyword_groups_present("Go with vendor b by November 22 for $18,500.", groups) == 1.0
    assert S.keyword_groups_present("Go with Vendor B.", groups) == pytest.approx(1 / 3)
    assert S.keyword_groups_present("", groups) == 0.0


def test_keywords_absent_strict():
    assert S.keywords_absent("Reported by Marcus.", ["Marcus", "Elm St", "27701"], strict=True) == 0.0
    assert S.keywords_absent("Reported by Marcus.", ["Marcus", "Elm St", "27701"]) == pytest.approx(2 / 3)
    assert S.keywords_absent("No personal details.", ["Marcus"], strict=True) == 1.0


def test_lines_naming():
    need = [["chicken"], ["lemon"], ["garlic"], ["potato"]]
    plain = "4 chicken thighs\n2 lemons\n3 cloves garlic\n1 lb baby potatoes"
    assert S.lines_naming(plain, need, at_least=3) == 1.0
    assert S.lines_naming("- 4 chicken thighs\n- 2 lemons\n- 3 cloves garlic", need, at_least=3) == 1.0
    tips = "You're welcome! A couple of tips:\n- Arrange the potatoes around the chicken in a single layer so it roasts evenly.\n- Thighs are forgiving."
    assert S.lines_naming(tips, need, at_least=3) == 0.0
    every = need + [["salt"], ["olive oil"], ["oregano"]]
    assert S.lines_naming(plain, every, target=4) == 1.0
    assert S.lines_naming(plain + "\nsalt\nolive oil\noregano", every, target=4) == pytest.approx(0.25)
