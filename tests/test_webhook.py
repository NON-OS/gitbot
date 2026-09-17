import hashlib
import hmac
import json
import tempfile
import unittest
from pathlib import Path

from gitbot.config import Config
from gitbot.handler import Handler
from gitbot.health import Health
from gitbot.state import State
from gitbot.webhook import Webhook, verify
from tests import fixtures

SECRET = "topsecret-value"


class FakeTelegram:
    def __init__(self):
        self.jobs = []
        self.sent = []  # photo messages: (message_id, caption)
        self.sent_text = []  # plain messages (tags): (message_id, text)
        self.edited = []  # edit_media: (message_id, caption)
        self._next = 100

    def enqueue(self, job):
        self.jobs.append(job)

    async def run_jobs(self):
        while self.jobs:
            await self.jobs.pop(0)()

    async def send_photo(self, photo, caption):
        self._next += 1
        self.sent.append((self._next, caption))
        return self._next

    async def edit_media(self, message_id, photo, caption):
        self.edited.append((message_id, caption))

    async def send_text(self, text):
        self._next += 1
        self.sent_text.append((self._next, text))
        return self._next


class FakeSummary:
    async def author_for(self, pr):
        return "eKisNonos"


class FakeForge:
    def __init__(self, pulls=None):
        self.pulls = pulls or {}  # number -> forge PR json, or None

    async def pull(self, repo_full_name, number):
        return self.pulls.get(number)


def merged_pr_json(number=12, title="A vault the wallet keeps", merged=True):
    return {
        "number": number,
        "title": title,
        "html_url": f"https://git.nonos.software/NON-OS/nonos-micro-kernel/pulls/{number}",
        "state": "closed",
        "merged": merged,
        "base": {"ref": "main"},
        "head": {"label": "eKisNonos/nonos-micro-kernel:gh-485"},
        "body": "Opened on GitHub by eKisNonos as pull request 485.",
        "user": {"login": "nonos-sync"},
    }


class FakeRequest:
    def __init__(self, headers, body):
        self.headers = headers
        self._body = body

    async def read(self):
        return self._body


def sign(secret, body):
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def make_request(event, payload, delivery="d1", signature=None, delivery_hdr=True):
    body = json.dumps(payload).encode()
    headers = {
        "X-Forgejo-Event": event,
        "X-Forgejo-Signature": signature if signature is not None else sign(SECRET, body),
    }
    if delivery_hdr:
        headers["X-Forgejo-Delivery"] = delivery
    return FakeRequest(headers, body)


class WebhookTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.cfg = Config(
            bot_token="1:x",
            webhook_secret=SECRET,
            chat_id=-100123,
            state_file=Path(self.dir.name) / "state.json",
            batch_seconds=0,  # flush commit pushes immediately in tests
        )
        self.state = State()
        self.tg = FakeTelegram()
        self.forge = FakeForge()
        self.handler = Handler(self.cfg, self.tg, self.state, FakeSummary(), self.forge)
        self.hook = Webhook(self.cfg, self.handler, self.state)

    def tearDown(self):
        self.dir.cleanup()

    async def test_bad_signature_rejected(self):
        resp = await self.hook.handle(make_request("push", fixtures.push(), signature="deadbeef"))
        self.assertEqual(resp.status, 401)
        self.assertEqual(self.tg.jobs, [])

    async def test_raw_body_signature_survives_key_reordering(self):
        # A signature over the exact bytes must verify even though re-dumping
        # the parsed dict would reorder keys and change the digest.
        payload = fixtures.push()
        body = json.dumps(payload, sort_keys=True).encode()
        req = FakeRequest(
            {"X-Forgejo-Event": "push", "X-Forgejo-Delivery": "raw1", "X-Forgejo-Signature": sign(SECRET, body)},
            body,
        )
        resp = await self.hook.handle(req)
        self.assertEqual(resp.status, 202)

    async def test_valid_push_enqueues_and_sends(self):
        resp = await self.hook.handle(make_request("push", fixtures.push()))
        self.assertEqual(resp.status, 202)
        await self.tg.run_jobs()
        self.assertEqual(len(self.tg.sent), 1)
        self.assertIn("nonos-micro-kernel", self.tg.sent[0][1])
        self.assertNotIn("nonos-sync", self.tg.sent[0][1])

    async def test_duplicate_delivery_dropped(self):
        await self.hook.handle(make_request("push", fixtures.push(), delivery="dup"))
        resp = await self.hook.handle(make_request("push", fixtures.push(), delivery="dup"))
        self.assertEqual(resp.status, 202)
        await self.tg.run_jobs()
        self.assertEqual(len(self.tg.sent), 1)

    async def test_gitea_twin_headers_accepted(self):
        body = json.dumps(fixtures.push()).encode()
        req = FakeRequest(
            {"X-Gitea-Event": "push", "X-Gitea-Delivery": "g1", "X-Gitea-Signature": sign(SECRET, body)},
            body,
        )
        resp = await self.hook.handle(req)
        self.assertEqual(resp.status, 202)
        await self.tg.run_jobs()
        self.assertEqual(len(self.tg.sent), 1)

    async def test_non_default_branch_no_send(self):
        resp = await self.hook.handle(make_request("push", fixtures.push(ref="refs/heads/feature")))
        self.assertEqual(resp.status, 202)
        await self.tg.run_jobs()
        self.assertEqual(self.tg.sent, [])

    async def test_unaccepted_event_ignored(self):
        resp = await self.hook.handle(make_request("issues", {"action": "opened"}))
        self.assertEqual(resp.status, 202)
        self.assertEqual(self.tg.jobs, [])

    async def test_bad_json_400(self):
        body = b"{not json"
        req = FakeRequest(
            {"X-Forgejo-Event": "push", "X-Forgejo-Delivery": "dj", "X-Forgejo-Signature": sign(SECRET, body)},
            body,
        )
        resp = await self.hook.handle(req)
        self.assertEqual(resp.status, 400)

    async def test_pr_open_then_merge_edits_same_message(self):
        await self.hook.handle(
            make_request("pull_request", fixtures.pull_request(action="opened", number=12), delivery="o12")
        )
        await self.tg.run_jobs()
        self.assertEqual(len(self.tg.sent), 1)
        message_id = self.tg.sent[0][0]

        await self.hook.handle(
            make_request("pull_request", fixtures.pull_request(action="closed", merged=True, number=12), delivery="m12")
        )
        await self.tg.run_jobs()
        self.assertEqual(len(self.tg.sent), 1)
        self.assertEqual(len(self.tg.edited), 1)
        self.assertEqual(self.tg.edited[0][0], message_id)
        self.assertIn("merged", self.tg.edited[0][1].lower())

    async def test_pr_sync_without_prior_open_posts_fresh(self):
        await self.hook.handle(
            make_request("pull_request", fixtures.pull_request(action="synchronized", number=99), delivery="s99")
        )
        await self.tg.run_jobs()
        self.assertEqual(len(self.tg.sent), 1)
        self.assertEqual(self.tg.edited, [])

    async def test_tag_push_is_plain_text_not_photo(self):
        await self.hook.handle(make_request("push", fixtures.push(ref="refs/tags/v0.9.2", commits=[]), delivery="tag1"))
        await self.tg.run_jobs()
        self.assertEqual(self.tg.sent, [])
        self.assertEqual(len(self.tg.sent_text), 1)
        self.assertIn("v0.9.2", self.tg.sent_text[0][1])

    async def test_release_posts_photo(self):
        await self.hook.handle(make_request("release", fixtures.release(), delivery="rel1"))
        await self.tg.run_jobs()
        self.assertEqual(len(self.tg.sent), 1)
        self.assertIn("Release published", self.tg.sent[0][1])

    async def test_merge_commit_push_reads_as_merged_pr(self):
        self.forge.pulls = {12: merged_pr_json(12)}
        push = fixtures.push(commits=[fixtures.commit("Merge pull request #12 from eKisNonos/vault")])
        await self.hook.handle(make_request("push", push, delivery="merge12"))
        await self.tg.run_jobs()
        self.assertEqual(len(self.tg.sent), 1)
        caption = self.tg.sent[0][1]
        self.assertIn("Pull request merged", caption)
        self.assertIn("#12", caption)
        self.assertNotIn("commits by", caption)

    async def test_merge_edits_existing_pr_message(self):
        self.state.remember_pr("NON-OS/nonos-micro-kernel", 12, 777)
        self.forge.pulls = {12: merged_pr_json(12)}
        push = fixtures.push(commits=[fixtures.commit("Merge pull request #12 from eKisNonos/vault")])
        await self.hook.handle(make_request("push", push, delivery="merge12b"))
        await self.tg.run_jobs()
        self.assertEqual(self.tg.sent, [])  # no new message
        self.assertEqual(len(self.tg.edited), 1)  # edited in place
        self.assertEqual(self.tg.edited[0][0], 777)
        self.assertIn("merged", self.tg.edited[0][1].lower())

    async def test_squash_reference_not_merged_falls_back_to_commits(self):
        self.forge.pulls = {99: None}  # forge says: not a merged PR
        push = fixtures.push(commits=[fixtures.commit("fix a thing (#99)")])
        await self.hook.handle(make_request("push", push, delivery="ref99"))
        await self.tg.run_jobs()
        self.assertEqual(len(self.tg.sent), 1)
        self.assertIn("commit by", self.tg.sent[0][1])
        self.assertNotIn("Pull request merged", self.tg.sent[0][1])

    async def test_two_merges_in_one_push_both_announced(self):
        self.forge.pulls = {12: merged_pr_json(12), 13: merged_pr_json(13, title="Second")}
        push = fixtures.push(
            commits=[
                fixtures.commit("Merge pull request #12 from a/b"),
                fixtures.commit("Merge pull request #13 from c/d"),
            ]
        )
        await self.hook.handle(make_request("push", push, delivery="merge2"))
        await self.tg.run_jobs()
        self.assertEqual(len(self.tg.sent), 2)
        self.assertTrue(all("Pull request merged" in c for _, c in self.tg.sent))

    async def test_new_repository_announced_once(self):
        first_push = fixtures.push(before=fixtures.ZERO)  # new default branch with commits
        await self.hook.handle(make_request("push", first_push, delivery="new1"))
        await self.tg.run_jobs()
        # banner-repo-new.png is not shipped yet, so it falls back to text.
        posted = self.tg.sent + self.tg.sent_text
        self.assertEqual(len(posted), 1)
        self.assertIn("New repository", posted[0][1])


