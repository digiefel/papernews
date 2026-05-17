from django.db.models import Q

from .models import (
    Community,
    CommentScope,
    CommunityMembership,
    Submission,
    SubmissionScope,
)


def visible_communities_for(user):
    if user.is_authenticated:
        return Community.objects.filter(
            Q(is_private=False) | Q(memberships__user=user)
        ).distinct()
    return Community.objects.filter(is_private=False)


def is_community_moderator(user, community):
    if not user.is_authenticated:
        return False
    return community.memberships.filter(
        user=user, is_moderator=True
    ).exists()


def writable_communities_for(user):
    """Communities the user is allowed to post or reply in.

    Membership is the gate for both public and private communities: anyone
    can *read* a public community, but posting/replying requires joining.
    This keeps submit and reply scope pickers focused on the user's chosen
    spaces instead of every public community on the site.
    """
    if not user.is_authenticated:
        return Community.objects.none()
    return Community.objects.filter(memberships__user=user).distinct()


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


def annotate_visible_community_scopes(submissions, user):
    """Set .visible_community_scopes on each submission, filtered to the
    communities the viewer can see. Uses the prefetched scopes; the only
    extra query is one tiny lookup of the user's own memberships.

    Important: never use the raw `submission.scopes.all()` from templates to
    render community labels — it leaks the existence of private communities
    a global submission also happens to be in.
    """
    member_ids = set()
    if user.is_authenticated:
        member_ids = set(
            CommunityMembership.objects.filter(user=user).values_list(
                "community_id", flat=True
            )
        )
    for s in submissions:
        s.visible_community_scopes = [
            scope
            for scope in s.scopes.all()
            if scope.community_id
            and (
                not scope.community.is_private
                or scope.community_id in member_ids
            )
        ]


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
