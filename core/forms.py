from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from .models import Comment, Submission


class SignupForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ("username",)


class SubmissionForm(forms.ModelForm):
    class Meta:
        model = Submission
        fields = ("title", "url", "body")
        widgets = {
            "url": forms.URLInput(attrs={"placeholder": "https://..."}),
            "body": forms.Textarea(attrs={"rows": 8}),
        }
        help_texts = {"body": "Leave the URL blank for a text post."}


class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ("body",)
        widgets = {"body": forms.Textarea(attrs={"rows": 4})}
