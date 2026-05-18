import re

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator

from .citations import normalize_doi
from .models import (
    Comment,
    Community,
    CommunityMembership,
    Submission,
    SubmissionScope,
)
from .sanitize import COMMENT_BODY
from .text import fallback_body_html
from .visibility import writable_communities_for


def _resolve_body_html(cleaned_body: str, raw_body_html: str | None) -> str:
    """Compute the stored ``body_html`` for a comment- or submission-shaped form.

    Centralised so both forms share the policy: trust nothing from the client,
    sanitize what they send, and fall back to a text-only render when the
    client didn't supply HTML at all (typically: JavaScript disabled).
    """
    if raw_body_html:
        return COMMENT_BODY.clean(raw_body_html)
    return fallback_body_html(cleaned_body or "")


COLOR_INPUT_ATTRS = {"type": "color"}
DESCRIPTION_WIDGET = forms.Textarea(attrs={"rows": 3})


def _user_is_admin(user):
    return bool(user and user.is_authenticated and user.is_staff)


class CommunityCreateForm(forms.ModelForm):
    class Meta:
        model = Community
        fields = ("slug", "name", "description", "color", "is_private")
        widgets = {
            "description": DESCRIPTION_WIDGET,
            "color": forms.TextInput(attrs=COLOR_INPUT_ATTRS),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        # Only global admins can create public communities. For everyone else
        # we drop the is_private field entirely and force-private on save.
        if not _user_is_admin(user):
            del self.fields["is_private"]

    def save(self, commit=True):
        instance = super().save(commit=False)
        if "is_private" not in self.fields:
            instance.is_private = True
        if commit:
            instance.save()
        return instance


class AddMemberForm(forms.Form):
    username = forms.CharField(max_length=150, label="Username")
    is_moderator = forms.BooleanField(required=False, label="as moderator")

    def __init__(self, *args, community=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.community = community

    def clean_username(self):
        User = get_user_model()
        username = self.cleaned_data["username"].strip()
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            raise forms.ValidationError(f"No user named '{username}'.")
        if self.community and CommunityMembership.objects.filter(
            community=self.community, user=user
        ).exists():
            raise forms.ValidationError(
                f"{username} is already a member of this community."
            )
        # Stash the resolved user so the view doesn't need to look it up again.
        self.cleaned_data["user"] = user
        return username


class CommunityEditForm(forms.ModelForm):
    # Slug is omitted: it's in URLs and shouldn't change after creation.
    class Meta:
        model = Community
        fields = ("name", "description", "color", "is_private")
        widgets = {
            "description": DESCRIPTION_WIDGET,
            "color": forms.TextInput(attrs=COLOR_INPUT_ATTRS),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        # Closing the loophole: a non-admin moderator can't flip privacy
        # either, otherwise the create rule would be bypassable.
        if not _user_is_admin(user):
            del self.fields["is_private"]


class SignupForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ("username",)


class SubmissionForm(forms.ModelForm):
    # Override the model's URLField so we can accept a bare DOI shorthand
    # (e.g. "10.1038/Nature12373") alongside a normal URL. Validation lives in
    # clean_url() below; the model's URLField never sees the raw input.
    url = forms.CharField(
        required=False,
        widget=forms.URLInput(
            attrs={"placeholder": "https://… or 10.xxxx/yyy"}
        ),
        label="URL",
    )
    post_globally = forms.BooleanField(
        required=False,
        initial=True,
        label="global",
    )
    communities = forms.ModelMultipleChoiceField(
        queryset=None,
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Also post to",
    )
    # Rendered HTML for `body`, populated client-side by static/math-compose.js
    # right before submit. Treated as untrusted: sanitized via COMMENT_BODY
    # before storage. If absent (JS disabled), we render a text-only fallback
    # server-side in clean().
    body_html = forms.CharField(required=False, widget=forms.HiddenInput)
    bibtex_text = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={"rows": 4, "placeholder": "@article{...}"}
        ),
        label="BibTeX",
    )
    bibtex_file = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(attrs={"accept": ".bib,text/plain,text/x-bibtex"}),
        label="or drop a .bib file",
    )
    authors_text = forms.CharField(
        required=False,
        label="Authors",
        help_text="Separate with ';' or ' and '.",
    )

    class Meta:
        model = Submission
        fields = ("title", "url", "body", "year", "source")
        widgets = {
            "body": forms.Textarea(
                attrs={
                    "rows": 8, "data-math-compose": "body_html",
                    "placeholder": "Leave the URL blank and type something here for a text post."
                }
            ),
            "year": forms.NumberInput(attrs={"placeholder": "2023"}),
            "source": forms.TextInput(attrs={"placeholder": "journal, conference, …"}),
        }
        help_texts = {
            # "body": "Leave the URL blank for a text post.",
            "body": "",
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["communities"].queryset = writable_communities_for(user)

    def community_choices(self):
        """List of (community, is_selected) for manual checkbox rendering."""
        raw = self["communities"].value() or []
        selected = {str(v) for v in raw}
        return [
            (c, str(c.pk) in selected)
            for c in self.fields["communities"].queryset
        ]

    def clean_url(self):
        raw = (self.cleaned_data.get("url") or "").strip()
        if not raw:
            return ""
        # Bare DOI shorthand wins: turn "10.xxxx/yyy" (and the doi:/doi.org/
        # variants) into a canonical doi.org URL.
        norm_doi = normalize_doi(raw)
        if norm_doi:
            return f"https://doi.org/{norm_doi}"
        # Otherwise, validate as a regular URL.
        try:
            URLValidator()(raw)
        except ValidationError:
            raise ValidationError("Enter a valid URL or DOI.")
        return raw

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("post_globally") and not cleaned.get("communities"):
            raise forms.ValidationError(
                "Pick the global feed, one or more communities, or both."
            )
        return cleaned

    def _post_clean(self):
        # super() copies cleaned_data → self.instance. The DOI field isn't a
        # form input (URL is canonical), so we derive it here from the now-
        # assigned self.instance.url. Doing it in the form keeps every "URL
        # changed → DOI updated" path consistent without the view caring.
        super()._post_clean()
        self.instance.doi = normalize_doi(self.instance.url) or ""
        self.instance.body_html = _resolve_body_html(
            self.instance.body, self.cleaned_data.get("body_html")
        )

    def split_authors(self):
        """Return ordered, deduped list of non-empty author names from authors_text."""
        raw = (self.cleaned_data.get("authors_text") or "").strip()
        if not raw:
            return []
        parts = re.split(r"\s*;\s*|\s+and\s+", raw, flags=re.IGNORECASE)
        seen = set()
        result = []
        for p in parts:
            name = p.strip()
            if name and name not in seen:
                seen.add(name)
                result.append(name)
        return result


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
    # See SubmissionForm.body_html for the contract.
    body_html = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = Comment
        fields = ("body",)
        widgets = {
            "body": forms.Textarea(
                attrs={"rows": 4, "data-math-compose": "body_html"}
            ),
        }

    def _post_clean(self):
        super()._post_clean()
        self.instance.body_html = _resolve_body_html(
            self.instance.body, self.cleaned_data.get("body_html")
        )

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

        # Build two parallel structures: `choices` for Django's ChoiceField
        # validation, and `scope_options` (with color) for manual template
        # rendering so per-option color can be inlined on <option>.
        choices = []
        self.scope_options = []
        if submission_global:
            choices.append((GLOBAL_SCOPE_VALUE, "global"))
            self.scope_options.append(
                {"value": GLOBAL_SCOPE_VALUE, "label": "global", "color": None}
            )
        for c in in_submission + side_channel:
            value = _community_scope_value(c.id)
            label = f"c/{c.slug}"
            choices.append((value, label))
            self.scope_options.append(
                {"value": value, "label": label, "color": c.color}
            )

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
