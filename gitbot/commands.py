"""Read-only group commands, answered from the forge API.

The bot is otherwise one-way. This lets anyone in the group ask what is open
or what just landed: /prs, /latest, /repo, /status, /help. Commands are
answered only in the configured chat or a private chat, rate limited per chat,
and never change anything.
"""

from __future__ import annotations

import html
import logging
import time

from .config import Config
from .digest import build_digest
from .forge import ForgeClient
from .health import Health
from .render import first_line
from .telegram import Telegram

log = logging.getLogger("gitbot.cmd")

COOLDOWN = 3.0
MAX_ROWS = 15
UPDATES_TIMEOUT = 25

HELP = (
    "<b>git.nonos.software</b>\n"
    "/prs [repo] - open pull requests\n"
    "/latest &lt;repo&gt; - recent commits on the default branch\n"
    "/repo &lt;repo&gt; - repository summary\n"
    "/repos - repositories being watched\n"
    "/digest - what landed this week\n"
    "/status - bot health"
)


def _esc(text: str) -> str:
    return html.escape(text or "", quote=False)


class CommandLoop:
    NAME = "commands"

    def __init__(
        self,
        cfg: Config,
        tg: Telegram,
        forge: ForgeClient,
        started_at: float,
        health: Health | None = None,
    ):
        self.cfg = cfg
        self.tg = tg
        self.forge = forge
        self.started_at = started_at
        self.health = health
        self.bot_username = ""
        self._last: dict[int, float] = {}
        if health:
            health.register(self.NAME, UPDATES_TIMEOUT)

    async def run(self) -> None:
        if not self.cfg.commands_enabled:
            log.info("group commands disabled")
            return
        me = await self.tg.me()
        self.bot_username = me.get("username", "")
        await self.tg.delete_webhook()
        log.info("group commands enabled as @%s", self.bot_username)
        offset = 0
        while True:
            updates = await self.tg.get_updates(offset, UPDATES_TIMEOUT)
            if self.health:
                self.health.ok(self.NAME)  # the long poll returned, the loop is alive
            for upd in updates:
                offset = upd["update_id"] + 1
                msg = upd.get("message")
                if not msg:
                    continue
                try:
                    await self._handle(msg)
                except Exception as exc:  # never let one command kill the loop
                    log.warning("command failed: %s", exc)

    async def _handle(self, msg: dict) -> None:
        text = msg.get("text") or ""
        if not text.startswith("/"):
            return
        chat_id = int(msg["chat"]["id"])
        if chat_id != self.cfg.chat_id and msg["chat"].get("type") != "private":
            return
        first, *args = text.split()
        name, _, addressed = first.partition("@")
        if addressed and self.bot_username and addressed.lower() != self.bot_username.lower():
            return
        name = name.lower()
        handler = getattr(self, "cmd_" + name[1:], None) if name[1:].isalnum() else None
        if handler is None:
            return
        now = time.monotonic()
        if now - self._last.get(chat_id, -COOLDOWN) < COOLDOWN:
            return
        self._last[chat_id] = now
        reply = await handler(args)
        if reply:
            await self.tg.reply(chat_id, reply)

    async def _resolve(self, args: list[str]) -> str | None:
        return await self.forge.resolve_repo(self.cfg.org, args[0]) if args else None

    def _short(self, full: str) -> str:
        return full.split("/")[-1]

    async def cmd_help(self, args):
        return HELP

    async def cmd_start(self, args):
        return HELP

    async def cmd_status(self, args):
        up = int(time.monotonic() - self.started_at)
        repos = await self.forge.org_repos(self.cfg.org)
        lines = [
            "<b>git bot</b>",
            f"up {up // 3600}h {(up % 3600) // 60}m",
            f"watching {len(repos)} repositories",
        ]
        if self.health:
            snap = self.health.snapshot()
            for name, c in snap["components"].items():
                mark = "🟢" if c["ok"] else "🔴"
                age = c["last_ok_age_seconds"]
                when = "no cycle yet" if age is None else f"{age}s ago"
                lines.append(f"{mark} {_esc(name)}: {when}")
        else:
            lines.append(f"polling every {int(self.cfg.pr_poll_seconds)}s")
        return "\n".join(lines)

    async def cmd_repos(self, args):
        repos = await self.forge.org_repos(self.cfg.org)
        if not repos:
            return "No repositories found."
        lines = [f"<b>Watching {len(repos)} repositories</b>"]
        for full in sorted(repos)[:MAX_ROWS]:
            lines.append(f"· {_esc(self._short(full))}")
        if len(repos) > MAX_ROWS:
            lines.append(f"· and {len(repos) - MAX_ROWS} more")
        return "\n".join(lines)

    async def cmd_prs(self, args):
        if args:
            full = await self._resolve(args)
            if not full:
                return f"No repository matching {_esc(args[0])}."
            pulls = await self.forge.open_pulls(full, MAX_ROWS)
            if not pulls:
                return f"No open pull requests in {_esc(self._short(full))}."
            lines = [f"<b>Open pull requests · {_esc(self._short(full))}</b>"]
            for p in pulls[:MAX_ROWS]:
                lines.append(
                    f"#{p['number']} {_esc(first_line(p.get('title', ''), 60))} · "
                    f'<a href="{p.get("html_url", "")}">open</a>'
                )
            return "\n".join(lines)
        lines = ["<b>Open pull requests</b>"]
        total = 0
        for full in await self.forge.org_repos(self.cfg.org):
            for p in await self.forge.open_pulls(full, 20):
                lines.append(f"{_esc(self._short(full))} #{p['number']} {_esc(first_line(p.get('title', ''), 45))}")
                total += 1
                if total >= MAX_ROWS:
                    break
            if total >= MAX_ROWS:
                break
        return "\n".join(lines) if total else "No open pull requests."

    async def cmd_latest(self, args):
        full = await self._resolve(args)
        if not args:
            return "Usage: /latest &lt;repo&gt;"
        if not full:
            return f"No repository matching {_esc(args[0])}."
        commits = await self.forge.commits(full, 5)
        if not commits:
            return f"No commits found for {_esc(self._short(full))}."
        lines = [f"<b>Latest on {_esc(self._short(full))}</b>"]
        for c in commits:
            cm = c.get("commit", {})
            who = (c.get("author") or {}).get("login") or cm.get("author", {}).get("name", "")
            lines.append(f"· {_esc(first_line(cm.get('message', ''), 60))} <i>{_esc(who)}</i>")
        url = f"{self.cfg.forge_base}/{full}"
        lines.append(f'<a href="{url}">{_esc(url)}</a>')
        return "\n".join(lines)

    async def cmd_digest(self, args):
        return await build_digest(self.forge, self.cfg)

    async def cmd_repo(self, args):
        full = await self._resolve(args)
        if not args:
            return "Usage: /repo &lt;name&gt;"
        if not full:
            return f"No repository matching {_esc(args[0])}."
        r = await self.forge.repo(full)
        if not r:
            return f"Could not read {_esc(full)}."
        pulls = await self.forge.open_pulls(full, 50)
        rels = await self.forge.releases(full, 1)
        lines = [f"<b>{_esc(full)}</b>"]
        if r.get("description"):
            lines.append(_esc(r["description"]))
        lines.append(f"default branch: {_esc(r.get('default_branch', 'main'))}")
        lines.append(f"open pull requests: {len(pulls)}")
        if rels:
            lines.append(f"latest release: {_esc(rels[0].get('tag_name', ''))}")
        lines.append(f'<a href="{r.get("html_url", "")}">{_esc(r.get("html_url", ""))}</a>')
        return "\n".join(lines)
