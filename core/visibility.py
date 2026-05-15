from django.db.models import Q

from .models import Community, CommentScope, Submission, SubmissionScope


def visible_communities_for(user):
    if user.is_authenticated:
        return Community.objects.filter(
            Q(is_private=False) | Q(memberships__user=user)
        ).distinct()
    return Community.objects.filter(is_private=False)


def writable_communities_for(user):
    """Communities the user is allowed to post into.

    Public communities are open to any logged-in user; private ones require
    membership.
    """
    if not user.is_authenticated:
        return Community.objects.none()
    return Community.objects.filter(
        Q(is_private=False) | Q(memberships__user=user)
    ).distinct()


def visible_submissions_for(user):
    community_ids = visible_communities_for(user).values("id")
    return (
        Submission.objects.visible()
        .filter(
            Q(scopes__kind=SubmissionScope.KIND_GLOBAL)
            | Q(scopes__community_id__in=community_ids)
        )
        .distinct()
    )


def visible_comments_for(user, submission):
    community_ids = visible_communities_for(user).values("id")
    return (
        submission.comments.filter(is_removed=False)
        .filter(
            Q(scopes__kind=CommentScope.KIND_GLOBAL)
            | Q(scopes__community_id__in=community_ids)
        )
        .distinct()
    )
