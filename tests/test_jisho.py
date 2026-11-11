import json
from pathlib import Path

import httpx
import pytest

from kotoba.jisho import LookupError, fetch
from kotoba.model import Entry, LookupResult, Sense


NEKO_FIXTURE = {
    "data": [
        {
            "slug": "猫",
            "is_common": True,
            "jlpt": ["jlpt-n5"],
            "tags": ["wanikani6"],
            "japanese": [{"word": "猫", "reading": "ねこ"}],
            "senses": [
                {
                    "english_definitions": ["cat"],
                    "parts_of_speech": ["Noun"],
                },
            ],
        },
        {
            "slug": "黒猫",
            "is_common": False,
            "tags": [],
            "japanese": [{"word": "黒猫", "reading": "くろねこ"}],
            "senses": [
                {
                    "english_definitions": ["black cat"],
                    "parts_of_speech": ["Noun"],
                },
            ],
        },
    ],
}


def test_fetch_maps_fixture(monkeypatch):
    def fake_get(url, *, timeout):
        return httpx.Response(200, json=NEKO_FIXTURE)

    monkeypatch.setattr("httpx.get", fake_get)
    result = fetch("猫")
    assert result.query == "猫"
    assert result.source == "jisho"
    assert len(result.entries) == 2
    assert result.entries[0] == Entry(
        headword="猫",
        reading="ねこ",
        senses=(Sense(pos=("Noun",), glosses=("cat",)),),
        tags=("common", "jlpt-n5", "wanikani6"),
    )
    assert result.url == "https://jisho.org/search/%E7%8C%AB"


def test_fetch_capped_at_twelve(monkeypatch):
    payload = {"data": [{"slug": f"entry-{i}", "japanese": [{"word": f"x{i}"}], "senses": []} for i in range(20)]}

    def fake_get(url, *, timeout):
        return httpx.Response(200, json=payload)

    monkeypatch.setattr("httpx.get", fake_get)
    result = fetch("many")
    assert len(result.entries) == 12


def test_fetch_network_error(monkeypatch):
    def fake_get(url, *, timeout):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr("httpx.get", fake_get)
    with pytest.raises(LookupError, match="network error"):
        fetch("猫")


def test_fetch_non_200(monkeypatch):
    def fake_get(url, *, timeout):
        return httpx.Response(503, text="unavailable")

    monkeypatch.setattr("httpx.get", fake_get)
    with pytest.raises(LookupError, match="jisho returned 503"):
        fetch("猫")


@pytest.mark.network
@pytest.mark.skip(reason="network tests off by default")
def test_fetch_live():
    result = fetch("猫")
    assert result.entries


def test_no_results(monkeypatch):
    def fake_get(url, *, timeout):
        return httpx.Response(200, json={"data": []})

    monkeypatch.setattr("httpx.get", fake_get)
    result = fetch("xyznotaword")
    assert result.entries == ()
    assert result.url
