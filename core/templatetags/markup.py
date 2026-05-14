from django import template
from django.utils.html import urlize
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def render_text(text):
    """Render user-submitted text to HTML: escape, autolink URLs, newlines to <br>.

    The single place post and comment bodies become HTML. Any richer markup
    (math, code blocks) belongs here so call sites and templates stay unchanged.
    """
    if not text:
        return ""
    text = text.replace("\r\n", "\n")
    # urlize() escapes its input before autolinking, so the result is safe to mark.
    return mark_safe(urlize(text, nofollow=True).replace("\n", "<br>"))
