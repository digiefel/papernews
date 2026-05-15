"""BibTeX parsing and DOI metadata extraction.

Best-effort utilities to extract a handful of fields from BibTeX text or a DOI.
PLAN.md: parse only title, author, year, journal/booktitle (→ source), DOI, URL.
"""

import re
import urllib.error
import urllib.request

_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")
_BIB_FIELD_RE = re.compile(
    r"(\w+)\s*=\s*(\{(?:[^{}]|\{[^{}]*\})*\}|\"[^\"]*\"|[^,\n]+)\s*,?",
    re.DOTALL,
)


def normalize_doi(raw):
    """Strip common prefixes/whitespace, lowercase, validate. Return str or None."""
    if not raw:
        return None
    text = raw.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "http://dx.doi.org/",
                   "https://dx.doi.org/", "doi:"):
        if text.lower().startswith(prefix):
            text = text[len(prefix):]
            break
    text = text.strip().lower()
    if _DOI_RE.match(text):
        return text
    return None


def _strip_braces(value):
    value = value.strip().rstrip(",").strip()
    if len(value) >= 2 and value[0] in "{\"" and value[-1] in "}\"":
        value = value[1:-1]
    # Remove single-level inner braces used for capitalization preservation.
    value = re.sub(r"[{}]", "", value)
    return value.strip()


def parse_bibtex(text):
    """Parse the first @entry in `text`. Return dict of known fields, or None."""
    if not text:
        return None
    match = re.search(r"@\w+\s*\{[^,]*,(.*)\}\s*$", text.strip(), re.DOTALL)
    if not match:
        # Try without trailing-brace anchor (be lenient).
        match = re.search(r"@\w+\s*\{[^,]*,(.*)", text.strip(), re.DOTALL)
        if not match:
            return None

    body = match.group(1)
    fields = {}
    for fname, fvalue in _BIB_FIELD_RE.findall(body):
        fields[fname.lower()] = _strip_braces(fvalue)

    if not fields:
        return None

    result = {}
    if "title" in fields:
        result["title"] = fields["title"]
    if "author" in fields:
        authors = [a.strip() for a in re.split(r"\s+and\s+", fields["author"])]
        authors = [a for a in authors if a]
        if authors:
            result["authors"] = authors
    if "year" in fields:
        m = re.search(r"\d{4}", fields["year"])
        if m:
            result["year"] = int(m.group(0))
    for key in ("journal", "booktitle"):
        if fields.get(key):
            result["source"] = fields[key]
            break
    if fields.get("doi"):
        result["doi"] = fields["doi"]
    if fields.get("url"):
        result["url"] = fields["url"]
    return result or None


def fetch_bibtex_for_doi(doi, timeout=5):
    """GET https://doi.org/<doi> with Accept: application/x-bibtex. Return body or None."""
    if not doi:
        return None
    req = urllib.request.Request(
        f"https://doi.org/{doi}",
        headers={"Accept": "application/x-bibtex"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read().decode(charset, errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


def extract_metadata(pasted_text):
    """Return (metadata_dict, source_kind) or (None, None).

    source_kind is "bibtex" or "doi" — useful for the UI notice.
    If text looks like BibTeX, parse directly. Else try DOI → fetch → parse.
    """
    if not pasted_text:
        return None, None
    text = pasted_text.strip()
    if text.startswith("@"):
        return parse_bibtex(text), "bibtex"
    doi = normalize_doi(text)
    if doi:
        bibtex = fetch_bibtex_for_doi(doi)
        if bibtex:
            parsed = parse_bibtex(bibtex) or {}
            parsed.setdefault("doi", doi)
            return parsed, "doi"
        # We recognized a DOI but couldn't fetch — still useful.
        return {"doi": doi}, "doi"
    return None, None
