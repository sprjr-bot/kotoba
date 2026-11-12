import pytest

from kotoba.langs import all_languages, get, resolve
from kotoba.langs.english import English
from kotoba.langs.japanese import Japanese


def test_registry_includes_japanese_and_english():
    codes = {lang.code for lang in all_languages()}
    assert "jisho" in codes
    assert "wordnet" in codes


def test_get_returns_language_instance():
    ja = get("jisho")
    en = get("wordnet")
    assert isinstance(ja, Japanese)
    assert isinstance(en, English)
    assert ja.name == "Japanese"
    assert en.name == "English"


def test_get_unknown_code_raises():
    with pytest.raises(KeyError):
        get("klingon")


def test_resolve_alias_to_canonical_code():
    assert resolve("jp") == "jisho"
    assert resolve("jisho") == "jisho"
    assert resolve("en") == "wordnet"
    assert resolve("wordnet") == "wordnet"


def test_resolve_unknown_alias_raises():
    with pytest.raises(KeyError):
        resolve("tlh")


def test_japanese_autodetect():
    ja = get("jisho")
    assert ja.autodetect("猫")
    assert ja.autodetect("コトバ")
    assert ja.autodetect("あいさつ")
    assert not ja.autodetect("hello")
    assert not ja.autodetect("123")


def test_english_autodetect():
    en = get("wordnet")
    assert en.autodetect("hello")
    assert en.autodetect("WordNet")
    assert not en.autodetect("猫")
    assert not en.autodetect("123")


def test_japanese_datasets_order():
    ja = get("jisho")
    datasets = ja.datasets()
    assert datasets[0] == "jmdict-eng"
    assert datasets[-1] == "radkfile"


def test_english_datasets_empty():
    en = get("wordnet")
    assert en.datasets() == []
