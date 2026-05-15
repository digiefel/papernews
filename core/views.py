from collections import defaultdict

from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Prefetch
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import (
    GLOBAL_SCOPE_VALUE,
    CommentForm,
    SignupForm,
    SubmissionForm,
    _community_scope_value,
    _parse_scope_value,
)
from .citations import extract_metadata, normalize_doi
from .models import (
    Author,
    Comment,
    CommentScope,
    CommentVote,
    Community,
    Save,
    Submission,
    SubmissionAuthor,
    SubmissionScope,
    SubmissionVote,
)
from .ranking import hot_score
from .visibility import (
    visible_comments_for,
    visible_communities_for,
    visible_submissions_for,
)

User = get_user_model()

PAGE_SIZE = 30
CANDIDATE_POOL = 200
MAX_INDENT = 6


def _safe_next(request, fallback="home"):
    nxt = request.POST.get("next") or request.GET.get("next")
    if nxt and url_has_allowed_host_and_scheme(
        nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return nxt
    return reverse(fallback)


def _mark_saved(submissions, user):
    """Set .is_saved on each submission for `user`, in one query (no N+1)."""
    if not user.is_authenticated:
        for s in submissions:
            s.is_saved = False
        return
    saved_ids = set(
        Save.objects.filter(user=user, submission__in=submissions).values_list(
            "submission_id", flat=True
        )
    )
    for s in submissions:
        s.is_saved = s.id in saved_ids


def _scopes_prefetch():
    return Prefetch(
        "scopes",
        queryset=SubmissionScope.objects.select_related("community"),
    )


def _authors_prefetch():
    return Prefetch(
        "submission_authors",
        queryset=SubmissionAuthor.objects.select_related("author"),
    )


def _attach_scope(comment):
    """Set comment.scope_value (string for form input) and comment.scope_community."""
    first_scope = next(iter(comment.scopes.all()), None)
    if first_scope is None or first_scope.kind == CommentScope.KIND_GLOBAL:
        comment.scope_value = GLOBAL_SCOPE_VALUE
        comment.scope_community = None
    else:
        comment.scope_value = _community_scope_value(first_scope.community_id)
        comment.scope_community = first_scope.community


def _default_scope_from_provenance(request, submission):
    """If ?in=<slug> matches a community the user can write in, use it; else None."""
    slug = request.GET.get("in", "").strip()
    if not slug:
        return None
    community = (
        visible_communities_for(request.user).filter(slug=slug).first()
    )
    if community is None:
        return None
    return _community_scope_value(community.id)



def front_page(request):
    now = timezone.now()
    candidates = list(
        visible_submissions_for(request.user)
        .annotate(vote_count=Count("votes", distinct=True))
        .select_related("author", "author__profile")
        .prefetch_related(_scopes_prefetch(), _authors_prefetch())
        .order_by("-created")[:CANDIDATE_POOL]
    )
    candidates.sort(
        key=lambda s: hot_score(s.vote_count, s.created, now), reverse=True
    )
    page = Paginator(candidates, PAGE_SIZE).get_page(request.GET.get("page"))
    _mark_saved(page.object_list, request.user)
    return render(request, "core/listing.html", {"page_obj": page})


def new_page(request):
    qs = (
        visible_submissions_for(request.user)
        .annotate(vote_count=Count("votes", distinct=True))
        .select_related("author", "author__profile")
        .prefetch_related(_scopes_prefetch(), _authors_prefetch())
        .order_by("-created")
    )
    page = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page"))
    _mark_saved(page.object_list, request.user)
    return render(
        request, "core/listing.html", {"page_obj": page, "page_title": "New"}
    )


def submission_detail(request, pk):
    submission = get_object_or_404(
        visible_submissions_for(request.user)
        .annotate(vote_count=Count("votes", distinct=True))
        .select_related("author", "author__profile")
        .prefetch_related(_scopes_prefetch(), _authors_prefetch()),
        pk=pk,
    )

    # Provenance: if the user reached this page from a community feed, the link
    # carries ?in=<slug>. Use it to seed the comment scope default.
    default_scope = _default_scope_from_provenance(request, submission)

    if request.method == "POST":
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        form = CommentForm(
            request.POST,
            submission=submission,
            user=request.user,
            default_scope=default_scope,
        )
        if form.is_valid():
            with transaction.atomic():
                comment = form.save(commit=False)
                comment.author = request.user
                comment.submission = submission
                comment.save()
                kind, community_id = _parse_scope_value(form.cleaned_data["scope"])
                if kind == "global":
                    CommentScope.objects.create(
                        comment=comment, kind=CommentScope.KIND_GLOBAL
                    )
                else:
                    CommentScope.objects.create(
                        comment=comment,
                        kind=CommentScope.KIND_COMMUNITY,
                        community_id=community_id,
                    )
            return redirect(comment.get_absolute_url())
    else:
        form = CommentForm(
            submission=submission,
            user=request.user,
            default_scope=default_scope,
        )

    comments = list(
        visible_comments_for(request.user, submission)
        .annotate(vote_count=Count("votes", distinct=True))
        .select_related("author", "author__profile")
        .prefetch_related(
            Prefetch(
                "scopes",
                queryset=CommentScope.objects.select_related("community"),
            )
        )
    )
    by_parent = defaultdict(list)
    for c in comments:
        by_parent[c.parent_id].append(c)
    for c in comments:
        c.children_list = by_parent[c.id]
        _attach_scope(c)
    roots = by_parent[None]

    stack = [(c, 0) for c in roots]
    while stack:
        comment, depth = stack.pop()
        comment.indent = min(depth, MAX_INDENT)
        stack += [(child, depth + 1) for child in comment.children_list]

    return render(
        request,
        "core/submission_detail.html",
        {"submission": submission, "roots": roots, "form": form},
    )


@login_required
def reply(request, sub_pk, comment_pk):
    submission = get_object_or_404(
        visible_submissions_for(request.user)
        .select_related("author", "author__profile")
        .prefetch_related(_scopes_prefetch(), _authors_prefetch()),
        pk=sub_pk,
    )
    parent = get_object_or_404(
        visible_comments_for(request.user, submission)
        .annotate(vote_count=Count("votes", distinct=True))
        .select_related("author", "author__profile")
        .prefetch_related(
            Prefetch(
                "scopes",
                queryset=CommentScope.objects.select_related("community"),
            )
        ),
        pk=comment_pk,
    )
    _attach_scope(parent)

    # Siblings of the parent: comments visible to this user at the same depth
    # under the same grandparent (or top-level if the parent itself is root).
    sibling_qs = (
        visible_comments_for(request.user, submission)
        .filter(parent_id=parent.parent_id)
        .exclude(pk=parent.pk)
        .annotate(vote_count=Count("votes", distinct=True))
        .select_related("author", "author__profile")
        .prefetch_related(
            Prefetch(
                "scopes",
                queryset=CommentScope.objects.select_related("community"),
            )
        )
    )
    siblings = list(sibling_qs)
    for s in siblings:
        s.indent = 0
        s.children_list = []
        _attach_scope(s)
    parent.indent = 0
    parent.children_list = []

    if request.method == "POST":
        # Reuse the same scope rules as inline replies: inherited from parent,
        # passed as a hidden field. Validate via the same CommentForm.
        form = CommentForm(
            request.POST,
            submission=submission,
            user=request.user,
            default_scope=parent.scope_value,
        )
        if form.is_valid():
            with transaction.atomic():
                comment = form.save(commit=False)
                comment.author = request.user
                comment.submission = submission
                comment.parent = parent
                comment.save()
                kind, community_id = _parse_scope_value(form.cleaned_data["scope"])
                if kind == "global":
                    CommentScope.objects.create(
                        comment=comment, kind=CommentScope.KIND_GLOBAL
                    )
                else:
                    CommentScope.objects.create(
                        comment=comment,
                        kind=CommentScope.KIND_COMMUNITY,
                        community_id=community_id,
                    )
            return redirect(comment.get_absolute_url())
    else:
        form = CommentForm(
            submission=submission,
            user=request.user,
            default_scope=parent.scope_value,
        )

    return render(
        request,
        "core/reply.html",
        {
            "submission": submission,
            "parent": parent,
            "siblings": siblings,
            "form": form,
        },
    )


@login_required
def submit(request):
    if request.method == "POST":
        form = SubmissionForm(request.POST, user=request.user)
        if form.is_valid():
            with transaction.atomic():
                submission = form.save(commit=False)
                submission.author = request.user
                if submission.url:
                    doi = normalize_doi(submission.url)
                    if doi:
                        submission.doi = doi
                submission.save()
                if form.cleaned_data.get("post_globally"):
                    SubmissionScope.objects.create(
                        submission=submission, kind=SubmissionScope.KIND_GLOBAL
                    )
                for community in form.cleaned_data.get("communities", []):
                    SubmissionScope.objects.create(
                        submission=submission,
                        kind=SubmissionScope.KIND_COMMUNITY,
                        community=community,
                    )
                for position, name in enumerate(form.split_authors()):
                    author, _ = Author.objects.get_or_create(name=name)
                    SubmissionAuthor.objects.create(
                        submission=submission, author=author, position=position
                    )
            return redirect(submission.get_absolute_url())
    else:
        form = SubmissionForm(user=request.user)
    return render(request, "core/submit.html", {"form": form})


MAX_BIBTEX_UPLOAD_BYTES = 200_000  # BibTeX is small text; 200 KB is generous.


@require_POST
def api_extract_metadata(request):
    # Authentication: gate the endpoint so anonymous callers can't use the
    # server as a doi.org fetch proxy. Return JSON (not Django's HTML login
    # redirect) so the AJAX caller can handle the failure cleanly.
    if not request.user.is_authenticated:
        return JsonResponse({"error": "authentication required"}, status=401)

    uploaded = request.FILES.get("file")
    if uploaded is not None:
        if uploaded.size > MAX_BIBTEX_UPLOAD_BYTES:
            return JsonResponse({"error": "file too large"}, status=413)
        source_text = uploaded.read().decode("utf-8", errors="replace")
    else:
        source_text = request.POST.get("text", "").strip()

    metadata, kind = extract_metadata(source_text)
    if not metadata:
        return JsonResponse({"error": "unrecognized"}, status=400)

    return JsonResponse({"metadata": metadata, "kind": kind})


def communities_index(request):
    communities = (
        visible_communities_for(request.user)
        .annotate(submission_count=Count("submissionscope__submission", distinct=True))
        .order_by("slug")
    )
    return render(
        request,
        "core/communities_list.html",
        {"communities": communities},
    )


def community_detail(request, slug):
    community = visible_communities_for(request.user).filter(slug=slug).first()
    if community is None:
        raise Http404
    qs = (
        visible_submissions_for(request.user)
        .filter(scopes__kind=SubmissionScope.KIND_COMMUNITY, scopes__community=community)
        .annotate(vote_count=Count("votes", distinct=True))
        .select_related("author", "author__profile")
        .prefetch_related(_scopes_prefetch(), _authors_prefetch())
        .order_by("-created")
        .distinct()
    )
    page = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(
        request,
        "core/community_detail.html",
        {"community": community, "page_obj": page},
    )


@require_POST
@login_required
def vote_submission(request, pk):
    submission = get_object_or_404(
        visible_submissions_for(request.user), pk=pk
    )
    SubmissionVote.objects.get_or_create(submission=submission, user=request.user)
    return redirect(_safe_next(request))


@require_POST
@login_required
def vote_comment(request, pk):
    comment = get_object_or_404(Comment, pk=pk, is_removed=False)
    # Guard: don't allow voting on a comment you can't see.
    if not visible_comments_for(request.user, comment.submission).filter(pk=pk).exists():
        raise Http404
    CommentVote.objects.get_or_create(comment=comment, user=request.user)
    return redirect(_safe_next(request))


@require_POST
@login_required
def toggle_save(request, pk):
    submission = get_object_or_404(Submission.objects.visible(), pk=pk)
    save, created = Save.objects.get_or_create(
        submission=submission, user=request.user
    )
    if not created:
        save.delete()
    return redirect(_safe_next(request))


@login_required
def saved_page(request):
    saves = (
        Save.objects.filter(user=request.user, submission__is_removed=False)
        .select_related(
            "submission", "submission__author", "submission__author__profile"
        )
        .prefetch_related(
            Prefetch(
                "submission__submission_authors",
                queryset=SubmissionAuthor.objects.select_related("author"),
            )
        )
        .annotate(vote_count=Count("submission__votes"))
        .order_by("-created")
    )
    page = Paginator(saves, PAGE_SIZE).get_page(request.GET.get("page"))
    submissions = []
    for save in page.object_list:
        submission = save.submission
        submission.vote_count = save.vote_count
        submission.is_saved = True
        submissions.append(submission)
    page.object_list = submissions
    return render(
        request, "core/listing.html", {"page_obj": page, "page_title": "Saved"}
    )


def user_page(request, username):
    profile_user = get_object_or_404(User, username=username)

    submissions = list(
        Submission.objects.visible()
        .filter(author=profile_user)
        .annotate(vote_count=Count("votes"))
        .select_related("author", "author__profile")
        .prefetch_related(_authors_prefetch())
    )
    for submission in submissions:
        submission.item_type = "submission"

    comments = list(
        Comment.objects.filter(
            author=profile_user, is_removed=False, submission__is_removed=False
        )
        .annotate(vote_count=Count("votes"))
        .select_related("author", "author__profile", "submission")
    )
    for comment in comments:
        comment.item_type = "comment"

    feed = sorted(submissions + comments, key=lambda x: x.created, reverse=True)
    page = Paginator(feed, PAGE_SIZE).get_page(request.GET.get("page"))
    _mark_saved(
        [i for i in page.object_list if i.item_type == "submission"], request.user
    )
    return render(
        request,
        "core/user_page.html",
        {"profile_user": profile_user, "page_obj": page},
    )


def signup(request):
    if request.user.is_authenticated:
        return redirect("home")
    if request.method == "POST":
        form = SignupForm(request.POST)
        if form.is_valid():
            login(request, form.save())
            return redirect("home")
    else:
        form = SignupForm()
    return render(request, "core/signup.html", {"form": form})
