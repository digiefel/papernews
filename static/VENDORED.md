# Vendored static assets

## temml.min.js, temml.css

[Temml](https://temml.org/) — LaTeX-to-MathML converter. Vendored verbatim from
the upstream release; do not edit in place.

- **Version:** v0.13.3
- **Upstream:** https://github.com/ronkok/Temml
- **Files:**
  - `temml.min.js` — sourced from `https://cdn.jsdelivr.net/npm/temml@0.13.3/dist/temml.min.js`
  - `temml.css` — sourced from `https://cdn.jsdelivr.net/npm/temml@0.13.3/dist/Temml-Local.css`

To upgrade:

```sh
V=<new-version>
curl -sSL -o static/temml.min.js "https://cdn.jsdelivr.net/npm/temml@${V}/dist/temml.min.js"
curl -sSL -o static/temml.css    "https://cdn.jsdelivr.net/npm/temml@${V}/dist/Temml-Local.css"
```

After upgrading, re-audit the `MATHML` allowlist in `core/sanitize.py` against
the new output (check that the set of tags/attributes Temml emits is still a
subset of what the allowlist permits) and run the test suite.

The `temml.css` file references a `Temml.woff2` font for a small set of
specialty characters (math script capitals). We do not ship the font — readers
fall back to system fonts for those glyphs. If we ever care, vendor
`Temml.woff2` from the same release alongside the CSS.
