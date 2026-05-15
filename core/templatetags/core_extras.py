from django import template

register = template.Library()


@register.filter
def author_names(submission):
    """Return ordered list of author names for a submission."""
    return [sa.author.name for sa in submission.submission_authors.all()]


@register.filter
def join_authors(names):
    """Render a list of author names: comma-joined, with 'et al.' past 3."""
    if not names:
        return ""
    if len(names) <= 3:
        return "; ".join(names)
    return "; ".join(names[:3]) + " et al."
