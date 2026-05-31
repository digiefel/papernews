"""Plain-text utilities for splitting math out of bodies and rendering the
no-JavaScript fallback for ``body_html``.

The JavaScript that powers the live preview mirrors ``split_body`` (see
``static/math-compose.js``). Keep the two in sync: they're the only piece of
logic that exists in both languages.
"""
from __future__ import annotations

import re
from typing import Literal

from django.utils.html import escape, urlize


Segment = tuple[Literal["text", "inline_math", "display_math"], str]


# Match either ``$$…$$`` (display math, may span lines) or ``$…$`` (inline math,
# single line, not preceded by a literal ``\``). Display is tried first because
# it's the longer match; once a ``$$`` opens, we expect another to close before
# an inline ``$`` claims the rest. ``re.DOTALL`` makes ``.`` cross newlines in
# the display branch; the inline branch uses ``[^$\n]`` to stay single-line.
SEGMENT_RE = re.compile(
    r"\$\$(?P<display>.+?)\$\$"
    r"|(?<!\\)\$(?P<inline>(?:\\\$|[^$\n])+?)\$",
    re.DOTALL,
)


def split_body(text: str) -> list[Segment]:
    """Split ``text`` into ordered text and math segments.

    Each segment is a ``(kind, content)`` tuple where ``kind`` is
    ``"text"``, ``"inline_math"``, or ``"display_math"``. For math
    segments, ``content`` is the LaTeX source without the surrounding
    delimiters.
    """
    if not text:
        return []
    segments: list[Segment] = []
    last = 0
    for m in SEGMENT_RE.finditer(text):
        if m.start() > last:
            segments.append(("text", text[last:m.start()]))
        if m.group("display") is not None:
            segments.append(("display_math", m.group("display")))
        else:
            segments.append(("inline_math", m.group("inline")))
        last = m.end()
    if last < len(text):
        segments.append(("text", text[last:]))
    return segments


def fallback_body_html(text: str) -> str:
    """Render plain text to HTML without invoking the math renderer.

    Used when the client did not POST a ``body_html`` field (e.g. JavaScript
    is disabled, or a non-browser client). Math delimiters survive as literal
    text — the same way they appeared in the source — so readers see the raw
    LaTeX rather than nothing.

    The returned string is HTML-safe. We do the escaping ourselves rather
    than relying on ``urlize``: when called from Python (not a template),
    ``urlize`` only escapes characters inside the URLs it finds, leaving
    arbitrary HTML in the surrounding text untouched. We escape first, then
    autolink the now-safe-but-still-recognisable URLs.
    """
    if not text:
        return ""
    text = text.replace("\r\n", "\n")
    text = escape(text)
    text = urlize(text, nofollow=True)
    return text.replace("\n", "<br>")
