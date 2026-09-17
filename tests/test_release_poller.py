import tempfile
import unittest
from pathlib import Path

from gitbot.config import Config
from gitbot.forge import release_from_json
from gitbot.handler import Handler
from gitbot.models import Repo
from gitbot.poller import ReleasePoller
from gitbot.state import State

REPO = "NON-OS/nonos-micro-kernel"


def rel_json(tag, draft=False, prerelease=False):
    return {
        "tag_name": tag,
        "name": f"NONOS {tag}",
        "html_url": f"https://git.nonos.software/{REPO}/releases/tag/{tag}",
        "assets": [{"name": "nonos.iso", "size": 36700160}],
        "draft": draft,
        "prerelease": prerelease,
    }


class FakeTelegram:
    def __init__(self):
        self.sent = []

    async def send_text(self, text):
        self.sent.append(text)
        return len(self.sent)

    async def send_photo(self, photo, caption):
        self.sent.append(caption)
        return len(self.sent)


class FakeForge:
    def __init__(self, repos, releases):
        self._repos = repos
        self.releases_by_repo = releases  # repo -> list[dict]

    async def org_repos(self, org):
        return self._repos

    async def releases(self, full, limit=10):
        return self.releases_by_repo.get(full, [])


def make(tmp, releases, state=None):
    cfg = Config(
        bot_token="1:x",
        webhook_secret="s",
        chat_id=-100,
        state_file=tmp / "state.json",
        media_dir=tmp / "media",  # empty, so posts fall back to text
        release_poll_seconds=300,
    )
    state = state or State()
    tg = FakeTelegram()
    forge = FakeForge([REPO], releases)
    handler = Handler(cfg, tg, state, None, forge)
    poller = ReleasePoller(cfg, forge, state, handler.announce_release)
    return poller, handler, state, forge, tg


class ReleasePollerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    async def test_first_run_seeds_silently(self):
        poller, handler, state, forge, tg = make(self.tmp, {REPO: [rel_json("v1")]})
        await poller._cycle()
        self.assertEqual(tg.sent, [])
        self.assertTrue(state.release_seen(REPO, "v1"))  # already recorded

    async def test_new_release_announced(self):
        poller, handler, state, forge, tg = make(self.tmp, {REPO: [rel_json("v1")]})
        await poller._cycle()  # seed
        forge.releases_by_repo[REPO] = [rel_json("v2"), rel_json("v1")]
        await poller._cycle()
        self.assertEqual(len(tg.sent), 1)
        self.assertIn("v2", tg.sent[0])
        self.assertIn("Release published", tg.sent[0])

    async def test_no_reannounce_on_next_cycle(self):
        poller, handler, state, forge, tg = make(self.tmp, {REPO: [rel_json("v1")]})
        await poller._cycle()  # seed
        forge.releases_by_repo[REPO] = [rel_json("v2"), rel_json("v1")]
        await poller._cycle()
        await poller._cycle()
        self.assertEqual(len(tg.sent), 1)

    async def test_draft_never_announced(self):
        poller, handler, state, forge, tg = make(self.tmp, {})
        await poller._cycle()  # seed empty
        forge.releases_by_repo[REPO] = [rel_json("v3", draft=True)]
        await poller._cycle()
        self.assertEqual(tg.sent, [])

    async def test_prerelease_label(self):
        poller, handler, state, forge, tg = make(self.tmp, {})
        await poller._cycle()  # seed empty
        forge.releases_by_repo[REPO] = [rel_json("v4", prerelease=True)]
        await poller._cycle()
        self.assertEqual(len(tg.sent), 1)
        self.assertIn("Pre-release published", tg.sent[0])

    async def test_webhook_and_poller_do_not_double_post(self):
        # A release announced from the webhook path must not be re-posted when
        # the poller later reads the same release from the API.
        state = State()
        _, handler, state, _, tg = make(self.tmp, {}, state=state)
        repo = Repo(REPO, f"https://git.nonos.software/{REPO}", "main", False)
        await handler.announce_release(release_from_json(rel_json("v5"), repo))
        self.assertEqual(len(tg.sent), 1)
        # state now has v5, so a poller built from it is already seeded
        poller = ReleasePoller(
            handler.cfg, FakeForge([REPO], {REPO: [rel_json("v5")]}), state, handler.announce_release
        )
        await poller._cycle()
        self.assertEqual(len(tg.sent), 1)

    async def test_restart_does_not_reseed(self):
        poller, handler, state, forge, tg = make(self.tmp, {REPO: [rel_json("v1")]})
        await poller._cycle()  # seed
        state.save(self.tmp / "state.json")
        reloaded = State.load(self.tmp / "state.json")
        poller2, _, _, forge2, tg2 = make(self.tmp, {REPO: [rel_json("v6"), rel_json("v1")]}, state=reloaded)
        await poller2._cycle()
        self.assertEqual(len(tg2.sent), 1)
        self.assertIn("v6", tg2.sent[0])
