from __future__ import annotations

from kotoba.langs.base import Language
from kotoba.langs.english import English
from kotoba.langs.japanese import Japanese

_REGISTRY: dict[str, Language] = {}
_ALIASES: dict[str, str] = {}


def _register(language: Language) -> None:
    _REGISTRY[language.code] = language
    for alias in language.aliases:
        _ALIASES[alias] = language.code


_register(Japanese())
_register(English())


def get(code: str) -> Language:
    """Return the language registered under *code*.

    Raises :class:`KeyError` when the code is not known.
    """
    if code in _REGISTRY:
        return _REGISTRY[code]
    raise KeyError(code)


def resolve(alias: str) -> str:
    """Resolve an alias to a canonical language code.

    Raises :class:`KeyError` when the alias is not known.
    """
    return _ALIASES[alias]


def all_languages() -> list[Language]:
    """Return all registered languages."""
    return list(_REGISTRY.values())


def for_code(code: str) -> Language | None:
    """Return the language with matching code, alias, or language_code."""
    if code in _REGISTRY:
        return _REGISTRY[code]
    canonical = _ALIASES.get(code)
    if canonical is not None:
        return _REGISTRY.get(canonical)
    for lang in _REGISTRY.values():
        if getattr(lang, "language_code", "") == code:
            return lang
    return None


__all__ = ["Language", "get", "resolve", "all_languages", "for_code"]
