from django import template
from django.utils.html import urlize
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def render_text(text):
    """Minimal post/comment markup: escape, autolink URLs, keep line breaks.

    Rich markup (math, code blocks) is deferred; when added it goes here so
    templates don't change.
    """
    if not text:
        return ""
    text = text.replace("\r\n", "\n")
    # urlize escapes the input internally before autolinking.
    return mark_safe(urlize(text, nofollow=True).replace("\n", "<br>"))
