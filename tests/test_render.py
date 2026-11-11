from kotoba.model import Entry, LookupResult, Sense
from kotoba.render import render_error, render_text


def test_render_jisho_entry():
    result = LookupResult(
        query="猫",
        source="jisho",
        entries=(
            Entry(
                headword="猫",
                reading="ねこ",
                senses=(Sense(pos=("Noun",), glosses=("cat",)),),
                tags=("common",),
            ),
            Entry(
                headword="黒猫",
                reading="くろねこ",
                senses=(Sense(pos=("Noun",), glosses=("black cat",)),),
            ),
        ),
    )
    text = render_text(result)
    assert text.startswith("猫【ねこ】\n  • Noun: cat\n  tags: common\n\n黒猫【くろねこ】")
    assert text.endswith("\n")
    assert text.count("\n") == 6


def test_render_wordnet_entry():
    result = LookupResult(
        query="love",
        source="wordnet",
        entries=(
            Entry(
                headword="love",
                reading=None,
                senses=(
                    Sense(pos=("noun",), glosses=("a strong positive emotion", "a score of zero")),
                    Sense(pos=("verb",), glosses=("have a great affection",)),
                ),
            ),
        ),
    )
    text = render_text(result)
    assert "love\n" in text
    assert "noun:" in text
    assert "verb:" in text


def test_render_no_results():
    result = LookupResult(query="xyz", source="jisho", entries=())
    assert render_text(result) == "xyz: no results\n"


def test_render_error():
    assert render_error("猫", "network error") == "猫: network error\n"


def test_render_ends_with_single_newline():
    result = LookupResult(
        query="a",
        source="jisho",
        entries=(Entry(headword="a", reading=None, senses=(Sense(pos=("Noun",), glosses=("b",)),)),),
    )
    text = render_text(result)
    assert text.endswith("\n")
    assert not text.endswith("\n\n")


def test_render_wraps_with_hanging_indent():
    from kotoba.model import Entry, LookupResult, Sense

    result = LookupResult(
        query="猫背",
        source="jisho",
        entries=(
            Entry(
                headword="猫背",
                reading="ねこぜ",
                senses=(Sense(pos=("Noun", "Na-adjective"), glosses=(
                    "bent back; hunchback; stoop; a long gloss that has to wrap at a narrow width",
                )),),
            ),
        ),
    )
    out = render_text(result, width=40)
    wrapped = [line for line in out.splitlines() if line.startswith("      ")]
    assert wrapped, out
