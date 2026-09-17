import unittest

from gitbot.models import PullRequest, Repo
from gitbot.poller import summarize_reviews
from gitbot.render import render_pull_request

REPO = Repo("NON-OS/nonos-micro-kernel", "https://git.nonos.software/NON-OS/nonos-micro-kernel", "main", False)


def review(login, state, at):
    return {"user": {"login": login}, "state": state, "submitted_at": at}


class SummarizeTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(summarize_reviews([]), ((), ()))

    def test_single_approval(self):
        approved, changes = summarize_reviews([review("ek", "APPROVED", "2026-09-14T10:00:00Z")])
        self.assertEqual(approved, ("ek",))
        self.assertEqual(changes, ())

    def test_latest_decisive_review_wins(self):
        approved, changes = summarize_reviews(
            [
                review("ek", "APPROVED", "2026-09-14T10:00:00Z"),
                review("ek", "REQUEST_CHANGES", "2026-09-14T12:00:00Z"),
            ]
        )
        self.assertEqual(approved, ())
        self.assertEqual(changes, ("ek",))

    def test_comment_reviews_ignored(self):
        approved, changes = summarize_reviews(
            [review("ek", "COMMENT", "2026-09-14T10:00:00Z"), review("sam", "APPROVED", "2026-09-14T11:00:00Z")]
        )
        self.assertEqual(approved, ("sam",))
        self.assertEqual(changes, ())

    def test_two_reviewers_sorted(self):
        approved, _ = summarize_reviews(
            [review("zoe", "APPROVED", "2026-09-14T10:00:00Z"), review("amy", "APPROVED", "2026-09-14T11:00:00Z")]
        )
        self.assertEqual(approved, ("amy", "zoe"))


def a_pr(**kw):
    base = {
        "repo": REPO,
        "action": "opened",
        "number": 37,
        "title": "i2c core",
        "url": "https://git.nonos.software/NON-OS/nonos-micro-kernel/pulls/37",
        "state": "open",
        "merged": False,
        "base_ref": "main",
        "head_label": "",
        "body": "",
        "opener": "ek",
    }
    base.update(kw)
    return PullRequest(**base)


class RenderReviewTests(unittest.TestCase):
    def test_approved_line(self):
        out = render_pull_request(a_pr(approved_by=("ek",)), "ek")
        self.assertIn("Approved by ek", out)

    def test_changes_requested_takes_precedence(self):
        out = render_pull_request(a_pr(approved_by=("ek",), changes_by=("sam",)), "ek")
        self.assertIn("Changes requested by sam", out)
        self.assertNotIn("Approved by", out)

    def test_no_review_no_line(self):
        out = render_pull_request(a_pr(), "ek")
        self.assertNotIn("Approved", out)
        self.assertNotIn("Changes requested", out)
