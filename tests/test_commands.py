import time
import unittest
from pathlib import Path

from gitbot.commands import CommandLoop
from gitbot.config import Config
from gitbot.health import Health

CHAT = -1002548279653
REPO = "NON-OS/nonos-micro-kernel"


class FakeTelegram:
    def __init__(self):
        self.replies = []

    async def me(self):
        return {"username": "NOXGitbot", "id": 8931359604}

    async def delete_webhook(self):
        pass

    async def reply(self, chat_id, text):
        self.replies.append((chat_id, text))
        return len(self.replies)


class FakeForge:
    def __init__(self):
        self.repos = [REPO, "NON-OS/BuyBot"]
        self.pulls = {REPO: [{"number": 37, "title": "i2c core", "html_url": "u/37"}]}
        self._commits = {
            REPO: [
                {
                    "commit": {"message": "fix a thing\n\nbody", "author": {"name": "eK"}},
                    "author": {"login": "eKisNonos"},
                    "sha": "abc123",
                }
            ]
        }

    async def org_repos(self, org):
        return self.repos

    async def resolve_repo(self, org, name):
        n = name.lower()
        for f in self.repos:
            if f.split("/")[-1].lower() == n:
                return f
        return None

    async def open_pulls(self, full, limit=20):
        return self.pulls.get(full, [])

    async def list_pulls(self, full, limit=30):
        return []

    async def commits(self, full, limit=5):
        return self._commits.get(full, [])

    async def repo(self, full):
        return {"description": "the kernel", "default_branch": "main", "html_url": f"https://git.nonos.software/{full}"}

    async def releases(self, full, limit=1):
        return [{"tag_name": "v0.9.2"}]


def make_loop(health=None):
    cfg = Config(bot_token="1:x", webhook_secret="s", chat_id=CHAT, state_file=Path("/tmp/x"))
    tg = FakeTelegram()
    loop = CommandLoop(cfg, tg, FakeForge(), time.monotonic(), health)
    loop.bot_username = "NOXGitbot"
    return loop, tg


def msg(text, chat=CHAT, chat_type="supergroup"):
    return {"chat": {"id": chat, "type": chat_type}, "text": text}


class CommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_help(self):
        loop, tg = make_loop()
        await loop._handle(msg("/help"))
        self.assertIn("git.nonos.software", tg.replies[0][1])

    async def test_prs_for_repo(self):
        loop, tg = make_loop()
        await loop._handle(msg("/prs nonos-micro-kernel"))
        self.assertIn("#37", tg.replies[0][1])
        self.assertIn("i2c core", tg.replies[0][1])

    async def test_prs_unknown_repo(self):
        loop, tg = make_loop()
        await loop._handle(msg("/prs nope"))
        self.assertIn("No repository matching", tg.replies[0][1])

    async def test_latest(self):
        loop, tg = make_loop()
        await loop._handle(msg("/latest nonos-micro-kernel"))
        self.assertIn("fix a thing", tg.replies[0][1])
        self.assertIn("eKisNonos", tg.replies[0][1])

    async def test_repo_summary(self):
        loop, tg = make_loop()
        await loop._handle(msg("/repo nonos-micro-kernel"))
        body = tg.replies[0][1]
        self.assertIn("default branch: main", body)
        self.assertIn("v0.9.2", body)

    async def test_non_command_ignored(self):
        loop, tg = make_loop()
        await loop._handle(msg("hello there"))
        self.assertEqual(tg.replies, [])

    async def test_other_group_ignored(self):
        loop, tg = make_loop()
        await loop._handle(msg("/prs", chat=-100999))
        self.assertEqual(tg.replies, [])

    async def test_addressed_to_other_bot_ignored(self):
        loop, tg = make_loop()
        await loop._handle(msg("/prs@otherbot"))
        self.assertEqual(tg.replies, [])

    async def test_rate_limited(self):
        loop, tg = make_loop()
        await loop._handle(msg("/help"))
        await loop._handle(msg("/help"))
        self.assertEqual(len(tg.replies), 1)

    async def test_unknown_command_silent(self):
        loop, tg = make_loop()
        await loop._handle(msg("/frobnicate"))
        self.assertEqual(tg.replies, [])

    async def test_digest(self):
        loop, tg = make_loop()
        await loop._handle(msg("/digest"))
        self.assertIn("this week", tg.replies[0][1])

    async def test_repos(self):
        loop, tg = make_loop()
        await loop._handle(msg("/repos"))
        body = tg.replies[0][1]
        self.assertIn("Watching 2 repositories", body)
        self.assertIn("nonos-micro-kernel", body)
        self.assertIn("BuyBot", body)

    async def test_status_without_health(self):
        loop, tg = make_loop()
        await loop._handle(msg("/status"))
        self.assertIn("watching 2 repositories", tg.replies[0][1])

    async def test_status_with_health(self):
        health = Health()
        health.register("pr_poll", 90)
        health.ok("pr_poll")
        loop, tg = make_loop(health)
        await loop._handle(msg("/status"))
        body = tg.replies[0][1]
        self.assertIn("pr_poll", body)
        self.assertIn("🟢", body)