class HealthEndpoint(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.cfg = Config(
            bot_token="1:x",
            webhook_secret=SECRET,
            chat_id=-100123,
            state_file=Path(self.dir.name) / "state.json",
        )
        self.handler = Handler(self.cfg, FakeTelegram(), State(), FakeSummary(), FakeForge())

    def tearDown(self):
        self.dir.cleanup()

    async def test_plain_ok_without_health(self):
        hook = Webhook(self.cfg, self.handler, State())
        resp = await hook.health(FakeRequest({}, b""))
        self.assertEqual(resp.status, 200)

    async def test_json_200_when_fresh(self):
        health = Health()
        health.register("pr_poll", 90)
        health.ok("pr_poll")
        hook = Webhook(self.cfg, self.handler, State(), health=health)
        resp = await hook.health(FakeRequest({}, b""))
        self.assertEqual(resp.status, 200)
        self.assertIn(b'"ok": true', resp.body)

    async def test_json_503_when_stale(self):
        health = Health()
        health.register("pr_poll", 1)  # a 1s interval goes stale almost at once
        health.started_at -= 100
        for c in health._components.values():
            c.started -= 100
        hook = Webhook(self.cfg, self.handler, State(), health=health)
        resp = await hook.health(FakeRequest({}, b""))
        self.assertEqual(resp.status, 503)


class VerifyUnit(unittest.TestCase):
    def test_hmac_matches(self):
        body = b'{"a":1}'
        self.assertTrue(verify(SECRET.encode(), body, sign(SECRET, body)))
        self.assertFalse(verify(SECRET.encode(), body, "00"))
        self.assertFalse(verify(SECRET.encode(), body, ""))
