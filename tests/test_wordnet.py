import pytest

from kotoba.model import Entry, LookupResult, Sense
from kotoba.wordnet import LookupError, _parse, fetch

LOVE_NOUN_FIXTURE = """\n
WordNet 3.1 Copyright 2006 by Princeton University.  All rights reserved.

Noun

1. love: a strong positive emotion of regard and affection
2. love, passion: any object of warm affection or devotion;
3. beloved, dear, dearest, honey, love: a beloved person
4. love: a score of zero in tennis or squash
5. sexual love, lovemaking, making love, love, sexual intercourse: sexual activities (often including sexual intercourse) between two people

Verb

1. love: have a great affection or liking for
2. love, enjoy, like: get pleasure from
3. love: be enamored or in love with
"""


def test_parse_noun_with_multiple_senses():
    result = _parse("love", LOVE_NOUN_FIXTURE)
    assert result.query == "love"
    assert result.source == "wordnet"
    assert len(result.entries) == 2
    noun_entry = next(e for e in result.entries if e.senses[0].pos == ("noun",))
    assert noun_entry.headword == "love"
    assert noun_entry.reading is None
    assert len(noun_entry.senses) == 1
    assert len(noun_entry.senses[0].glosses) == 5
    assert noun_entry.senses[0].glosses[0] == "a strong positive emotion of regard and affection"


def test_parse_includes_verb_section():
    result = _parse("love", LOVE_NOUN_FIXTURE)
    verb_entry = next(e for e in result.entries if e.senses[0].pos == ("verb",))
    assert len(verb_entry.senses[0].glosses) == 3


def test_parse_no_entries():
    result = _parse("xyzqwerty", "")
    assert result.entries == ()


def test_fetch_without_wn(monkeypatch):
    monkeypatch.setattr("kotoba.langs.english.shutil.which", lambda cmd: None)
    with pytest.raises(LookupError, match="wordnet not installed"):
        fetch("love")


@pytest.mark.xfail(reason="fixture capture pending host run", strict=False)
def test_fetch_love_live():
    result = fetch("love")
    assert result.entries
    assert result.entries[0].senses
