from datetime import timedelta

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from .models import Comment, CommentVote, Profile, Save, Submission, SubmissionVote
from .ranking import hot_score


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
        s1 = Submission.objects.create(title="a", body="x", author=self.user)
        s2 = Submission.objects.create(title="b", body="y", author=self.user)
        parent = Comment.objects.create(submission=s1, author=self.user, body="p")
        with self.assertRaises(ValidationError):
            Comment(submission=s2, parent=parent, author=self.user, body="c").clean()

    def test_vote_unique_constraints(self):
        s = Submission.objects.create(title="a", body="x", author=self.user)
        SubmissionVote.objects.create(submission=s, user=self.user)
        with self.assertRaises(IntegrityError):
            SubmissionVote.objects.create(submission=s, user=self.user)

    def test_visible_excludes_removed(self):
        Submission.objects.create(title="ok", body="x", author=self.user)
        Submission.objects.create(
            title="gone", body="x", author=self.user, is_removed=True
        )
        self.assertEqual(Submission.objects.visible().count(), 1)


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

    def test_submit_requires_login(self):
        resp = self.client.get("/submit/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login/", resp["Location"])

    def test_submit_link_and_text(self):
        self.client.force_login(self.user)
        self.client.post(
            "/submit/", {"title": "a link", "url": "https://example.com", "body": ""}
        )
        self.client.post(
            "/submit/", {"title": "a text", "url": "", "body": "some words"}
        )
        self.assertEqual(Submission.objects.count(), 2)
        link = Submission.objects.get(title="a link")
        text = Submission.objects.get(title="a text")
        self.assertEqual(link.kind, "link")
        self.assertEqual(text.kind, "text")

    def test_submit_invalid_both_fields(self):
        self.client.force_login(self.user)
        resp = self.client.post(
            "/submit/",
            {"title": "x", "url": "https://example.com", "body": "text too"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Submission.objects.count(), 0)

    def test_comment_requires_login_and_nests(self):
        s = Submission.objects.create(title="a", body="x", author=self.user)
        resp = self.client.post(s.get_absolute_url(), {"body": "anon comment"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Comment.objects.count(), 0)

        self.client.force_login(self.user)
        self.client.post(s.get_absolute_url(), {"body": "top level"})
        top = Comment.objects.get()
        self.client.post(
            s.get_absolute_url(), {"body": "a reply", "parent_id": top.pk}
        )
        reply = Comment.objects.get(body="a reply")
        self.assertEqual(reply.parent_id, top.pk)

    def test_voting_idempotent(self):
        s = Submission.objects.create(title="a", body="x", author=self.user)
        self.client.force_login(self.user)
        url = f"/vote/submission/{s.pk}/"
        self.client.post(url)
        self.client.post(url)
        self.assertEqual(SubmissionVote.objects.filter(submission=s).count(), 1)

    def test_vote_get_not_allowed(self):
        s = Submission.objects.create(title="a", body="x", author=self.user)
        self.client.force_login(self.user)
        resp = self.client.get(f"/vote/submission/{s.pk}/")
        self.assertEqual(resp.status_code, 405)

    def test_vote_requires_login(self):
        s = Submission.objects.create(title="a", body="x", author=self.user)
        resp = self.client.post(f"/vote/submission/{s.pk}/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login/", resp["Location"])

    def test_comment_vote(self):
        s = Submission.objects.create(title="a", body="x", author=self.user)
        c = Comment.objects.create(submission=s, author=self.user, body="hi")
        self.client.force_login(self.user)
        self.client.post(f"/vote/comment/{c.pk}/")
        self.assertEqual(CommentVote.objects.filter(comment=c).count(), 1)

    def test_new_page_orders_by_created(self):
        old = Submission.objects.create(title="old", body="x", author=self.user)
        new = Submission.objects.create(title="new", body="x", author=self.user)
        resp = self.client.get("/new/")
        items = list(resp.context["page_obj"])
        self.assertEqual([items[0].pk, items[1].pk], [new.pk, old.pk])

    def test_removed_submission_absent_from_listings(self):
        Submission.objects.create(
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

    def test_save_unique_constraint(self):
        Save.objects.create(submission=self.sub, user=self.user)
        with self.assertRaises(IntegrityError):
            Save.objects.create(submission=self.sub, user=self.user)

    def test_toggle_save_creates_then_deletes(self):
        self.client.force_login(self.user)
        url = f"/save/submission/{self.sub.pk}/"
        self.client.post(url)
        self.assertEqual(Save.objects.count(), 1)
        self.client.post(url)
        self.assertEqual(Save.objects.count(), 0)

    def test_toggle_save_requires_login(self):
        resp = self.client.post(f"/save/submission/{self.sub.pk}/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login/", resp["Location"])

    def test_toggle_save_get_not_allowed(self):
        self.client.force_login(self.user)
        resp = self.client.get(f"/save/submission/{self.sub.pk}/")
        self.assertEqual(resp.status_code, 405)

    def test_saved_page_requires_login(self):
        resp = self.client.get("/saved/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login/", resp["Location"])

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

    def test_user_page_404_unknown_user(self):
        resp = self.client.get("/u/nobody/")
        self.assertEqual(resp.status_code, 404)
