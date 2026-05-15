from datetime import timedelta

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

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
from .ranking import hot_score


def make_submission(*, communities=(), global_=True, **kwargs):
    """Create a submission with the chosen scopes. Defaults to global-only."""
    s = Submission.objects.create(**kwargs)
    if global_:
        SubmissionScope.objects.create(submission=s, kind=SubmissionScope.KIND_GLOBAL)
    for c in communities:
        SubmissionScope.objects.create(
            submission=s, kind=SubmissionScope.KIND_COMMUNITY, community=c
        )
    return s


def make_comment(submission, *, communities=(), global_=True, **kwargs):
    c = Comment.objects.create(submission=submission, **kwargs)
    if global_:
        CommentScope.objects.create(comment=c, kind=CommentScope.KIND_GLOBAL)
    for community in communities:
        CommentScope.objects.create(
            comment=c, kind=CommentScope.KIND_COMMUNITY, community=community
        )
    return c


class ModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", password="pw-test-12345")

    def test_profile_auto_created(self):
        self.assertTrue(Profile.objects.filter(user=self.user).exists())

    def test_submission_kind_and_domain(self):
        link = Submission(
            title="t", url="https://www.example.com/x", author=self.user
        )
        text = Submission(title="t", body="hello", author=self.user)
        self.assertEqual(link.kind, "link")
        self.assertEqual(link.domain, "example.com")
        self.assertEqual(text.kind, "text")
        self.assertEqual(text.domain, "")

    def test_submission_clean_rejects_both_and_neither(self):
        with self.assertRaises(ValidationError):
            Submission(
                title="t", url="https://x.com", body="y", author=self.user
            ).clean()
        with self.assertRaises(ValidationError):
            Submission(title="t", author=self.user).clean()

    def test_comment_clean_rejects_cross_submission_parent(self):
        s1 = make_submission(title="a", body="x", author=self.user)
        s2 = make_submission(title="b", body="y", author=self.user)
        parent = Comment.objects.create(submission=s1, author=self.user, body="p")
        with self.assertRaises(ValidationError):
            Comment(submission=s2, parent=parent, author=self.user, body="c").clean()


class RankingTests(TestCase):
    def test_more_votes_ranks_higher(self):
        now = timezone.now()
        self.assertGreater(hot_score(10, now, now), hot_score(1, now, now))

    def test_older_ranks_lower_for_equal_votes(self):
        now = timezone.now()
        old = now - timedelta(hours=48)
        self.assertGreater(hot_score(5, now, now), hot_score(5, old, now))


class ViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("bob", password="pw-test-12345")

    def test_signup_creates_and_logs_in(self):
        resp = self.client.post(
            "/signup/",
            {
                "username": "carol",
                "password1": "s3cret-pw-9988",
                "password2": "s3cret-pw-9988",
            },
        )
        self.assertRedirects(resp, "/")
        carol = User.objects.get(username="carol")
        self.assertTrue(Profile.objects.filter(user=carol).exists())
        self.assertEqual(self.client.session["_auth_user_id"], str(carol.pk))

    def test_submit_link_and_text(self):
        self.client.force_login(self.user)
        self.client.post(
            "/submit/",
            {
                "title": "a link",
                "url": "https://example.com",
                "body": "",
                "post_globally": "on",
            },
        )
        self.client.post(
            "/submit/",
            {
                "title": "a text",
                "url": "",
                "body": "some words",
                "post_globally": "on",
            },
        )
        self.assertEqual(Submission.objects.count(), 2)
        link = Submission.objects.get(title="a link")
        text = Submission.objects.get(title="a text")
        self.assertEqual(link.kind, "link")
        self.assertEqual(text.kind, "text")
        # Each got a global scope row
        self.assertTrue(link.scopes.filter(kind="global").exists())
        self.assertTrue(text.scopes.filter(kind="global").exists())

    def test_submit_invalid_both_fields(self):
        self.client.force_login(self.user)
        resp = self.client.post(
            "/submit/",
            {
                "title": "x",
                "url": "https://example.com",
                "body": "text too",
                "post_globally": "on",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Submission.objects.count(), 0)

    def test_submit_requires_at_least_one_scope(self):
        self.client.force_login(self.user)
        resp = self.client.post(
            "/submit/",
            {"title": "x", "url": "", "body": "hi"},  # no post_globally, no community
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Submission.objects.count(), 0)

    def test_comment_requires_login_and_nests(self):
        s = make_submission(title="a", body="x", author=self.user)
        resp = self.client.post(s.get_absolute_url(), {"body": "anon comment"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Comment.objects.count(), 0)

        self.client.force_login(self.user)
        self.client.post(
            s.get_absolute_url(), {"body": "top level", "scope": "global"}
        )
        top = Comment.objects.get()
        self.client.post(
            f"/item/{s.pk}/reply/{top.pk}/",
            {"body": "a reply", "scope": "global"},
        )
        reply = Comment.objects.get(body="a reply")
        self.assertEqual(reply.parent_id, top.pk)

    def test_voting_idempotent(self):
        s = make_submission(title="a", body="x", author=self.user)
        self.client.force_login(self.user)
        url = f"/vote/submission/{s.pk}/"
        self.client.post(url)
        self.client.post(url)
        self.assertEqual(SubmissionVote.objects.filter(submission=s).count(), 1)

    def test_new_page_orders_by_created(self):
        old = make_submission(title="old", body="x", author=self.user)
        new = make_submission(title="new", body="x", author=self.user)
        resp = self.client.get("/new/")
        items = list(resp.context["page_obj"])
        self.assertEqual([items[0].pk, items[1].pk], [new.pk, old.pk])

    def test_removed_submission_absent_from_listings(self):
        make_submission(
            title="hidden", body="x", author=self.user, is_removed=True
        )
        resp = self.client.get("/new/")
        self.assertEqual(len(resp.context["page_obj"]), 0)


class SaveTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("bob", password="pw-test-12345")
        self.sub = Submission.objects.create(
            title="a", body="x", author=self.user
        )

    def test_toggle_save_creates_then_deletes(self):
        self.client.force_login(self.user)
        url = f"/save/submission/{self.sub.pk}/"
        self.client.post(url)
        self.assertEqual(Save.objects.count(), 1)
        self.client.post(url)
        self.assertEqual(Save.objects.count(), 0)

    def test_saved_page_lists_saved_recent_first_excludes_removed(self):
        kept = Submission.objects.create(title="kept", body="x", author=self.user)
        gone = Submission.objects.create(
            title="gone", body="x", author=self.user, is_removed=True
        )
        now = timezone.now()
        # auto_now_add gives near-identical timestamps; pin them to assert order.
        for sub, ago in [(self.sub, 30), (kept, 10), (gone, 0)]:
            Save.objects.filter(
                pk=Save.objects.create(submission=sub, user=self.user).pk
            ).update(created=now - timedelta(minutes=ago))

        self.client.force_login(self.user)
        resp = self.client.get("/saved/")
        items = list(resp.context["page_obj"])
        self.assertEqual([i.pk for i in items], [kept.pk, self.sub.pk])


class UserPageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", password="pw-test-12345")
        self.other = User.objects.create_user("bob", password="pw-test-12345")

    def test_user_page_interleaves_and_orders(self):
        s1 = Submission.objects.create(title="first", body="x", author=self.user)
        host = Submission.objects.create(title="host", body="x", author=self.other)
        c1 = Comment.objects.create(submission=host, author=self.user, body="c1")
        s2 = Submission.objects.create(title="second", body="y", author=self.user)

        resp = self.client.get(f"/u/{self.user.username}/")
        items = list(resp.context["page_obj"])
        self.assertEqual([i.pk for i in items], [s2.pk, c1.pk, s1.pk])
        self.assertEqual(
            [i.item_type for i in items], ["submission", "comment", "submission"]
        )

    def test_user_page_excludes_removed(self):
        Submission.objects.create(
            title="hidden", body="x", author=self.user, is_removed=True
        )
        host_ok = Submission.objects.create(title="ok host", body="x", author=self.other)
        host_gone = Submission.objects.create(
            title="gone host", body="x", author=self.other, is_removed=True
        )
        Comment.objects.create(
            submission=host_ok, author=self.user, body="removed", is_removed=True
        )
        Comment.objects.create(
            submission=host_gone, author=self.user, body="orphan"
        )

        resp = self.client.get(f"/u/{self.user.username}/")
        self.assertEqual(len(resp.context["page_obj"]), 0)


class VisibilityTests(TestCase):
    def setUp(self):
        self.author = User.objects.create_user("author", password="pw-test-12345")
        self.member = User.objects.create_user("member", password="pw-test-12345")
        self.outsider = User.objects.create_user("outsider", password="pw-test-12345")

        self.public_community = Community.objects.create(
            slug="ml-systems", name="ML Systems"
        )
        self.private_community = Community.objects.create(
            slug="my-lab", name="My Lab", is_private=True
        )
        CommunityMembership.objects.create(
            community=self.private_community, user=self.member
        )
        CommunityMembership.objects.create(
            community=self.private_community, user=self.author
        )

    def test_home_shows_global_and_public_community_posts_to_anon(self):
        # Anon "allowed to see" = global + public community posts.
        global_s = make_submission(title="g", body="x", author=self.author)
        public_only = make_submission(
            title="public-only",
            body="x",
            author=self.author,
            global_=False,
            communities=[self.public_community],
        )
        private_only = make_submission(
            title="private-only",
            body="x",
            author=self.author,
            global_=False,
            communities=[self.private_community],
        )
        resp = self.client.get("/")
        titles = [s.title for s in resp.context["page_obj"]]
        self.assertIn(global_s.title, titles)
        self.assertIn(public_only.title, titles)
        self.assertNotIn(private_only.title, titles)

    def test_anon_sees_public_community_page(self):
        make_submission(
            title="hi-ml",
            body="x",
            author=self.author,
            global_=False,
            communities=[self.public_community],
        )
        resp = self.client.get("/c/ml-systems/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "hi-ml")

    def test_anon_404_on_private_community(self):
        resp = self.client.get("/c/my-lab/")
        self.assertEqual(resp.status_code, 404)

    def test_outsider_404_on_private_community(self):
        self.client.force_login(self.outsider)
        resp = self.client.get("/c/my-lab/")
        self.assertEqual(resp.status_code, 404)

    def test_outsider_does_not_see_private_submissions_on_home(self):
        secret = make_submission(
            title="secret-lab-note",
            body="x",
            author=self.author,
            global_=False,
            communities=[self.private_community],
        )
        # outsider sees nothing
        self.client.force_login(self.outsider)
        resp = self.client.get("/")
        titles = [s.title for s in resp.context["page_obj"]]
        self.assertNotIn(secret.title, titles)
        # member sees it
        self.client.force_login(self.member)
        resp = self.client.get("/")
        titles = [s.title for s in resp.context["page_obj"]]
        self.assertIn(secret.title, titles)

    def test_outsider_404s_on_private_submission_detail(self):
        secret = make_submission(
            title="hidden",
            body="x",
            author=self.author,
            global_=False,
            communities=[self.private_community],
        )
        self.client.force_login(self.outsider)
        resp = self.client.get(secret.get_absolute_url())
        self.assertEqual(resp.status_code, 404)

    def test_private_scoped_comment_hidden_from_non_members(self):
        global_s = make_submission(title="global-post", body="x", author=self.author)
        public_comment = make_comment(
            global_s, author=self.author, body="public hi"
        )
        private_comment = make_comment(
            global_s,
            author=self.author,
            body="lab-only chatter",
            global_=False,
            communities=[self.private_community],
        )
        # outsider only sees the public comment
        self.client.force_login(self.outsider)
        resp = self.client.get(global_s.get_absolute_url())
        self.assertContains(resp, public_comment.body)
        self.assertNotContains(resp, private_comment.body)
        # member sees both
        self.client.force_login(self.member)
        resp = self.client.get(global_s.get_absolute_url())
        self.assertContains(resp, public_comment.body)
        self.assertContains(resp, private_comment.body)

    def test_communities_index_excludes_private_for_outsiders(self):
        self.client.force_login(self.outsider)
        resp = self.client.get("/communities/")
        self.assertContains(resp, "ml-systems")
        self.assertNotContains(resp, "my-lab")

    def test_communities_index_includes_private_for_members(self):
        self.client.force_login(self.member)
        resp = self.client.get("/communities/")
        self.assertContains(resp, "my-lab")

    def test_comment_scope_defaults_to_provenance_community(self):
        # Submission lives in c/ml-systems and is global.
        s = make_submission(
            title="paper",
            body="x",
            author=self.author,
            communities=[self.public_community],
        )
        # Member visits via ?in=ml-systems → dropdown default = c/ml-systems.
        self.client.force_login(self.member)
        resp = self.client.get(f"{s.get_absolute_url()}?in=ml-systems")
        form = resp.context["form"]
        self.assertEqual(form["scope"].value(), f"c{self.public_community.id}")
        # Same submission, no ?in= → defaults to global.
        resp = self.client.get(s.get_absolute_url())
        self.assertEqual(resp.context["form"]["scope"].value(), "global")

    def test_comment_scope_dropdown_excludes_global_for_private_only_post(self):
        s = make_submission(
            title="lab note",
            body="x",
            author=self.author,
            global_=False,
            communities=[self.private_community],
        )
        self.client.force_login(self.member)
        resp = self.client.get(s.get_absolute_url())
        choices = [v for v, _ in resp.context["form"]["scope"].field.choices]
        self.assertNotIn("global", choices)
        self.assertIn(f"c{self.private_community.id}", choices)

    def test_comment_scope_dropdown_offers_side_channel(self):
        # Global-only submission. Member should be offered c/my-lab as a side channel.
        s = make_submission(title="open paper", body="x", author=self.author)
        self.client.force_login(self.member)
        resp = self.client.get(s.get_absolute_url())
        labels = [label for _, label in resp.context["form"]["scope"].field.choices]
        self.assertTrue(any("side channel" in lbl for lbl in labels))

    def test_comment_side_channel_post_creates_private_scope(self):
        s = make_submission(title="open paper", body="x", author=self.author)
        self.client.force_login(self.member)
        self.client.post(
            s.get_absolute_url(),
            {"body": "lab whisper", "scope": f"c{self.private_community.id}"},
        )
        c = Comment.objects.get(body="lab whisper")
        scopes = [(sc.kind, sc.community_id) for sc in c.scopes.all()]
        self.assertEqual(scopes, [("community", self.private_community.id)])

    def test_reply_page_inherits_parent_scope(self):
        s = make_submission(title="open paper", body="x", author=self.author)
        parent = make_comment(
            s,
            author=self.author,
            body="lab whisper",
            global_=False,
            communities=[self.private_community],
        )
        self.client.force_login(self.member)
        # Reply page renders with the parent's scope as a hidden field.
        resp = self.client.get(f"/item/{s.pk}/reply/{parent.pk}/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(
            resp,
            f'name="scope" value="c{self.private_community.id}"',
        )
        # POSTing a reply through the reply view inherits the parent's scope.
        self.client.post(
            f"/item/{s.pk}/reply/{parent.pk}/",
            {"body": "agreed", "scope": f"c{self.private_community.id}"},
        )
        reply = Comment.objects.get(body="agreed")
        self.assertEqual(reply.parent_id, parent.pk)
        scopes = [(sc.kind, sc.community_id) for sc in reply.scopes.all()]
        self.assertEqual(scopes, [("community", self.private_community.id)])

    def test_reply_link_in_comment_subtext(self):
        s = make_submission(title="paper", body="x", author=self.author)
        parent = make_comment(s, author=self.author, body="root")
        self.client.force_login(self.author)
        resp = self.client.get(s.get_absolute_url())
        self.assertContains(resp, f'/item/{s.pk}/reply/{parent.pk}/')

    def test_reply_page_shows_parent_and_siblings(self):
        s = make_submission(title="paper", body="x", author=self.author)
        root = make_comment(s, author=self.author, body="root")
        target = make_comment(s, author=self.author, parent=root, body="target")
        # Sibling of target (same parent_id)
        sibling = make_comment(s, author=self.author, parent=root, body="sib")
        self.client.force_login(self.author)
        resp = self.client.get(f"/item/{s.pk}/reply/{target.pk}/")
        self.assertContains(resp, "target")
        self.assertContains(resp, "sib")
        self.assertNotContains(resp, "root")  # ancestors are not shown

    def test_reply_page_404_for_hidden_parent(self):
        # Outsider can't open a reply page for a comment in a private community.
        s = make_submission(title="paper", body="x", author=self.author)
        secret = make_comment(
            s,
            author=self.author,
            body="lab only",
            global_=False,
            communities=[self.private_community],
        )
        self.client.force_login(self.outsider)
        resp = self.client.get(f"/item/{s.pk}/reply/{secret.pk}/")
        self.assertEqual(resp.status_code, 404)

    def test_comment_scope_badge_renders_for_community_scoped(self):
        s = make_submission(
            title="paper",
            body="x",
            author=self.author,
            communities=[self.public_community],
        )
        make_comment(
            s,
            author=self.author,
            body="lab whisper",
            global_=False,
            communities=[self.public_community],
        )
        make_comment(s, author=self.author, body="public chatter")
        resp = self.client.get(s.get_absolute_url())
        # Community-scoped comment shows badge; global one does not.
        body = resp.content.decode()
        # The badge fragment used by the template
        self.assertIn("in <a", body)
        self.assertIn("c/ml-systems", body)

    def test_community_feed_discuss_link_carries_in_param(self):
        make_submission(
            title="cross",
            body="x",
            author=self.author,
            communities=[self.public_community],
        )
        resp = self.client.get("/c/ml-systems/")
        self.assertContains(resp, "?in=ml-systems")
        # Home feed has no community context.
        resp = self.client.get("/")
        self.assertNotContains(resp, "?in=")

    def test_submit_to_private_you_dont_belong_to_fails(self):
        self.client.force_login(self.outsider)
        resp = self.client.post(
            "/submit/",
            {
                "title": "intruder",
                "url": "",
                "body": "hi",
                "communities": [self.private_community.pk],
            },
        )
        # Form should reject the choice (queryset is restricted to writable communities)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Submission.objects.filter(title="intruder").exists())
