from style_check import check_story, check_text, count_sentences, find_copied_phrases

CLEAN = dict(
    title="Royal Navy orders twelve drone interceptors",
    description="The Ministry of Defence has signed a £40 million contract. Deliveries begin in 2027.",
    bullets=[
        "The order covers twelve interceptor systems for Type 45 destroyers.",
        "The U.S. supplier will assemble the systems in Scotland.",
    ],
)


def problems(**overrides):
    story = {**CLEAN, **overrides}
    return check_story(story["title"], story["description"], story["bullets"], source_texts=[])


def test_clean_story_passes():
    assert problems() == []


def test_title_length():
    assert any("Title is" in p for p in problems(title="x" * 60))
    assert not any("Title is" in p for p in problems(title="x" * 59))


def test_description_length_and_sentences():
    assert any("Description is" in p for p in problems(description=("Word " * 30).strip() + ". End."))
    assert any("1 sentence" in p for p in problems(description="Only one sentence here."))
    assert any("3 sentence" in p for p in problems(description="One. Two. Three."))


def test_sentence_count_ignores_abbreviations_and_decimals():
    assert count_sentences("The U.S. Army spent $1.5 billion. Gen. Smith approved it.") == 2


def test_bullet_count_and_length():
    assert any("4 bullets" in p for p in problems(bullets=["a."] * 4))
    assert any("0 bullets" in p for p in problems(bullets=[]))
    assert any("Bullet 1 is 26 words" in p for p in problems(bullets=["word " * 26]))


def test_contractions():
    for text in ["It's ready.", "They don't agree.", "We've signed.", "Officials’ll meet."]:
        assert any("contraction" in p for p in check_text("T", text)), text
    assert check_text("T", "The navy's new ship.") == []


def test_dashes():
    assert any("em dash" in p for p in check_text("T", "A ship — the first"))
    assert any("en dash" in p for p in check_text("T", "A ship – the first"))
    assert check_text("T", "A long-range missile") == []


def test_us_must_have_dots():
    assert any('"U.S."' in p for p in check_text("T", "The US Army"))
    assert check_text("T", "The U.S. Army") == []
    assert check_text("T", "USB drives and USAF jets") == []


def test_think_tank():
    assert any("think tank" in p for p in check_text("T", "A think-tank report"))


def test_not_a_it_is_b():
    assert any("not A" in p for p in check_text("T", "This is not a test, it is a deployment."))
    assert check_text("T", "The deal is not yet signed, but talks continue.") == []


def test_american_spellings():
    assert any('"defense"' in p for p in check_text("T", "a defense budget"))
    assert any('"organization"' in p for p in check_text("T", "the organization said"))
    assert any('"analyzed"' in p for p in check_text("T", "data was analyzed"))
    assert any('"program"' in p for p in check_text("T", "the drone program"))
    # Proper nouns and legitimate British uses pass.
    assert check_text("T", "the U.S. Department of Defense") == []
    assert check_text("T", "the Center for Naval Analyses") == []
    assert check_text("T", "a computer program and a programme of work") == []
    assert check_text("T", "the prize and its size") == []


def test_copied_phrases():
    source = "The contract was awarded to BAE Systems for the delivery of six new frigates by 2030."
    copied = find_copied_phrases(
        "Officials said the contract was awarded to BAE Systems for the delivery of ships.", [source])
    assert copied == ["the contract was awarded to bae systems for the delivery of"]
    assert find_copied_phrases("BAE Systems will deliver six frigates by 2030.", [source]) == []


def test_copied_phrase_reported_by_check_story():
    src = "The Ministry of Defence has signed a forty million pound contract for drones."
    out = check_story(CLEAN["title"], CLEAN["description"],
                      ["The Ministry of Defence has signed a forty million pound contract."], [src])
    assert any("Copied wording" in p for p in out)
