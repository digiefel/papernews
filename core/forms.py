from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from .models import Comment, Submission, SubmissionScope
from .visibility import writable_communities_for


class SignupForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ("username",)


class SubmissionForm(forms.ModelForm):
    post_globally = forms.BooleanField(
        required=False,
        initial=True,
        label="Post to the global feed",
    )
    communities = forms.ModelMultipleChoiceField(
        queryset=None,
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Also post to",
    )

    class Meta:
        model = Submission
        fields = ("title", "url", "body")
        widgets = {
            "url": forms.URLInput(attrs={"placeholder": "https://..."}),
            "body": forms.Textarea(attrs={"rows": 8}),
        }
        help_texts = {"body": "Leave the URL blank for a text post."}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["communities"].queryset = writable_communities_for(user)

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("post_globally") and not cleaned.get("communities"):
            raise forms.ValidationError(
                "Pick the global feed, one or more communities, or both."
            )
        return cleaned


GLOBAL_SCOPE_VALUE = "global"


def _community_scope_value(community_id):
    return f"c{community_id}"


def _parse_scope_value(value):
    """Return (kind, community_id_or_None). Raises ValueError on bad input."""
    if value == GLOBAL_SCOPE_VALUE:
        return ("global", None)
    if value.startswith("c"):
        return ("community", int(value[1:]))
    raise ValueError(f"unrecognised scope value {value!r}")


class CommentForm(forms.ModelForm):
    scope = forms.ChoiceField(
        choices=(),
        label="Reply in",
    )

    class Meta:
        model = Comment
        fields = ("body",)
        widgets = {"body": forms.Textarea(attrs={"rows": 4})}

    def __init__(
        self,
        *args,
        submission=None,
        user=None,
        default_scope=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.submission = submission
        self.user = user

        submission_global = False
        submission_community_ids = set()
        if submission is not None:
            scopes = list(submission.scopes.all())
            submission_global = any(
                s.kind == SubmissionScope.KIND_GLOBAL for s in scopes
            )
            submission_community_ids = {
                s.community_id
                for s in scopes
                if s.kind == SubmissionScope.KIND_COMMUNITY
            }

        writable = list(writable_communities_for(user))
        # Order: submission's own communities first (sorted by slug),
        # then user's other writable communities (side channel).
        in_submission = [c for c in writable if c.id in submission_community_ids]
        side_channel = [c for c in writable if c.id not in submission_community_ids]
        in_submission.sort(key=lambda c: c.slug)
        side_channel.sort(key=lambda c: c.slug)

        choices = []
        if submission_global:
            choices.append((GLOBAL_SCOPE_VALUE, "global"))
        for c in in_submission:
            choices.append((_community_scope_value(c.id), f"c/{c.slug}"))
        for c in side_channel:
            choices.append((_community_scope_value(c.id), f"c/{c.slug} (side channel)"))

        self.fields["scope"].choices = choices
        if not choices:
            self.fields["scope"].disabled = True

        # Pick a default. Priority: caller-supplied default_scope (must be a
        # valid value), then global if available, then first option.
        valid_values = {v for v, _ in choices}
        if default_scope in valid_values:
            self.fields["scope"].initial = default_scope
        elif GLOBAL_SCOPE_VALUE in valid_values:
            self.fields["scope"].initial = GLOBAL_SCOPE_VALUE
        elif choices:
            self.fields["scope"].initial = choices[0][0]
