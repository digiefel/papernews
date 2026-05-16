from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from .citations import (
    extract_metadata,
    fetch_bibtex_for_doi,
    normalize_doi,
    parse_bibtex,
)
from .models import (
    Author,
    Comment,
    CommentScope,
    CommentVote,
    Community,
    CommunityMembership,
    Profile,
    Save,
    Submission,
    SubmissionAuthor,
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
        s1 = make_submission(title="first", body="x", author=self.user)
        host = make_submission(title="host", body="x", author=self.other)
        c1 = make_comment(host, author=self.user, body="c1")
        s2 = make_submission(title="second", body="y", author=self.user)

        resp = self.client.get(f"/u/{self.user.username}/")
        items = list(resp.context["page_obj"])
        self.assertEqual([i.pk for i in items], [s2.pk, c1.pk, s1.pk])
        self.assertEqual(
            [i.item_type for i in items], ["submission", "comment", "submission"]
        )

    def test_user_page_excludes_removed(self):
        make_submission(
            title="hidden", body="x", author=self.user, is_removed=True
        )
        host_ok = make_submission(title="ok host", body="x", author=self.other)
        host_gone = make_submission(
            title="gone host", body="x", author=self.other, is_removed=True
        )
        make_comment(
            host_ok, author=self.user, body="removed", is_removed=True
        )
        make_comment(host_gone, author=self.user, body="orphan")

        resp = self.client.get(f"/u/{self.user.username}/")
        self.assertEqual(len(resp.context["page_obj"]), 0)

    def test_user_page_hides_private_only_submission_from_outsider(self):
        private = Community.objects.create(
            slug="lab", name="Lab", is_private=True
        )
        CommunityMembership.objects.create(community=private, user=self.user)
        make_submission(
            title="secret-paper",
            body="x",
            author=self.user,
            global_=False,
            communities=[private],
        )
        resp = self.client.get(f"/u/{self.user.username}/")
        self.assertNotContains(resp, "secret-paper")

    def test_user_page_shows_private_submission_to_member(self):
        private = Community.objects.create(
            slug="lab", name="Lab", is_private=True
        )
        CommunityMembership.objects.create(community=private, user=self.user)
        CommunityMembership.objects.create(community=private, user=self.other)
        make_submission(
            title="secret-paper",
            body="x",
            author=self.user,
            global_=False,
            communities=[private],
        )
        self.client.force_login(self.other)
        resp = self.client.get(f"/u/{self.user.username}/")
        self.assertContains(resp, "secret-paper")

    def test_user_page_hides_private_only_comment_from_outsider(self):
        private = Community.objects.create(
            slug="lab", name="Lab", is_private=True
        )
        CommunityMembership.objects.create(community=private, user=self.user)
        host = make_submission(title="host", body="x", author=self.other)
        make_comment(
            host,
            author=self.user,
            body="lab-only-comment",
            global_=False,
            communities=[private],
        )
        resp = self.client.get(f"/u/{self.user.username}/")
        self.assertNotContains(resp, "lab-only-comment")

    def test_home_feed_hides_private_community_label_from_outsider(self):
        # A submission posted globally AND to a private community should not
        # leak the private community's slug to outsiders viewing the home feed.
        private = Community.objects.create(
            slug="secret-lab", name="Secret Lab", is_private=True
        )
        CommunityMembership.objects.create(community=private, user=self.user)
        make_submission(
            title="cross-posted",
            body="x",
            author=self.user,
            communities=[private],
        )
        resp = self.client.get("/")
        self.assertContains(resp, "cross-posted")
        self.assertNotContains(resp, "secret-lab")

    def test_home_feed_shows_private_community_label_to_member(self):
        private = Community.objects.create(
            slug="secret-lab", name="Secret Lab", is_private=True
        )
        CommunityMembership.objects.create(community=private, user=self.user)
        CommunityMembership.objects.create(community=private, user=self.other)
        make_submission(
            title="cross-posted",
            body="x",
            author=self.user,
            communities=[private],
        )
        self.client.force_login(self.other)
        resp = self.client.get("/")
        self.assertContains(resp, "secret-lab")


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
        # Member must have joined c/ml-systems to be able to reply there.
        CommunityMembership.objects.create(
            community=self.public_community, user=self.member
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

    def test_submit_to_public_you_havent_joined_fails(self):
        # Membership now gates posting into public communities too.
        self.client.force_login(self.outsider)
        resp = self.client.post(
            "/submit/",
            {
                "title": "drive-by",
                "url": "",
                "body": "hi",
                "communities": [self.public_community.pk],
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Submission.objects.filter(title="drive-by").exists())

    def test_join_public_community_creates_membership(self):
        self.client.force_login(self.outsider)
        resp = self.client.post(f"/c/{self.public_community.slug}/join/")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            CommunityMembership.objects.filter(
                community=self.public_community, user=self.outsider
            ).exists()
        )

    def test_join_public_is_idempotent(self):
        CommunityMembership.objects.create(
            community=self.public_community, user=self.outsider
        )
        self.client.force_login(self.outsider)
        resp = self.client.post(f"/c/{self.public_community.slug}/join/")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(
            CommunityMembership.objects.filter(
                community=self.public_community, user=self.outsider
            ).count(),
            1,
        )

    def test_join_private_community_404(self):
        self.client.force_login(self.outsider)
        resp = self.client.post(f"/c/{self.private_community.slug}/join/")
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(
            CommunityMembership.objects.filter(
                community=self.private_community, user=self.outsider
            ).exists()
        )

    def test_join_requires_login(self):
        resp = self.client.post(f"/c/{self.public_community.slug}/join/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login/", resp["Location"])

    def test_leave_get_renders_confirm_page(self):
        CommunityMembership.objects.create(
            community=self.private_community, user=self.outsider
        )
        self.client.force_login(self.outsider)
        resp = self.client.get(f"/c/{self.private_community.slug}/leave/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, f"Leave")
        self.assertContains(resp, "private community")
        # The actual leave hasn't happened yet — membership still present.
        self.assertTrue(
            CommunityMembership.objects.filter(
                community=self.private_community, user=self.outsider
            ).exists()
        )

    def test_leave_get_for_last_mod_shows_block_message(self):
        # mod role on the public community for variety; same logic applies.
        only_mod = User.objects.create_user("solo", password="pw-test-12345")
        CommunityMembership.objects.create(
            community=self.public_community, user=only_mod, is_moderator=True
        )
        self.client.force_login(only_mod)
        resp = self.client.get(f"/c/{self.public_community.slug}/leave/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "only moderator")

    def test_leave_link_on_private_community_page(self):
        CommunityMembership.objects.create(
            community=self.private_community, user=self.outsider
        )
        self.client.force_login(self.outsider)
        resp = self.client.get(f"/c/{self.private_community.slug}/")
        # The "joined" indicator is a link to the confirm page, not a form
        # POST — that's what makes the confirm step work without JS.
        self.assertContains(
            resp, f'href="/c/{self.private_community.slug}/leave/"'
        )
        self.assertNotContains(
            resp, f'action="/c/{self.private_community.slug}/leave/"'
        )

    def test_leave_public_deletes_membership(self):
        CommunityMembership.objects.create(
            community=self.public_community, user=self.outsider
        )
        self.client.force_login(self.outsider)
        resp = self.client.post(f"/c/{self.public_community.slug}/leave/")
        self.assertRedirects(resp, f"/c/{self.public_community.slug}/")
        self.assertFalse(
            CommunityMembership.objects.filter(
                community=self.public_community, user=self.outsider
            ).exists()
        )

    def test_leave_private_redirects_to_index(self):
        self.client.force_login(self.member)
        resp = self.client.post(f"/c/{self.private_community.slug}/leave/")
        self.assertRedirects(resp, "/communities/")
        self.assertFalse(
            CommunityMembership.objects.filter(
                community=self.private_community, user=self.member
            ).exists()
        )

    def test_community_page_shows_join_button_for_non_member(self):
        self.client.force_login(self.outsider)
        resp = self.client.get(f"/c/{self.public_community.slug}/")
        self.assertContains(resp, f'action="/c/{self.public_community.slug}/join/"')

    def test_community_page_shows_leave_button_for_member(self):
        CommunityMembership.objects.create(
            community=self.public_community, user=self.outsider
        )
        self.client.force_login(self.outsider)
        resp = self.client.get(f"/c/{self.public_community.slug}/")
        self.assertContains(resp, f'action="/c/{self.public_community.slug}/leave/"')


class CommunityCreationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("creator", password="pw-test-12345")

    def test_create_requires_login(self):
        resp = self.client.get("/communities/new/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login/", resp["Location"])

    def test_create_community_makes_creator_moderator(self):
        # Public communities require staff; mark the creator so we can verify
        # the full create flow including is_private toggling.
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)
        resp = self.client.post(
            "/communities/new/",
            {
                "slug": "new-stuff",
                "name": "New Stuff",
                "description": "what we do",
                "color": "#112233",
                "is_private": "",
            },
        )
        self.assertEqual(resp.status_code, 302)
        community = Community.objects.get(slug="new-stuff")
        self.assertEqual(community.name, "New Stuff")
        self.assertEqual(community.color, "#112233")
        self.assertFalse(community.is_private)
        self.assertTrue(
            CommunityMembership.objects.filter(
                community=community, user=self.user, is_moderator=True
            ).exists()
        )

    def test_non_admin_create_is_forced_private(self):
        self.client.force_login(self.user)  # not staff
        resp = self.client.post(
            "/communities/new/",
            {
                "slug": "lab-x",
                "name": "Lab X",
                "description": "",
                "color": "#ff6600",
                # Even if the user tries to send is_private=off, the field
                # isn't on the form and the save path forces True.
                "is_private": "",
            },
        )
        self.assertEqual(resp.status_code, 302)
        community = Community.objects.get(slug="lab-x")
        self.assertTrue(community.is_private)

    def test_non_admin_does_not_see_privacy_toggle(self):
        self.client.force_login(self.user)
        resp = self.client.get("/communities/new/")
        self.assertNotContains(resp, 'name="is_private"')

    def test_create_rejects_duplicate_slug(self):
        Community.objects.create(slug="taken", name="T")
        self.client.force_login(self.user)
        resp = self.client.post(
            "/communities/new/",
            {
                "slug": "taken",
                "name": "Mine",
                "description": "",
                "color": "#ff6600",
                "is_private": "",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Community.objects.filter(slug="taken").count(), 1)


class CommunityModerationTests(TestCase):
    def setUp(self):
        self.mod = User.objects.create_user("mod", password="pw-test-12345")
        self.other_mod = User.objects.create_user("comod", password="pw-test-12345")
        self.member = User.objects.create_user("member", password="pw-test-12345")
        self.outsider = User.objects.create_user("nope", password="pw-test-12345")
        self.community = Community.objects.create(slug="lab", name="Lab")
        CommunityMembership.objects.create(
            community=self.community, user=self.mod, is_moderator=True
        )
        CommunityMembership.objects.create(
            community=self.community, user=self.member
        )

    def test_manage_page_404_for_non_moderator(self):
        self.client.force_login(self.member)
        resp = self.client.get(f"/c/{self.community.slug}/manage/")
        self.assertEqual(resp.status_code, 404)

    def test_manage_page_404_for_anon(self):
        resp = self.client.get(f"/c/{self.community.slug}/manage/")
        self.assertEqual(resp.status_code, 302)  # login redirect

    def test_moderator_can_edit_settings(self):
        self.client.force_login(self.mod)
        resp = self.client.post(
            f"/c/{self.community.slug}/manage/",
            {
                "name": "Lab (renamed)",
                "description": "now with more rigor",
                "color": "#abcdef",
                # Non-admin mod can't toggle privacy — field is dropped from
                # the form, so the original value is preserved.
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.community.refresh_from_db()
        self.assertEqual(self.community.name, "Lab (renamed)")
        self.assertEqual(self.community.color, "#abcdef")
        self.assertFalse(self.community.is_private)
        # Slug is intentionally not editable through this form.
        self.assertEqual(self.community.slug, "lab")

    def test_non_admin_mod_cannot_flip_privacy(self):
        # mod is not staff; sending is_private=on should be ignored.
        self.client.force_login(self.mod)
        self.client.post(
            f"/c/{self.community.slug}/manage/",
            {
                "name": "Lab",
                "description": "",
                "color": "#ff6600",
                "is_private": "on",
            },
        )
        self.community.refresh_from_db()
        self.assertFalse(self.community.is_private)

    def test_admin_mod_can_flip_privacy(self):
        self.mod.is_staff = True
        self.mod.save()
        self.client.force_login(self.mod)
        self.client.post(
            f"/c/{self.community.slug}/manage/",
            {
                "name": "Lab",
                "description": "",
                "color": "#ff6600",
                "is_private": "on",
            },
        )
        self.community.refresh_from_db()
        self.assertTrue(self.community.is_private)

    def test_moderator_can_remove_regular_member(self):
        self.client.force_login(self.mod)
        resp = self.client.post(
            f"/c/{self.community.slug}/members/{self.member.id}/remove/"
        )
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(
            CommunityMembership.objects.filter(
                community=self.community, user=self.member
            ).exists()
        )

    def test_cannot_remove_last_moderator(self):
        self.client.force_login(self.mod)
        resp = self.client.post(
            f"/c/{self.community.slug}/members/{self.mod.id}/remove/"
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            CommunityMembership.objects.filter(
                community=self.community, user=self.mod
            ).exists()
        )

    def test_can_remove_mod_when_another_mod_exists(self):
        CommunityMembership.objects.create(
            community=self.community, user=self.other_mod, is_moderator=True
        )
        self.client.force_login(self.mod)
        resp = self.client.post(
            f"/c/{self.community.slug}/members/{self.other_mod.id}/remove/"
        )
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(
            CommunityMembership.objects.filter(
                community=self.community, user=self.other_mod
            ).exists()
        )

    def test_last_moderator_cannot_leave(self):
        self.client.force_login(self.mod)
        resp = self.client.post(f"/c/{self.community.slug}/leave/")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            CommunityMembership.objects.filter(
                community=self.community, user=self.mod
            ).exists()
        )

    def test_manage_link_visible_only_to_mod(self):
        self.client.force_login(self.mod)
        resp = self.client.get(f"/c/{self.community.slug}/")
        self.assertContains(resp, f'href="/c/{self.community.slug}/manage/"')
        self.client.force_login(self.member)
        resp = self.client.get(f"/c/{self.community.slug}/")
        self.assertNotContains(resp, f'href="/c/{self.community.slug}/manage/"')

    def test_non_moderator_cannot_remove_member(self):
        self.client.force_login(self.member)
        resp = self.client.post(
            f"/c/{self.community.slug}/members/{self.mod.id}/remove/"
        )
        self.assertEqual(resp.status_code, 404)
        self.assertTrue(
            CommunityMembership.objects.filter(
                community=self.community, user=self.mod
            ).exists()
        )

    def test_manage_page_marks_current_user_and_hides_self_remove(self):
        self.client.force_login(self.mod)
        resp = self.client.get(f"/c/{self.community.slug}/manage/")
        self.assertContains(resp, "(you)")
        # No remove form action targeting the current user.
        self.assertNotContains(
            resp,
            f'action="/c/{self.community.slug}/members/{self.mod.id}/remove/"',
        )
        # But the other (regular) member still gets a remove form.
        self.assertContains(
            resp,
            f'action="/c/{self.community.slug}/members/{self.member.id}/remove/"',
        )

    def test_moderator_can_add_member(self):
        self.client.force_login(self.mod)
        resp = self.client.post(
            f"/c/{self.community.slug}/members/add/",
            {"username": self.outsider.username},
        )
        self.assertEqual(resp.status_code, 302)
        membership = CommunityMembership.objects.get(
            community=self.community, user=self.outsider
        )
        self.assertFalse(membership.is_moderator)

    def test_moderator_can_add_member_as_moderator(self):
        self.client.force_login(self.mod)
        resp = self.client.post(
            f"/c/{self.community.slug}/members/add/",
            {"username": self.outsider.username, "is_moderator": "on"},
        )
        self.assertEqual(resp.status_code, 302)
        membership = CommunityMembership.objects.get(
            community=self.community, user=self.outsider
        )
        self.assertTrue(membership.is_moderator)

    def test_add_unknown_user_shows_error(self):
        self.client.force_login(self.mod)
        resp = self.client.post(
            f"/c/{self.community.slug}/members/add/",
            {"username": "ghost"},
            follow=True,
        )
        self.assertContains(resp, "No user named")
        self.assertFalse(
            CommunityMembership.objects.filter(
                community=self.community, user__username="ghost"
            ).exists()
        )

    def test_add_existing_member_shows_error(self):
        self.client.force_login(self.mod)
        resp = self.client.post(
            f"/c/{self.community.slug}/members/add/",
            {"username": self.member.username},
            follow=True,
        )
        self.assertContains(resp, "already a member")
        self.assertEqual(
            CommunityMembership.objects.filter(
                community=self.community, user=self.member
            ).count(),
            1,
        )

    def test_non_moderator_cannot_add_member(self):
        self.client.force_login(self.member)
        resp = self.client.post(
            f"/c/{self.community.slug}/members/add/",
            {"username": self.outsider.username},
        )
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(
            CommunityMembership.objects.filter(
                community=self.community, user=self.outsider
            ).exists()
        )

    def test_add_member_requires_login(self):
        resp = self.client.post(
            f"/c/{self.community.slug}/members/add/",
            {"username": self.outsider.username},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login/", resp["Location"])

    def test_moderator_can_promote_member(self):
        self.client.force_login(self.mod)
        resp = self.client.post(
            f"/c/{self.community.slug}/members/{self.member.id}/toggle-mod/"
        )
        self.assertEqual(resp.status_code, 302)
        membership = CommunityMembership.objects.get(
            community=self.community, user=self.member
        )
        self.assertTrue(membership.is_moderator)

    def test_moderator_can_demote_another_moderator(self):
        CommunityMembership.objects.create(
            community=self.community, user=self.other_mod, is_moderator=True
        )
        self.client.force_login(self.mod)
        resp = self.client.post(
            f"/c/{self.community.slug}/members/{self.other_mod.id}/toggle-mod/"
        )
        self.assertEqual(resp.status_code, 302)
        membership = CommunityMembership.objects.get(
            community=self.community, user=self.other_mod
        )
        self.assertFalse(membership.is_moderator)

    def test_cannot_demote_last_moderator(self):
        self.client.force_login(self.mod)
        resp = self.client.post(
            f"/c/{self.community.slug}/members/{self.mod.id}/toggle-mod/"
        )
        self.assertEqual(resp.status_code, 302)
        membership = CommunityMembership.objects.get(
            community=self.community, user=self.mod
        )
        self.assertTrue(membership.is_moderator)

    def test_moderator_can_step_down_when_another_mod_exists(self):
        CommunityMembership.objects.create(
            community=self.community, user=self.other_mod, is_moderator=True
        )
        self.client.force_login(self.mod)
        resp = self.client.post(
            f"/c/{self.community.slug}/members/{self.mod.id}/toggle-mod/"
        )
        self.assertEqual(resp.status_code, 302)
        membership = CommunityMembership.objects.get(
            community=self.community, user=self.mod
        )
        self.assertFalse(membership.is_moderator)

    def test_non_moderator_cannot_toggle_mod(self):
        self.client.force_login(self.member)
        resp = self.client.post(
            f"/c/{self.community.slug}/members/{self.mod.id}/toggle-mod/"
        )
        self.assertEqual(resp.status_code, 404)
        membership = CommunityMembership.objects.get(
            community=self.community, user=self.mod
        )
        self.assertTrue(membership.is_moderator)

    def test_manage_page_shows_promote_button_for_regular_member(self):
        self.client.force_login(self.mod)
        resp = self.client.get(f"/c/{self.community.slug}/manage/")
        self.assertContains(resp, "make moderator")
        self.assertContains(
            resp,
            f'action="/c/{self.community.slug}/members/{self.member.id}/toggle-mod/"',
        )

    def test_manage_page_shows_step_down_for_self_mod(self):
        CommunityMembership.objects.create(
            community=self.community, user=self.other_mod, is_moderator=True
        )
        self.client.force_login(self.mod)
        resp = self.client.get(f"/c/{self.community.slug}/manage/")
        self.assertContains(resp, "step down")


SAMPLE_BIBTEX = """@article{shannon1948,
  title = {A Mathematical Theory of Communication},
  author = {Shannon, Claude E. and Weaver, Warren},
  journal = {Bell System Technical Journal},
  year = {1948},
  doi = {10.1002/j.1538-7305.1948.tb01338.x},
  url = {https://example.org/shannon}
}"""


class CitationsTests(TestCase):
    def test_parse_bibtex_extracts_known_fields(self):
        parsed = parse_bibtex(SAMPLE_BIBTEX)
        self.assertEqual(parsed["title"], "A Mathematical Theory of Communication")
        self.assertEqual(
            parsed["authors"], ["Shannon, Claude E.", "Weaver, Warren"]
        )
        self.assertEqual(parsed["year"], 1948)
        self.assertEqual(parsed["source"], "Bell System Technical Journal")
        self.assertEqual(parsed["doi"], "10.1002/j.1538-7305.1948.tb01338.x")
        self.assertEqual(parsed["url"], "https://example.org/shannon")

    def test_parse_bibtex_booktitle_maps_to_source(self):
        text = (
            "@inproceedings{x, title={T}, author={A}, "
            "booktitle={conference}, year={2020}}"
        )
        parsed = parse_bibtex(text)
        self.assertEqual(parsed["source"], "conference")

    def test_parse_bibtex_malformed_returns_none(self):
        self.assertIsNone(parse_bibtex("not bibtex"))
        self.assertIsNone(parse_bibtex(""))

    def test_normalize_doi_strips_prefixes(self):
        for raw in (
            "10.1048/x.y",
            "https://doi.org/10.1048/x.y",
            "http://dx.doi.org/10.1048/x.y",
            "  doi:10.1048/x.y  ",
        ):
            self.assertEqual(normalize_doi(raw), "10.1048/x.y")

    def test_normalize_doi_rejects_garbage(self):
        self.assertIsNone(normalize_doi("not a doi"))
        self.assertIsNone(normalize_doi(""))
        self.assertIsNone(normalize_doi(None))

    def _patched_urlopen(self, body_bytes, captured=None):
        class FakeResp:
            status = 200
            headers = type("H", (), {"get_content_charset": lambda self: "utf-8"})()

            def read(self, n=-1):
                return body_bytes if n < 0 else body_bytes[:n]

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

        def fake_urlopen(req, timeout=5):
            if captured is not None:
                captured["url"] = req.full_url
                captured["accept"] = req.get_header("Accept")
            return FakeResp()

        return fake_urlopen

    def test_fetch_bibtex_for_doi_uses_content_negotiation(self):
        captured = {}
        fake = self._patched_urlopen(SAMPLE_BIBTEX.encode("utf-8"), captured)
        with patch("core.citations.urllib.request.urlopen", fake):
            body = fetch_bibtex_for_doi("10.1048/x.y")
        self.assertEqual(captured["url"], "https://doi.org/10.1048/x.y")
        self.assertEqual(captured["accept"], "application/x-bibtex")
        self.assertIn("A Mathematical Theory of Communication", body)

    def test_fetch_bibtex_for_doi_rejects_oversize_response(self):
        # A malicious redirect serving > _MAX_BIBTEX_RESPONSE_BYTES should be
        # dropped rather than read fully into memory.
        from .citations import _MAX_BIBTEX_RESPONSE_BYTES

        huge = b"x" * (_MAX_BIBTEX_RESPONSE_BYTES + 100)
        fake = self._patched_urlopen(huge)
        with patch("core.citations.urllib.request.urlopen", fake):
            self.assertIsNone(fetch_bibtex_for_doi("10.1048/x.y"))

    def test_extract_metadata_bibtex_path(self):
        meta, kind = extract_metadata(SAMPLE_BIBTEX)
        self.assertEqual(kind, "bibtex")
        self.assertEqual(meta["year"], 1948)

    def test_extract_metadata_doi_path(self):
        with patch(
            "core.citations.fetch_bibtex_for_doi", return_value=SAMPLE_BIBTEX
        ):
            meta, kind = extract_metadata("10.1048/x.y")
        self.assertEqual(kind, "doi")
        self.assertEqual(meta["year"], 1948)
        # DOI from input is used even when the fetched bibtex has its own DOI.
        # Our orchestrator only sets the input-DOI if BibTeX didn't include one.
        self.assertIn("doi", meta)

    def test_extract_metadata_doi_fetch_failure_returns_minimal(self):
        with patch("core.citations.fetch_bibtex_for_doi", return_value=None):
            meta, kind = extract_metadata("10.1048/x.y")
        self.assertEqual(kind, "doi")
        self.assertEqual(meta, {"doi": "10.1048/x.y"})

    def test_extract_metadata_garbage_returns_none(self):
        meta, kind = extract_metadata("just some words")
        self.assertIsNone(meta)
        self.assertIsNone(kind)


class SubmitMetadataTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("bob", password="pw-test-12345")
        self.client.force_login(self.user)

    def test_submit_auto_fills_doi_from_doi_url(self):
        self.client.post(
            "/submit/",
            {
                "action": "submit",
                "title": "Paper",
                "url": "https://doi.org/10.1038/Nature12373",
                "body": "",
                "post_globally": "on",
            },
        )
        sub = Submission.objects.get()
        self.assertEqual(sub.doi, "10.1038/nature12373")

    def test_submit_normalizes_bare_doi_in_url_field(self):
        # URL field accepts a bare DOI as shorthand; it gets canonicalized to
        # a doi.org URL and the model's doi field is auto-populated on save.
        self.client.post(
            "/submit/",
            {
                "action": "submit",
                "title": "Paper",
                "url": "10.1038/Nature12373",
                "body": "",
                "post_globally": "on",
            },
        )
        sub = Submission.objects.get()
        self.assertEqual(sub.url, "https://doi.org/10.1038/nature12373")
        self.assertEqual(sub.doi, "10.1038/nature12373")

    def test_submit_rejects_garbage_in_url_field(self):
        # Neither a valid URL nor a DOI — should be a form error, no submission.
        resp = self.client.post(
            "/submit/",
            {
                "action": "submit",
                "title": "Paper",
                "url": "not a url and not a doi",
                "body": "",
                "post_globally": "on",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Submission.objects.count(), 0)
        self.assertIn("url", resp.context["form"].errors)

    def test_submit_persists_metadata_and_creates_authors(self):
        resp = self.client.post(
            "/submit/",
            {
                "action": "submit",
                "title": "Paper",
                "url": "https://example.com/p",
                "body": "",
                "year": "2023",
                "source": "journal",
                "authors_text": "Smith, J.; Doe, A.",
                "post_globally": "on",
            },
        )
        self.assertEqual(resp.status_code, 302)
        sub = Submission.objects.get()
        self.assertEqual(sub.year, 2023)
        self.assertEqual(sub.source, "journal")
        sas = list(sub.submission_authors.all())
        self.assertEqual(len(sas), 2)
        self.assertEqual([sa.position for sa in sas], [0, 1])
        self.assertEqual(
            [sa.author.name for sa in sas], ["Smith, J.", "Doe, A."]
        )

    def test_resubmit_reuses_author_rows(self):
        Author.objects.create(name="Smith, J.")
        self.client.post(
            "/submit/",
            {
                "action": "submit",
                "title": "P1",
                "url": "https://example.com/1",
                "body": "",
                "authors_text": "Smith, J.",
                "post_globally": "on",
            },
        )
        self.client.post(
            "/submit/",
            {
                "action": "submit",
                "title": "P2",
                "url": "https://example.com/2",
                "body": "",
                "authors_text": "Smith, J.",
                "post_globally": "on",
            },
        )
        self.assertEqual(Author.objects.filter(name="Smith, J.").count(), 1)
        self.assertEqual(SubmissionAuthor.objects.count(), 2)

    def test_metadata_renders_on_detail_page(self):
        # DOI is stored but intentionally not displayed (metadata only).
        sub = Submission.objects.create(
            title="Paper",
            body="text",
            author=self.user,
            year=2023,
            source="journal",
            doi="10.1048/x.y",
        )
        SubmissionScope.objects.create(submission=sub, kind=SubmissionScope.KIND_GLOBAL)
        a1 = Author.objects.create(name="Smith, J.")
        a2 = Author.objects.create(name="Doe, A.")
        SubmissionAuthor.objects.create(submission=sub, author=a1, position=0)
        SubmissionAuthor.objects.create(submission=sub, author=a2, position=1)
        resp = self.client.get(sub.get_absolute_url())
        body = resp.content.decode()
        self.assertIn("Smith, J.", body)
        self.assertIn("Doe, A.", body)
        self.assertIn("2023", body)
        self.assertIn("journal", body)


class ApiExtractMetadataTests(TestCase):
    """The /api/extract-metadata/ endpoint is the single extraction path; the
    no-JS submit form has no extract button. These tests pin its contract:
    auth-gated JSON, accepts text or file, returns metadata + kind."""

    URL = "/api/extract-metadata/"

    def setUp(self):
        self.user = User.objects.create_user("bob", password="pw-test-12345")

    def test_anonymous_user_gets_401_json(self):
        resp = self.client.post(self.URL, {"text": SAMPLE_BIBTEX})
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp["Content-Type"], "application/json")
        self.assertIn("error", resp.json())

    def test_get_is_405(self):
        self.client.force_login(self.user)
        resp = self.client.get(self.URL)
        self.assertEqual(resp.status_code, 405)

    def test_post_bibtex_text_returns_metadata_and_kind(self):
        self.client.force_login(self.user)
        resp = self.client.post(self.URL, {"text": SAMPLE_BIBTEX})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["kind"], "bibtex")
        self.assertEqual(
            data["metadata"]["title"],
            "A Mathematical Theory of Communication",
        )
        self.assertEqual(data["metadata"]["year"], 1948)

    def test_post_doi_text_returns_metadata(self):
        self.client.force_login(self.user)
        with patch(
            "core.views.extract_metadata",
            return_value=({"title": "T", "doi": "10.1038/x.y"}, "doi"),
        ) as m:
            resp = self.client.post(self.URL, {"text": "10.1038/x.y"})
        m.assert_called_once_with("10.1038/x.y")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["kind"], "doi")
        self.assertEqual(data["metadata"]["doi"], "10.1038/x.y")

    def test_post_garbage_text_returns_400(self):
        self.client.force_login(self.user)
        resp = self.client.post(self.URL, {"text": "random nonsense"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp["Content-Type"], "application/json")

    def test_post_uploaded_bibtex_file_returns_metadata(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.client.force_login(self.user)
        upload = SimpleUploadedFile(
            "shannon.bib",
            SAMPLE_BIBTEX.encode("utf-8"),
            content_type="application/x-bibtex",
        )
        resp = self.client.post(self.URL, {"file": upload})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["kind"], "bibtex")
        self.assertEqual(data["metadata"]["year"], 1948)

    def test_post_oversize_file_rejected(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.client.force_login(self.user)
        upload = SimpleUploadedFile(
            "big.bib",
            b"x" * (200_001),
            content_type="application/x-bibtex",
        )
        resp = self.client.post(self.URL, {"file": upload})
        self.assertEqual(resp.status_code, 413)

