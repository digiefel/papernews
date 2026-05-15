from django.contrib import admin

from .models import (
    Comment,
    CommentScope,
    CommentVote,
    Community,
    CommunityMembership,
    Profile,
    Save,
    Submission,
    SubmissionScope,
    SubmissionVote,
)


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "verified", "created")
    list_filter = ("verified",)
    search_fields = ("user__username",)


class SubmissionScopeInline(admin.TabularInline):
    model = SubmissionScope
    extra = 0
    autocomplete_fields = ("community",)


class CommentScopeInline(admin.TabularInline):
    model = CommentScope
    extra = 0
    autocomplete_fields = ("community",)


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ("title", "author", "kind", "is_removed", "created")
    list_filter = ("is_removed",)
    search_fields = ("title", "url", "author__username")
    date_hierarchy = "created"
    raw_id_fields = ("author",)
    inlines = [SubmissionScopeInline]


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ("__str__", "author", "submission", "is_removed", "created")
    list_filter = ("is_removed",)
    search_fields = ("body", "author__username")
    raw_id_fields = ("author", "submission", "parent")
    inlines = [CommentScopeInline]


@admin.register(SubmissionVote)
class SubmissionVoteAdmin(admin.ModelAdmin):
    list_display = ("submission", "user", "created")
    raw_id_fields = ("submission", "user")


@admin.register(CommentVote)
class CommentVoteAdmin(admin.ModelAdmin):
    list_display = ("comment", "user", "created")
    raw_id_fields = ("comment", "user")


@admin.register(Save)
class SaveAdmin(admin.ModelAdmin):
    list_display = ("submission", "user", "created")
    raw_id_fields = ("submission", "user")


class CommunityMembershipInline(admin.TabularInline):
    model = CommunityMembership
    extra = 0
    raw_id_fields = ("user",)


@admin.register(Community)
class CommunityAdmin(admin.ModelAdmin):
    list_display = ("slug", "name", "is_private", "created")
    list_filter = ("is_private",)
    search_fields = ("slug", "name")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [CommunityMembershipInline]


@admin.register(CommunityMembership)
class CommunityMembershipAdmin(admin.ModelAdmin):
    list_display = ("community", "user", "is_moderator", "created")
    list_filter = ("is_moderator",)
    raw_id_fields = ("user",)
    search_fields = ("user__username", "community__slug")
