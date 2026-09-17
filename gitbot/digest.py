"""A weekly digest of the forge: pull requests merged, commits landed and
releases cut over the last seven days, read from the forge API and posted on a
schedule. Also available on demand through /digest."""

from __future__ import annotations

import asyncio
import html
import logging
from datetime import datetime, timedelta, timezone

from . import banners
from .config import Config
from .forge import ForgeClient
from .telegram import Telegram

log = logging.getLogger("gitbot.digest")

MAX_LISTED = 10


def _esc(text: str) -> str:
    return html.escape(text or "", quote=False)


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def seconds_until(now: datetime, dow: int, hour: int) -> float:
    """Seconds from now to the next weekday (Mon=0..Sun=6) at hour:00 UTC."""
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    target += timedelta(days=(dow - now.weekday()) % 7)
    if target <= now:
        target += timedelta(days=7)
    return (target - now).total_seconds()


async def build_digest(forge: ForgeClient, cfg: Config, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=7)
    total_commits = 0
    active_repos = 0
    merged: list[tuple[str, int, str]] = []
    releases: list[tuple[str, str]] = []

    for full in await forge.org_repos(cfg.org):
        short = full.split("/")[-1]
        n = 0
        for c in await forge.commits(full, 50):
            cm = c.get("commit", {})
            d = _parse((cm.get("committer") or {}).get("date") or (cm.get("author") or {}).get("date"))
            if d and d >= cutoff:
                n += 1
        if n:
            total_commits += n
            active_repos += 1
        for p in await forge.list_pulls(full, 50):
            md = _parse(p.get("merged_at"))
            if p.get("merged") and md and md >= cutoff:
                merged.append((short, int(p.get("number", 0) or 0), p.get("title", "")))
        for r in await forge.releases(full, 10):
            rd = _parse(r.get("published_at") or r.get("created_at"))
            if rd and rd >= cutoff:
                releases.append((short, r.get("tag_name", "")))

    span = f"{cutoff.strftime('%b %-d')} to {now.strftime('%b %-d')}"
    lines = [f"<b>git.nonos.software this week</b> ({_esc(span)})", ""]
    lines.append(f"🔀 <b>{len(merged)}</b> pull request{'' if len(merged) == 1 else 's'} merged")
    lines.append(
        f"📦 <b>{total_commits}</b> commit{'' if total_commits == 1 else 's'} across {active_repos} "
        f"repositor{'y' if active_repos == 1 else 'ies'}"
    )
    if releases:
        tags = ", ".join(f"{_esc(t)} ({_esc(s)})" for s, t in releases[:MAX_LISTED])
        lines.append(f"🏷 <b>{len(releases)}</b> release{'' if len(releases) == 1 else 's'}: {tags}")
    if merged:
        lines.append("")
        lines.append("<b>Merged</b>")
        from .render import first_line

        for short, number, title in merged[:MAX_LISTED]:
            lines.append(f"· {_esc(short)} #{number} {_esc(first_line(title, 50))}")
        if len(merged) > MAX_LISTED:
            lines.append(f"· and {len(merged) - MAX_LISTED} more")
    if not merged and not total_commits and not releases:
        lines.append("")
        lines.append("A quiet week.")
    return "\n".join(lines)


class DigestScheduler:
    def __init__(self, cfg: Config, forge: ForgeClient, tg: Telegram):
        self.cfg = cfg
        self.forge = forge
        self.tg = tg

    async def run(self) -> None:
        if not self.cfg.digest_enabled:
            log.info("weekly digest disabled")
            return
        log.info("weekly digest on day %d at %02d:00 UTC", self.cfg.digest_dow, self.cfg.digest_hour)
        while True:
            delay = seconds_until(datetime.now(timezone.utc), self.cfg.digest_dow, self.cfg.digest_hour)
            await asyncio.sleep(delay)
            try:
                text = await build_digest(self.forge, self.cfg)
                await self.post(text)
            except Exception as exc:  # keep the schedule alive
                log.error("digest failed: %s", exc)
            await asyncio.sleep(60)  # step past the fire minute before recomputing

    async def post(self, text: str) -> None:
        banner = banners.path(self.cfg.media_dir, banners.DIGEST)
        if banner.is_file():
            await self.tg.send_photo(banner, text)
        else:
            await self.tg.send_text(text)
