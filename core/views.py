from collections import defaultdict

from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.core.paginator import Paginator
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import CommentForm, SignupForm, SubmissionForm
from .models import Comment, CommentVote, Save, Submission, SubmissionVote
from .ranking import hot_score

User = get_user_model()

PAGE_SIZE = 30
CANDIDATE_POOL = 200
MAX_INDENT = 6


def _safe_next(request, fallback="home"):
    """Resolve a redirect target from ?next=, rejecting off-site URLs (open-redirect guard)."""
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


def front_page(request):
    now = timezone.now()
    candidates = list(
        Submission.objects.visible()
        .annotate(vote_count=Count("votes"))
        .select_related("author", "author__profile")
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
        Submission.objects.visible()
        .annotate(vote_count=Count("votes"))
        .select_related("author", "author__profile")
        .order_by("-created")
    )
    page = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page"))
    _mark_saved(page.object_list, request.user)
    return render(request, "core/listing.html", {"page_obj": page, "page_title": "New"})


def submission_detail(request, pk):
    submission = get_object_or_404(
        Submission.objects.visible()
        .annotate(vote_count=Count("votes"))
        .select_related("author", "author__profile"),
        pk=pk,
    )

    if request.method == "POST":
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        form = CommentForm(request.POST)
        if form.is_valid():
            comment = form.save(commit=False)
            comment.author = request.user
            comment.submission = submission
            parent_id = request.POST.get("parent_id")
            if parent_id:
                comment.parent = get_object_or_404(
                    Comment, pk=parent_id, submission=submission
                )
            comment.save()
            return redirect(comment.get_absolute_url())
    else:
        form = CommentForm()

    # Fetch the whole thread in one query and assemble the tree in memory, so the
    # recursive template render touches no database.
    comments = list(
        submission.comments.filter(is_removed=False)
        .annotate(vote_count=Count("votes"))
        .select_related("author", "author__profile")
    )
    by_parent = defaultdict(list)
    for c in comments:
        by_parent[c.parent_id].append(c)
    for c in comments:
        c.children_list = by_parent[c.id]
    roots = by_parent[None]

    # Precompute indentation depth; capped so deep threads don't run off the page.
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
def submit(request):
    if request.method == "POST":
        form = SubmissionForm(request.POST)
        if form.is_valid():
            submission = form.save(commit=False)
            submission.author = request.user
            submission.save()
            return redirect(submission.get_absolute_url())
    else:
        form = SubmissionForm()
    return render(request, "core/submit.html", {"form": form})


@require_POST
@login_required
def vote_submission(request, pk):
    submission = get_object_or_404(Submission.objects.visible(), pk=pk)
    SubmissionVote.objects.get_or_create(submission=submission, user=request.user)
    return redirect(_safe_next(request))


@require_POST
@login_required
def vote_comment(request, pk):
    comment = get_object_or_404(Comment, pk=pk, is_removed=False)
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
