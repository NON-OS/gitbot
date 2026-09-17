"""The Forgejo webhook receiver.

Verifies the HMAC over the raw request body before parsing anything, drops
duplicate and unsigned deliveries, answers fast, and hands verified events
to the handler. Payloads are never logged; only the delivery id is.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging

from aiohttp import web

from .config import Config
from .handler import Handler
from .health import Health
from .state import State

log = logging.getLogger("gitbot.webhook")

ACCEPTED_EVENTS = {"push", "pull_request", "release"}


def _header(request: web.Request, name: str) -> str:
    return request.headers.get(f"X-Forgejo-{name}") or request.headers.get(f"X-Gitea-{name}") or ""


def verify(secret: bytes, raw_body: bytes, signature: str) -> bool:
    want = hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(want, signature or "")


class Webhook:
    def __init__(self, cfg: Config, handler: Handler, state: State, alerter=None, health: Health | None = None):
        self.cfg = cfg
        self.handler = handler
        self.state = state
        self.alerter = alerter
        self._health = health
        self._secret = cfg.webhook_secret.encode()
        self._sig_fails = 0

    async def handle(self, request: web.Request) -> web.Response:
        delivery = _header(request, "Delivery")
        event = _header(request, "Event")
        raw = await request.read()

        if not verify(self._secret, raw, _header(request, "Signature")):
            self._sig_fails += 1
            log.warning("rejected delivery %s: bad signature (%d in a row)", delivery or "?", self._sig_fails)
            if self.alerter and self._sig_fails >= 5:
                await self.alerter.fault("webhook signatures failing", f"{self._sig_fails} bad signatures in a row")
            return web.Response(status=401)
        self._sig_fails = 0

        if event not in ACCEPTED_EVENTS:
            return web.Response(status=202, text="ignored")

        if self.state.seen(delivery):
            log.info("duplicate delivery %s dropped", delivery)
            return web.Response(status=202, text="duplicate")
        self.state.save(self.cfg.state_file)

        try:
            payload = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            log.warning("delivery %s: body was not valid JSON", delivery or "?")
            return web.Response(status=400)

        try:
            self.handler.dispatch(event, payload)
        except Exception as exc:  # never fail the delivery over a render bug
            log.exception("dispatch failed for delivery %s: %s", delivery or "?", exc)

        return web.Response(status=202, text="ok")

    async def health(self, request: web.Request) -> web.Response:
        if self._health is None:
            return web.Response(text="ok")
        snap = self._health.snapshot()
        return web.json_response(snap, status=200 if snap["ok"] else 503)


def build_app(
    cfg: Config, handler: Handler, state: State, alerter=None, health: Health | None = None
) -> web.Application:
    hook = Webhook(cfg, handler, state, alerter, health)
    app = web.Application()
    app.router.add_post(cfg.webhook_path, hook.handle)
    app.router.add_get("/healthz", hook.health)
    return app
