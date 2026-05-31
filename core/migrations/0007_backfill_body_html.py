"""Backfill body_html for rows that pre-date the field.

Existing rows have no math (the feature didn't exist), so the rendered HTML is
just the same plain-text-with-autolinks render the display path used before.
"""
from django.db import migrations


def _fallback(text: str) -> str:
    # Inlined to avoid importing from core.text — migrations should stand on
    # their own and Django's util surface here is stable. Matches the policy
    # in core.text.fallback_body_html: escape first (urlize alone leaves
    # surrounding HTML unescaped when called from Python), then autolink.
    from django.utils.html import escape, urlize
    if not text:
        return ""
    text = text.replace("\r\n", "\n")
    text = escape(text)
    text = urlize(text, nofollow=True)
    return text.replace("\n", "<br>")


def backfill(apps, schema_editor):
    Submission = apps.get_model("core", "Submission")
    Comment = apps.get_model("core", "Comment")
    for Model in (Submission, Comment):
        for row in Model.objects.filter(body_html="").iterator():
            if row.body:
                row.body_html = _fallback(row.body)
                row.save(update_fields=["body_html"])


def noop(apps, schema_editor):
    # The reverse is "clear body_html" — but reversing this migration is
    # equivalent to discarding the field, which 0006_body_html handles. Leave
    # the data alone here so accidental reversal doesn't lose anything.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0006_body_html"),
    ]

    operations = [
        migrations.RunPython(backfill, noop),
    ]
