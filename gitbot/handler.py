"""Turn a verified webhook into Telegram work: decide, render, enqueue.

Commit pushes are held briefly and coalesced per branch by the batcher, so a
burst becomes one message. A new repository is announced once. A push that
carries a merge commit is read as a merged pull request, not as generic
commits, because merges done on GitHub reach the forge as a push rather than
a pull_request event. Pull requests and releases post immediately, and a pull
request stays one message whose banner and caption change together as it
opens, merges or closes. An event whose banner is not present yet falls back
to a plain text message rather than failing.
"""

from __future__ import annotations

import logging

from . import banners, events, filters, merges, models, render
from .authors import SyncSummary
from .batcher import CommitBatcher, merge
from .config import Config
from .forge import ForgeClient, pull_from_json
from .state import State
from .telegram import Telegram

log = logging.getLogger("gitbot.handler")


class Handler:
    def __init__(self, cfg: Config, tg: Telegram, state: State, summary: SyncSummary, forge: ForgeClient):
        self.cfg = cfg
        self.tg = tg
        self.state = state
        self.summary = summary
        self.forge = forge
        self.batcher = CommitBatcher(cfg.batch_seconds, self._flush_commits)

    def dispatch(self, event_type: str, payload: dict) -> None:
        if event_type == "push":
            self._push(events.parse_push(payload))
        elif event_type == "pull_request":
            self._pull_request(events.parse_pull_request(payload))
        elif event_type == "release":
            self._release(events.parse_release(payload))
        else:
            log.debug("dropping event type %s", event_type)

    def _banner(self, name: str):
        return banners.path(self.cfg.media_dir, name)

    def _post_banner(self, banner_name: str, text: str) -> None:
        banner = self._banner(banner_name)
        if banner.is_file():
            self.tg.enqueue(lambda: self.tg.send_photo(banner, text))
        else:
            log.info("banner %s not present, posting as text", banner_name)
            self.tg.enqueue(lambda: self.tg.send_text(text))

    def _push(self, push: models.Push) -> None:
        decision, reason = filters.decide_push(push)
        log.info("push %s %s: %s (%s)", push.repo.full_name, push.branch, decision, reason)
        if decision == filters.SKIP:
            return
        if decision == filters.REPO:
            self._post_banner(banners.REPO_NEW, render.render_repo_new(push))
            return
        if push.is_tag:
            text = render.render_push(push, self.cfg.max_commits, self.cfg.summary_chars)
            self.tg.enqueue(lambda: self.tg.send_text(text))
            return
        pr_numbers = merges.pr_numbers(push.commits)
        if pr_numbers:
            self.tg.enqueue(lambda: self._handle_merge_push(push, pr_numbers))
            return
        self.batcher.add(push)

    def _flush_commits(self, pushes: list[models.Push]) -> None:
        merged = merge(pushes)
        text = render.render_push(merged, self.cfg.max_commits, self.cfg.summary_chars)
        self._post_banner(banners.COMMITS, text)

    async def _handle_merge_push(self, push: models.Push, pr_numbers: list[int]) -> None:
        """A default-branch push that names pull requests: confirm each is
        merged, announce it, and edit its message in place. If none turn out
        to be merged, the references were incidental and it is a normal push."""
        merged_any = False
        for number in pr_numbers:
            data = await self.forge.pull(push.repo.full_name, number)
            if not data or not data.get("merged"):
                continue
            merged_any = True
            await self.announce_pr(pull_from_json(data, push.repo))
        if not merged_any:
            text = render.render_push(push, self.cfg.max_commits, self.cfg.summary_chars)
            banner = self._banner(banners.COMMITS)
            if banner.is_file():
                await self.tg.send_photo(banner, text)
            else:
                await self.tg.send_text(text)

    async def announce_pr(self, pr: models.PullRequest) -> None:
        """Post a pull request once, then edit that message in place as it
        updates, merges or closes. Shared by the merge path and the poller."""
        author = await self.summary.author_for(pr)
        text = render.render_pull_request(pr, author)
        banner = self._banner(banners.for_pull_request(pr))
        existing = self.state.pr_message(pr.repo.full_name, pr.number)
        if existing:
            await self.tg.edit_media(existing, banner, text)
            return
        if banner.is_file():
            message_id = await self.tg.send_photo(banner, text)
        else:
            message_id = await self.tg.send_text(text)
        self.state.remember_pr(pr.repo.full_name, pr.number, message_id)
        self.state.save(self.cfg.state_file)

    def _pull_request(self, pr: models.PullRequest) -> None:
        decision, reason = filters.decide_pull_request(pr, self.cfg.skip_drafts)
        log.info("pull_request %s #%s %s: %s (%s)", pr.repo.full_name, pr.number, pr.action, decision, reason)
        if decision == filters.SKIP:
            return

        async def job() -> None:
            author = await self.summary.author_for(pr)
            text = render.render_pull_request(pr, author)
            banner = self._banner(banners.for_pull_request(pr))
            existing = self.state.pr_message(pr.repo.full_name, pr.number)
            if existing:
                await self.tg.edit_media(existing, banner, text)
                return
            if decision == filters.EDIT:
                log.info("no stored message for %s #%s; posting fresh", pr.repo.full_name, pr.number)
            message_id = await self.tg.send_photo(banner, text)
            self.state.remember_pr(pr.repo.full_name, pr.number, message_id)
            self.state.save(self.cfg.state_file)

        self.tg.enqueue(job)

    def _release(self, release: models.Release) -> None:
        decision, reason = filters.decide_release(release)
        log.info("release %s %s: %s (%s)", release.repo.full_name, release.tag_name, decision, reason)
        if decision != filters.POST:
            return
        self.tg.enqueue(lambda: self.announce_release(release))

    async def announce_release(self, release: models.Release) -> None:
        """Post a release once. The dedup is shared with the poller through the
        state, so a release announced from a webhook is never re-posted when the
        poller later reads it from the API, and the other way round."""
        if not release.tag_name or self.state.release_seen(release.repo.full_name, release.tag_name):
            return
        self.state.save(self.cfg.state_file)
        text = render.render_release(release)
        banner = self._banner(banners.RELEASE)
        if banner.is_file():
            await self.tg.send_photo(banner, text)
        else:
            await self.tg.send_text(text)
