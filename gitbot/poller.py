"""Poll the forge for pull request and release changes.

The forge does not fire pull_request or release webhooks for its sync-driven
activity, so the webhook stream only ever carries pushes. These pollers read the
forge API on an interval. The PR poller notices when a pull request opens, gets
new commits, merges or closes, and announces it, editing the one message per
pull request in place. The release poller notices a new release and announces
it. Both learn the current state silently on the first run, so a fresh deploy
does not flood the group with the existing open pull requests and releases.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from .config import Config
from .forge import ForgeClient, pull_from_json, release_from_json
from .health import ALERT_AFTER, Health
from .models import PullRequest, Release, Repo
from .state import State

log = logging.getLogger("gitbot.poll")


def summarize_reviews(reviews: list[dict]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return (approved_by, changes_requested_by) from a PR's reviews, counting
    only each reviewer's most recent decisive review."""
    latest: dict[str, str] = {}
    for r in sorted(reviews, key=lambda x: x.get("submitted_at", "")):
        user = (r.get("user") or {}).get("login", "")
        state = r.get("state", "")
        if user and state in ("APPROVED", "REQUEST_CHANGES"):
            latest[user] = state
    approved = tuple(sorted(u for u, s in latest.items() if s == "APPROVED"))
    changes = tuple(sorted(u for u, s in latest.items() if s == "REQUEST_CHANGES"))
    return approved, changes


class PRPoller:
    NAME = "pr_poll"

    def __init__(
        self,
        cfg: Config,
        forge: ForgeClient,
        state: State,
        announce: Callable[[PullRequest], Awaitable[None]],
        health: Health | None = None,
        alerter=None,
    ):
        self.cfg = cfg
        self.forge = forge
        self.state = state
        self.announce = announce
        self.health = health
        self.alerter = alerter
        self._seeded = bool(state.pr_state)
        if health:
            health.register(self.NAME, cfg.pr_poll_seconds)

    async def run(self) -> None:
        if self.cfg.pr_poll_seconds <= 0:
            log.info("pull request polling disabled")
            return
        log.info(
            "polling pull requests every %ds%s",
            self.cfg.pr_poll_seconds,
            "" if self._seeded else " (first run learns current state silently)",
        )
        while True:
            try:
                await self._cycle()
                if self.health:
                    self.health.ok(self.NAME)
            except Exception as exc:  # keep polling
                log.error("pr poll cycle failed: %s", exc)
                await self._report(exc)
            await asyncio.sleep(self.cfg.pr_poll_seconds)

    async def _report(self, exc: Exception) -> None:
        fails = self.health.fail(self.NAME, str(exc)) if self.health else 0
        if self.alerter and fails >= ALERT_AFTER:
            await self.alerter.fault("pull request polling failing", f"{fails} cycles in a row: {exc}")

    async def _cycle(self) -> None:
        for full in await self.forge.org_repos(self.cfg.org):
            await self._poll_repo(full)
        self._seeded = True

    async def _poll_repo(self, full: str) -> None:
        pulls = await self.forge.list_pulls(full)
        if not pulls:
            return
        repo = Repo(full, f"{self.cfg.forge_base}/{full}", "main", False)
        changed = False
        for data in pulls:
            pr = pull_from_json(data, repo)
            if not pr.number:
                continue
            if self.cfg.reviews_enabled and pr.state == "open":
                pr.approved_by, pr.changes_by = summarize_reviews(await self.forge.reviews(full, pr.number))
            key = self.state.pr_key(full, pr.number)
            signature = f"{pr.state}:{pr.merged}:{pr.head_sha}:a={','.join(pr.approved_by)}:c={','.join(pr.changes_by)}"
            if self.state.pr_signature(key) == signature:
                continue
            first_seen = self.state.pr_signature(key) is None
            self.state.set_pr_signature(key, signature)
            changed = True
            if not self._seeded:
                continue
            if first_seen and pr.state == "open" and pr.is_draft and self.cfg.skip_drafts:
                continue
            log.info("pull request %s #%s changed: %s", full, pr.number, signature)
            await self.announce(pr)
        if changed:
            self.state.save(self.cfg.state_file)


class ReleasePoller:
    NAME = "release_poll"

    def __init__(
        self,
        cfg: Config,
        forge: ForgeClient,
        state: State,
        announce: Callable[[Release], Awaitable[None]],
        health: Health | None = None,
        alerter=None,
    ):
        self.cfg = cfg
        self.forge = forge
        self.state = state
        self.announce = announce
        self.health = health
        self.alerter = alerter
        self._seeded = bool(state.releases)
        if health:
            health.register(self.NAME, cfg.release_poll_seconds)

    async def run(self) -> None:
        if self.cfg.release_poll_seconds <= 0:
            log.info("release polling disabled")
            return
        log.info(
            "polling releases every %ds%s",
            self.cfg.release_poll_seconds,
            "" if self._seeded else " (first run learns current state silently)",
        )
        while True:
            try:
                await self._cycle()
                if self.health:
                    self.health.ok(self.NAME)
            except Exception as exc:  # keep polling
                log.error("release poll cycle failed: %s", exc)
                await self._report(exc)
            await asyncio.sleep(self.cfg.release_poll_seconds)

    async def _report(self, exc: Exception) -> None:
        fails = self.health.fail(self.NAME, str(exc)) if self.health else 0
        if self.alerter and fails >= ALERT_AFTER:
            await self.alerter.fault("release polling failing", f"{fails} cycles in a row: {exc}")

    async def _cycle(self) -> None:
        for full in await self.forge.org_repos(self.cfg.org):
            await self._poll_repo(full)
        self._seeded = True

    async def _poll_repo(self, full: str) -> None:
        repo = Repo(full, f"{self.cfg.forge_base}/{full}", "main", False)
        seeding = not self._seeded
        for data in await self.forge.releases(full, 10):
            release = release_from_json(data, repo)
            if not release.tag_name or release.draft:
                continue
            if seeding:
                # Learn the current releases without posting them; the dedup is
                # shared, so announce() below would otherwise fire on the backlog.
                self.state.release_seen(full, release.tag_name)
                continue
            # announce() dedups against the shared state and posts only what is
            # genuinely new, so old releases here are a cheap no-op.
            await self.announce(release)
        if seeding:
            self.state.save(self.cfg.state_file)
