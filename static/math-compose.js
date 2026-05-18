// Math editor: ALL show/hide state is in the template's HTML/CSS — a
// hidden checkbox (.editor-mode-toggle-state) drives `:checked ~ ...` sibling
// rules that swap textarea ↔ preview and the toggle's label text.
//
// This script only does what CSS cannot:
//   - enable the checkbox (template renders it `disabled` so no-JS
//     users can never get into a half-broken "preview" state),
//   - render the preview content when the toggle flips on,
//   - render the hidden body_html field on form submit.
//
// `core/text.split_body` mirrors `splitBody` below — keep them in sync.
// Depends on Temml being loaded first (provides global `temml`).
(function () {
  "use strict";
  if (typeof temml === "undefined") return;

  // Mirror of core.text.SEGMENT_RE. Display ($$...$$) matched first.
  var SEGMENT_RE = /\$\$([\s\S]+?)\$\$|(?<!\\)\$((?:\\\$|[^$\n])+?)\$/g;

  function escapeHtml(s) {
    return s
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function splitBody(text) {
    var out = [];
    var last = 0;
    SEGMENT_RE.lastIndex = 0;
    var m;
    while ((m = SEGMENT_RE.exec(text)) !== null) {
      if (m.index > last) {
        out.push({ kind: "text", content: text.slice(last, m.index) });
      }
      if (m[1] !== undefined) {
        out.push({ kind: "display_math", content: m[1] });
      } else {
        out.push({ kind: "inline_math", content: m[2] });
      }
      last = m.index + m[0].length;
    }
    if (last < text.length) {
      out.push({ kind: "text", content: text.slice(last) });
    }
    return out;
  }

  function renderSegment(seg) {
    if (seg.kind === "text") {
      return escapeHtml(seg.content).replace(/\r?\n/g, "<br>");
    }
    try {
      return temml.renderToString(seg.content, {
        displayMode: seg.kind === "display_math",
        throwOnError: false,
      });
    } catch (e) {
      return (
        '<code class="math-error" title="' +
        escapeHtml(e.message || "math error") +
        '">' +
        escapeHtml(seg.content) +
        "</code>"
      );
    }
  }

  function renderBody(text) {
    return splitBody(text).map(renderSegment).join("");
  }

  function wire(textarea) {
    var field = textarea.closest(".text-editor");
    if (!field) return;
    var checkbox = field.querySelector(".editor-mode-toggle-state");
    var preview = field.querySelector(".editor-preview");
    var hiddenName = textarea.getAttribute("data-math-compose");
    var form = textarea.form;
    var hidden = form ? form.querySelector('input[name="' + hiddenName + '"]') : null;

    // Template renders the checkbox `disabled` so no-JS users can never
    // trigger the CSS toggle (which would hide the textarea with no way
    // to recover). JS proves the renderer exists → enable it.
    if (checkbox) checkbox.disabled = false;

    if (checkbox && preview) {
      checkbox.addEventListener("change", function () {
        if (checkbox.checked) {
          preview.innerHTML = renderBody(textarea.value);
        }
      });
    }

    if (form && hidden) {
      form.addEventListener("submit", function () {
        hidden.value = renderBody(textarea.value);
      });
    }
  }

  function init() {
    var nodes = document.querySelectorAll("textarea[data-math-compose]");
    for (var i = 0; i < nodes.length; i++) wire(nodes[i]);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
