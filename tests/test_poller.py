import tempfile
import unittest
from pathlib import Path

from gitbot.config import Config
from gitbot.poller import PRPoller
from gitbot.state import State

REPO = "NON-OS/nonos-micro-kernel"


def pr_json(number, state="open", merged=False, head="a" * 40, title="A change", draft=False):
    return {
        "number": number,
        "state": state,
        "merged": merged,
        "title": title,
        "html_url": f"https://git.nonos.software/{REPO}/pulls/{number}",
        "base": {"ref": "main"},
        "head": {"label": f"eKisNonos/x:gh-{400 + number}", "sha": head},
        "body": f"Opened on GitHub by eKisNonos as pull request {400 + number}.",
        "user": {"login": "nonos-sync"},
        "draft": draft,
    }


class FakeForge:
    def __init__(self, repos, pulls, reviews=None):
        self._repos = repos
        self.pulls = pulls  # repo -> list[dict]
        self.reviews_by_pr = reviews or {}  # (repo, number) -> list[dict]

    async def org_repos(self, org):
        return self._repos

    async def list_pulls(self, full, limit=30):
        return self.pulls.get(full, [])

    async def reviews(self, full, number):
        return self.reviews_by_pr.get((full, number), [])


def make_poller(tmp, pulls, state=None, reviews=None):
    cfg = Config(
        bot_token="1:x",
        webhook_secret="s",
        chat_id=-100,
        state_file=tmp / "state.json",
        pr_poll_seconds=90,
    )
    state = state or State()
    forge = FakeForge([REPO], pulls, reviews)
    announced = []

    async def announce(pr):
        announced.append(pr)

    return PRPoller(cfg, forge, state, announce), state, forge, announced


class PollerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    async def test_first_run_seeds_silently(self):
        poller, state, forge, announced = make_poller(self.tmp, {REPO: [pr_json(1), pr_json(2)]})
        await poller._cycle()
        self.assertEqual(announced, [])
        self.assertIsNotNone(state.pr_signature(f"{REPO}#1"))

    async def test_new_pr_after_seed_is_announced_opened(self):
        poller, state, forge, announced = make_poller(self.tmp, {REPO: [pr_json(1)]})
        await poller._cycle()  # seed
        forge.pulls[REPO] = [pr_json(2), pr_json(1)]
        await poller._cycle()
        self.assertEqual(len(announced), 1)
        self.assertEqual(announced[0].number, 2)
        self.assertEqual(announced[0].action, "opened")

    async def test_new_commits_on_pr_announced(self):
        poller, state, forge, announced = make_poller(self.tmp, {REPO: [pr_json(1, head="a" * 40)]})
        await poller._cycle()  # seed
        forge.pulls[REPO] = [pr_json(1, head="b" * 40)]
        await poller._cycle()
        self.assertEqual(len(announced), 1)
        self.assertEqual(announced[0].number, 1)
        self.assertEqual(announced[0].head_sha, "b" * 40)

    async def test_merge_announced(self):
        poller, state, forge, announced = make_poller(self.tmp, {REPO: [pr_json(1)]})
        await poller._cycle()  # seed
        forge.pulls[REPO] = [pr_json(1, state="closed", merged=True)]
        await poller._cycle()
        self.assertEqual(len(announced), 1)
        self.assertTrue(announced[0].merged)
        self.assertEqual(announced[0].action, "closed")

    async def test_draft_open_is_skipped(self):
        poller, state, forge, announced = make_poller(self.tmp, {REPO: [pr_json(1)]})
        await poller._cycle()  # seed
        forge.pulls[REPO] = [pr_json(2, draft=True), pr_json(1)]
        await poller._cycle()
        self.assertEqual(announced, [])  # draft not announced
        self.assertIsNotNone(state.pr_signature(f"{REPO}#2"))  # but tracked

    async def test_approval_announced_on_open_pr(self):
        poller, state, forge, announced = make_poller(self.tmp, {REPO: [pr_json(1)]})
        await poller._cycle()  # seed
        forge.reviews_by_pr[(REPO, 1)] = [
            {"user": {"login": "ek"}, "state": "APPROVED", "submitted_at": "2026-09-14T10:00:00Z"}
        ]
        await poller._cycle()
        self.assertEqual(len(announced), 1)
        self.assertEqual(announced[0].approved_by, ("ek",))
        self.assertEqual(announced[0].changes_by, ())

    async def test_review_change_re_announces(self):
        reviews = {(REPO, 1): [{"user": {"login": "ek"}, "state": "APPROVED", "submitted_at": "2026-09-14T10:00:00Z"}]}
        poller, state, forge, announced = make_poller(self.tmp, {REPO: [pr_json(1)]}, reviews=reviews)
        await poller._cycle()  # seed with an approval already present
        self.assertEqual(announced, [])
        forge.reviews_by_pr[(REPO, 1)] = [
            {"user": {"login": "ek"}, "state": "APPROVED", "submitted_at": "2026-09-14T10:00:00Z"},
            {"user": {"login": "ek"}, "state": "REQUEST_CHANGES", "submitted_at": "2026-09-14T12:00:00Z"},
        ]
        await poller._cycle()
        self.assertEqual(len(announced), 1)
        self.assertEqual(announced[0].approved_by, ())
        self.assertEqual(announced[0].changes_by, ("ek",))

    async def test_restart_does_not_reseed(self):
        poller, state, forge, announced = make_poller(self.tmp, {REPO: [pr_json(1)]})
        await poller._cycle()  # seed
        state.save(self.tmp / "state.json")
        reloaded = State.load(self.tmp / "state.json")
        poller2, state2, forge2, announced2 = make_poller(self.tmp, {REPO: [pr_json(3), pr_json(1)]}, state=reloaded)
        await poller2._cycle()
        self.assertEqual([p.number for p in announced2], [3])
