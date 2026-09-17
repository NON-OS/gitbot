import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from gitbot.config import Config
from gitbot.digest import build_digest, seconds_until

NOW = datetime(2026, 9, 14, 16, 0, tzinfo=timezone.utc)  # a Monday
REPO = "NON-OS/nonos-micro-kernel"


def iso(days_ago):
    return (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


class FakeForge:
    def __init__(self, commits=None, pulls=None, releases=None, repos=None):
        self._commits = commits or {}
        self._pulls = pulls or {}
        self._releases = releases or {}
        self._repos = repos or [REPO]

    async def org_repos(self, org):
        return self._repos

    async def commits(self, full, limit=5):
        return self._commits.get(full, [])

    async def list_pulls(self, full, limit=30):
        return self._pulls.get(full, [])

    async def releases(self, full, limit=1):
        return self._releases.get(full, [])


def cfg():
    return Config(bot_token="1:x", webhook_secret="s", chat_id=-100, state_file=Path("/tmp/x"))


class DigestBuildTests(unittest.IsolatedAsyncioTestCase):
    async def test_counts_only_last_seven_days(self):
        forge = FakeForge(
            commits={
                REPO: [
                    {"commit": {"committer": {"date": iso(1)}}},
                    {"commit": {"committer": {"date": iso(3)}}},
                    {"commit": {"committer": {"date": iso(20)}}},  # too old
                ]
            },
            pulls={
                REPO: [
                    {"number": 37, "title": "i2c core", "merged": True, "merged_at": iso(2)},
                    {"number": 30, "title": "old work", "merged": True, "merged_at": iso(30)},  # too old
                    {"number": 38, "title": "open one", "merged": False, "merged_at": None},
                ]
            },
            releases={REPO: [{"tag_name": "v0.9.2", "published_at": iso(1)}]},
        )
        text = await build_digest(forge, cfg(), now=NOW)
        self.assertIn("<b>1</b> pull request merged", text)
        self.assertIn("<b>2</b> commits across 1 repositor", text)
        self.assertIn("v0.9.2", text)
        self.assertIn("#37", text)
        self.assertNotIn("#30", text)

    async def test_quiet_week(self):
        text = await build_digest(FakeForge(), cfg(), now=NOW)
        self.assertIn("A quiet week.", text)


class ScheduleTests(unittest.TestCase):
    def test_next_sunday_from_monday(self):
        # NOW is Monday 16:00; next Sunday 16:00 is six days out.
        secs = seconds_until(NOW, dow=6, hour=16)
        self.assertAlmostEqual(secs, 6 * 86400, delta=1)

    def test_today_but_hour_passed_rolls_a_week(self):
        # Monday 16:00 asking for Monday 09:00 must jump to next Monday.
        secs = seconds_until(NOW, dow=0, hour=9)
        self.assertAlmostEqual(secs, 7 * 86400 - 7 * 3600, delta=1)

    def test_later_today(self):
        secs = seconds_until(NOW, dow=0, hour=20)
        self.assertAlmostEqual(secs, 4 * 3600, delta=1)
