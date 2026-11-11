from kotoba.model import Entry, LookupResult, Sense


def test_lookup_result_round_trip():
    result = LookupResult(
        query="猫",
        source="jisho",
        entries=(
            Entry(
                headword="猫",
                reading="ねこ",
                senses=(Sense(pos=("noun",), glosses=("cat",)),),
                tags=("common", "jlpt-n5"),
            ),
        ),
        url="https://jisho.org/search/%E7%8C%AB",
    )
    assert result.query == "猫"
    assert result.source == "jisho"
    assert len(result.entries) == 1
    assert result.entries[0].tags == ("common", "jlpt-n5")


def test_empty_entries_repr():
    result = LookupResult(query="xyz", source="wordnet", entries=())
    assert repr(result) == "LookupResult(query='xyz', source='wordnet', entries=(), url=None)"
    assert result.url is None
