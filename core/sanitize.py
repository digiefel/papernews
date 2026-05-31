"""Central HTML sanitization for user-authored content.

Single chokepoint for every place untrusted HTML enters the app. New surfaces
(math in comments and submissions today, personal user HTML pages later)
compose a `Profile` from named building blocks rather than calling
`nh3.clean` directly. Adding a surface means defining or composing a profile
here; auditing the security surface means reading this file.

## How to extend

- Add a new building block as a frozen ``Profile`` near the others.
- Compose a public profile via ``|`` (e.g.
  ``USER_PAGE = INLINE_TEXT | MATHML | RICH_TEXT | ...``).
- Add tests in ``core/tests/test_sanitize.py``.

## Re-audit checklist (run on every Temml upgrade)

1. Render a corpus of representative formulas with the new Temml version.
2. Diff the set of element names and attributes against ``MATHML``. Add any
   missing names; consider removing anything no longer emitted.
3. Run the test suite; the ``COMMENT_BODY`` round-trip cases must still pass.

Temml version currently audited against: **v0.13.3**.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

import nh3


# Schemes permitted in any URL-bearing attribute (e.g. ``href``). nh3 strips
# attributes whose URL scheme is not in this set, neutralising ``javascript:``,
# ``data:``, etc.
_SAFE_URL_SCHEMES = frozenset({"http", "https", "mailto"})


@dataclass(frozen=True)
class Profile:
    """A named bundle of HTML sanitization rules.

    Profiles compose via ``|``: the result has the union of tags, the
    per-tag union of attributes, the union of URL schemes, and the
    ``link_rel`` of the left operand (by convention, composition starts
    from the text-side profile, which sets the link-relationship policy).
    """

    tags: frozenset[str] = frozenset()
    attributes: Mapping[str, frozenset[str]] = field(default_factory=dict)
    url_schemes: frozenset[str] = _SAFE_URL_SCHEMES
    link_rel: str | None = "nofollow noopener"

    def clean(self, html: str) -> str:
        """Sanitize ``html`` against this profile."""
        # nh3 wants mutable ``set`` instances; our frozensets need a copy.
        attrs = {tag: set(allowed) for tag, allowed in self.attributes.items()}
        return nh3.clean(
            html,
            tags=set(self.tags),
            attributes=attrs,
            url_schemes=set(self.url_schemes),
            link_rel=self.link_rel,
        )

    def __or__(self, other: "Profile") -> "Profile":
        merged_attrs: dict[str, frozenset[str]] = dict(self.attributes)
        for tag, allowed in other.attributes.items():
            merged_attrs[tag] = merged_attrs.get(tag, frozenset()) | allowed
        return Profile(
            tags=self.tags | other.tags,
            attributes=merged_attrs,
            url_schemes=self.url_schemes | other.url_schemes,
            link_rel=self.link_rel,
        )


# ---------------------------------------------------------------------------
# Building blocks. Each is a `Profile`; compose into public profiles below.
# ---------------------------------------------------------------------------


INLINE_TEXT = Profile(
    tags=frozenset({"br", "a", "code"}),
    attributes={
        # ``rel`` is managed by nh3 via ``link_rel`` (it overwrites any
        # incoming rel value), so it must NOT appear here.
        "a": frozenset({"href"}),
        "code": frozenset({"class"}),
    },
)
"""Plain-text primitives: line breaks, autolinked URLs, inline ``<code>``."""


# MathML element and attribute set that Temml v0.13.3 may emit. Derived from
# MathML 3 / Core, narrowed to Temml's vocabulary. Re-audit on Temml upgrade.
_MATHML_TAGS = frozenset({
    # Top-level / semantics
    "math", "semantics", "annotation", "annotation-xml",
    # Token elements
    "mi", "mn", "mo", "mtext", "ms", "mspace",
    # Layout
    "mrow", "mfrac", "msqrt", "mroot", "mstyle", "merror",
    "mpadded", "mphantom", "menclose",
    # Scripts and limits
    "msub", "msup", "msubsup", "munder", "mover", "munderover",
    "mmultiscripts", "mprescripts", "none",
    # Tabular
    "mtable", "mtr", "mtd", "mlabeledtr",
    # Interactive (rarely used; Temml may emit for accessibility)
    "maction",
})

# Attributes acceptable on any MathML element. ``style`` is intentionally
# allowed: Temml uses it for column spacing and similar layout that can't be
# expressed otherwise. CSS-based exfiltration would require an attacker to
# bypass Temml client-side, and modern browsers no longer support
# ``expression()`` or other code-executing CSS.
_MATHML_GLOBAL_ATTRS = frozenset({
    "id", "class", "style",
    "mathvariant", "mathsize", "mathcolor", "mathbackground",
    "displaystyle", "scriptlevel", "dir",
    "data-mjx-texclass",
})

# Start with global-only, then specialise per-tag where Temml emits more.
_MATHML_ATTRS: dict[str, frozenset[str]] = {tag: _MATHML_GLOBAL_ATTRS for tag in _MATHML_TAGS}
_MATHML_ATTRS["math"] |= frozenset({"xmlns", "display", "alttext"})
_MATHML_ATTRS["mo"] |= frozenset({
    "form", "fence", "separator", "lspace", "rspace",
    "stretchy", "symmetric", "maxsize", "minsize",
    "largeop", "movablelimits", "accent",
})
_MATHML_ATTRS["mfrac"] |= frozenset({
    "linethickness", "numalign", "denomalign", "bevelled",
})
_MATHML_ATTRS["mspace"] |= frozenset({"width", "height", "depth"})
_MATHML_ATTRS["mpadded"] |= frozenset({
    "width", "height", "depth", "voffset", "lspace",
})
_MATHML_ATTRS["mtable"] |= frozenset({
    "align", "columnalign", "rowalign", "columnlines", "rowlines",
    "frame", "framespacing", "columnwidth", "columnspacing", "rowspacing",
    "equalcolumns", "equalrows", "side", "minlabelspacing",
})
_MATHML_ATTRS["mtr"] |= frozenset({"columnalign", "rowalign"})
_MATHML_ATTRS["mtd"] |= frozenset({
    "columnalign", "rowalign", "columnspan", "rowspan",
})
_MATHML_ATTRS["mlabeledtr"] = _MATHML_ATTRS["mtr"]
_MATHML_ATTRS["mover"] |= frozenset({"accent", "align"})
_MATHML_ATTRS["munder"] |= frozenset({"accentunder", "align"})
_MATHML_ATTRS["munderover"] |= frozenset({"accent", "accentunder", "align"})
_MATHML_ATTRS["menclose"] |= frozenset({"notation"})
_MATHML_ATTRS["maction"] |= frozenset({"actiontype", "selection"})
_MATHML_ATTRS["annotation"] |= frozenset({"encoding", "definitionURL", "cd", "src"})
_MATHML_ATTRS["annotation-xml"] |= frozenset({"encoding", "definitionURL", "cd", "src"})
_MATHML_ATTRS["semantics"] |= frozenset({"definitionURL", "cd"})


MATHML = Profile(
    tags=_MATHML_TAGS,
    attributes={tag: attrs for tag, attrs in _MATHML_ATTRS.items()},
)
"""MathML vocabulary as emitted by Temml — see the audit checklist above."""


# ---------------------------------------------------------------------------
# Public profiles — what call sites actually use.
# ---------------------------------------------------------------------------


COMMENT_BODY = INLINE_TEXT | MATHML
"""Submission and comment bodies: plain text primitives plus math."""
