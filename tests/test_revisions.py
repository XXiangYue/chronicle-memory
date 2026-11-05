import pytest

from chronicle.revisions import Timeline


def fact(owner, value, kind, quote):
    return {
        "owner": owner,
        "attribute": "city",
        "value": value,
        "kind": kind,
        "quote": quote,
    }


def test_later_trip_and_other_person_do_not_replace_standing_city():
    memory = Timeline()
    memory.append(
        0, "I live in Xi'an.", [fact("user", "Xi'an", "standing", "I live in Xi'an.")]
    )
    memory.append(
        1,
        "I moved to Chengdu.",
        [fact("user", "Chengdu", "standing", "I moved to Chengdu.")],
    )
    memory.append(
        2,
        "I'm in Sanya this week.",
        [fact("user", "Sanya", "temporary", "I'm in Sanya this week.")],
    )
    memory.append(
        3,
        "Bo moved to Tianjin.",
        [fact("Bo", "Tianjin", "standing", "Bo moved to Tianjin.")],
    )
    assert memory.evidence("user", "city") == ["Session 1: I moved to Chengdu."]
    assert memory.evidence("user", "city", as_of=0) == ["Session 0: I live in Xi'an."]
    assert len(memory.evidence("user", "city", include_temporary=True)) == 2


def test_missing_quote_and_uncertain_updates_do_not_install_standing_facts():
    memory = Timeline()
    possible = fact("user", "Dali", "uncertain", "I might move to Dali")
    missing = fact("user", "Beijing", "standing", "I live in Beijing")
    memory.append(1, "I might move to Dali.", [possible, missing])
    memory.append(1, "I might move to Dali.", [possible])
    assert [e.kind for e in memory.entries] == ["uncertain"]
    assert memory.evidence("user", "city") == ["Session 1: I might move to Dali"]
    with pytest.raises(ValueError):
        memory.append(1, "different source", [])
