from __future__ import annotations

import textwrap

from kotoba.model import LookupResult


def render_text(result: LookupResult, width: int | None = None) -> str:
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
            line = f"  • {pos}: {glosses}"
            if width:
                line = textwrap.fill(line, width=width, subsequent_indent=" " * 6, break_long_words=False)
            lines.append(line)
        if entry.tags:
            lines.append(f"  tags: {', '.join(entry.tags)}")
        blocks.append("\n".join(lines))

    return "\n\n".join(blocks) + "\n"


def render_error(query: str, msg: str) -> str:
    return f"{query}: {msg}\n"
