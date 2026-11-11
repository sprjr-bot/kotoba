from __future__ import annotations

from kotoba.model import Entry, LookupResult, Sense


def render_text(result: LookupResult) -> str:
    if not result.entries:
        return f"{result.query}: no results\n"

    blocks: list[str] = []
    for entry in result.entries:
        head = entry.headword
        if entry.reading:
            head += f"【{entry.reading}】"
        lines = [head]
        for sense in entry.senses:
            pos = ", ".join(sense.pos) or "?"
            glosses = "; ".join(sense.glosses)
            lines.append(f"  • {pos}: {glosses}")
        if entry.tags:
            lines.append(f"  tags: {', '.join(entry.tags)}")
        blocks.append("\n".join(lines))

    return "\n\n".join(blocks) + "\n"


def render_error(query: str, msg: str) -> str:
    return f"{query}: {msg}\n"
