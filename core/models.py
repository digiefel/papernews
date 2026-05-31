from urllib.parse import urlparse

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q
from django.urls import reverse


HEX_COLOR_VALIDATOR = RegexValidator(
    regex=r"^#[0-9a-fA-F]{6}$",
    message="Use a 6-digit hex color like #ff6600.",
)


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
    # Rendered HTML for `body`: math (MathML) + autolinked text. Populated by
    # the form layer (sanitized client-supplied render, with a server-side
    # text-only fallback if the client omitted it). Display paths read this
    # directly; never re-render at display time. See core/sanitize.py.
    body_html = models.TextField(blank=True)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="submissions"
    )
    created = models.DateTimeField(auto_now_add=True, db_index=True)
    is_removed = models.BooleanField(default=False)
    # Nothing writes this yet — front_page ranks live (see ranking.py). It exists
    # so switching to a cached rank is a backfill, not a schema change on a big table.
    score = models.IntegerField(default=0)
    year = models.PositiveSmallIntegerField(null=True, blank=True)
    source = models.CharField(max_length=200, blank=True)
    doi = models.CharField(max_length=200, blank=True, db_index=True)
    authors = models.ManyToManyField(
        "Author", through="SubmissionAuthor", related_name="submissions"
    )

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

    def save(self, *args, **kwargs):
        # Invariant: body_html is populated whenever body is non-empty.
        # The form path sets body_html explicitly (sanitized client render).
        # Any other write path — tests, shell, future imports — gets the
        # safe text-only fallback automatically.
        if self.body and not self.body_html:
            from .text import fallback_body_html
            self.body_html = fallback_body_html(self.body)
        super().save(*args, **kwargs)


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
    # See Submission.body_html — same contract for comments.
    body_html = models.TextField(blank=True)
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

    def save(self, *args, **kwargs):
        # See Submission.save — same invariant.
        if self.body and not self.body_html:
            from .text import fallback_body_html
            self.body_html = fallback_body_html(self.body)
        super().save(*args, **kwargs)


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


class Save(models.Model):
    submission = models.ForeignKey(
        Submission, on_delete=models.CASCADE, related_name="saves"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saves"
    )
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["submission", "user"], name="uniq_save")
        ]


class Community(models.Model):
    slug = models.SlugField(max_length=32, unique=True)
    name = models.CharField(max_length=80)
    description = models.TextField(blank=True)
    is_private = models.BooleanField(default=False)
    color = models.CharField(
        max_length=7,
        default="#ff6600",
        validators=[HEX_COLOR_VALIDATOR],
        help_text="Accent color shown on the community page and listings.",
    )
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["slug"]
        verbose_name_plural = "communities"

    def __str__(self):
        return f"c/{self.slug}"

    def get_absolute_url(self):
        return reverse("community_detail", args=[self.slug])


class CommunityMembership(models.Model):
    community = models.ForeignKey(
        Community, on_delete=models.CASCADE, related_name="memberships"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="community_memberships",
    )
    is_moderator = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["community", "user"], name="uniq_community_membership"
            )
        ]

    def __str__(self):
        return f"{self.user.username} in {self.community}"


class _ScopeBase(models.Model):
    KIND_GLOBAL = "global"
    KIND_COMMUNITY = "community"
    KIND_PRIVATE = "private"
    KIND_CHOICES = [
        (KIND_GLOBAL, "Global"),
        (KIND_COMMUNITY, "Community"),
        (KIND_PRIVATE, "Private"),
    ]

    kind = models.CharField(max_length=16, choices=KIND_CHOICES)
    community = models.ForeignKey(
        Community, on_delete=models.CASCADE, null=True, blank=True
    )

    class Meta:
        abstract = True

    def clean(self):
        if self.kind == self.KIND_COMMUNITY and self.community_id is None:
            raise ValidationError("Community-scoped rows require a community.")
        if self.kind != self.KIND_COMMUNITY and self.community_id is not None:
            raise ValidationError(
                "Only community-scoped rows may set a community."
            )


class SubmissionScope(_ScopeBase):
    submission = models.ForeignKey(
        Submission, on_delete=models.CASCADE, related_name="scopes"
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                name="submissionscope_community_when_community_kind",
                condition=(
                    Q(kind="community", community__isnull=False)
                    | (~Q(kind="community") & Q(community__isnull=True))
                ),
            ),
            models.UniqueConstraint(
                fields=["submission", "community"],
                condition=Q(kind="community"),
                name="uniq_submission_community_scope",
            ),
            models.UniqueConstraint(
                fields=["submission"],
                condition=Q(kind="global"),
                name="uniq_submission_global_scope",
            ),
        ]

    def __str__(self):
        if self.kind == self.KIND_COMMUNITY:
            return f"submission#{self.submission_id} in {self.community}"
        return f"submission#{self.submission_id} {self.kind}"


class CommentScope(_ScopeBase):
    comment = models.ForeignKey(
        Comment, on_delete=models.CASCADE, related_name="scopes"
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                name="commentscope_community_when_community_kind",
                condition=(
                    Q(kind="community", community__isnull=False)
                    | (~Q(kind="community") & Q(community__isnull=True))
                ),
            ),
            models.UniqueConstraint(
                fields=["comment", "community"],
                condition=Q(kind="community"),
                name="uniq_comment_community_scope",
            ),
            models.UniqueConstraint(
                fields=["comment"],
                condition=Q(kind="global"),
                name="uniq_comment_global_scope",
            ),
        ]

    def __str__(self):
        if self.kind == self.KIND_COMMUNITY:
            return f"comment#{self.comment_id} in {self.community}"
        return f"comment#{self.comment_id} {self.kind}"


class Author(models.Model):
    name = models.CharField(max_length=200, unique=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class SubmissionAuthor(models.Model):
    submission = models.ForeignKey(
        Submission, on_delete=models.CASCADE, related_name="submission_authors"
    )
    author = models.ForeignKey(
        Author, on_delete=models.CASCADE, related_name="submission_authors"
    )
    position = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(
                fields=["submission", "position"], name="uniq_submission_author_position"
            ),
            models.UniqueConstraint(
                fields=["submission", "author"], name="uniq_submission_author"
            ),
        ]

    def __str__(self):
        return f"{self.author.name} ({self.position}) on submission#{self.submission_id}"
