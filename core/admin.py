from django.contrib import admin

from .models import Comment, CommentVote, Profile, Submission, SubmissionVote


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "verified", "created")
    list_filter = ("verified",)
    search_fields = ("user__username",)


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ("title", "author", "kind", "is_removed", "created")
    list_filter = ("is_removed",)
    search_fields = ("title", "url", "author__username")
    date_hierarchy = "created"
    raw_id_fields = ("author",)


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ("__str__", "author", "submission", "is_removed", "created")
    list_filter = ("is_removed",)
    search_fields = ("body", "author__username")
    raw_id_fields = ("author", "submission", "parent")


@admin.register(SubmissionVote)
class SubmissionVoteAdmin(admin.ModelAdmin):
    list_display = ("submission", "user", "created")
    raw_id_fields = ("submission", "user")


@admin.register(CommentVote)
class CommentVoteAdmin(admin.ModelAdmin):
    list_display = ("comment", "user", "created")
    raw_id_fields = ("comment", "user")
