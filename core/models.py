from urllib.parse import urlparse

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse


class Profile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    verified = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.user.username


class SubmissionManager(models.Manager):
    def visible(self):
        return self.filter(is_removed=False)


class Submission(models.Model):
    title = models.CharField(max_length=300)
    url = models.URLField(max_length=2000, blank=True)
    body = models.TextField(blank=True)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="submissions"
    )
    created = models.DateTimeField(auto_now_add=True, db_index=True)
    is_removed = models.BooleanField(default=False)
    # Cached ranking column; unused this milestone (ranking is computed in Python).
    # Present now so a future scaling pass is a backfill, not a migration on a large table.
    score = models.IntegerField(default=0)

    objects = SubmissionManager()

    class Meta:
        ordering = ["-created"]

    def __str__(self):
        return self.title

    @property
    def kind(self):
        return "link" if self.url else "text"

    @property
    def domain(self):
        if not self.url:
            return ""
        return urlparse(self.url).netloc.removeprefix("www.")

    def get_absolute_url(self):
        return reverse("submission_detail", args=[self.pk])

    def clean(self):
        has_url = bool(self.url.strip())
        has_body = bool(self.body.strip())
        if has_url and has_body:
            raise ValidationError("Provide either a URL or body text, not both.")
        if not has_url and not has_body:
            raise ValidationError("Provide either a URL or body text.")


class Comment(models.Model):
    submission = models.ForeignKey(
        Submission, on_delete=models.CASCADE, related_name="comments", db_index=True
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="comments"
    )
    body = models.TextField()
    created = models.DateTimeField(auto_now_add=True, db_index=True)
    is_removed = models.BooleanField(default=False)

    class Meta:
        ordering = ["created"]

    def __str__(self):
        return f"comment by {self.author.username}"

    def get_absolute_url(self):
        return f"{self.submission.get_absolute_url()}#comment-{self.pk}"

    def clean(self):
        if self.parent_id and self.parent.submission_id != self.submission_id:
            raise ValidationError(
                "A reply must belong to the same submission as its parent."
            )


class SubmissionVote(models.Model):
    submission = models.ForeignKey(
        Submission, on_delete=models.CASCADE, related_name="votes"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="submission_votes",
    )
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["submission", "user"], name="uniq_submission_vote"
            )
        ]


class CommentVote(models.Model):
    comment = models.ForeignKey(
        Comment, on_delete=models.CASCADE, related_name="votes"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="comment_votes",
    )
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["comment", "user"], name="uniq_comment_vote"
            )
        ]
