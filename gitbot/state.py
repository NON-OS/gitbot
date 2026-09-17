"""Durable state: the ring of seen delivery ids for dedup, and the map from
a pull request to the Telegram message posted for it so later updates edit
in place. Written atomically at mode 600."""

from __future__ import annotations

import json
import logging
import os
from collections import OrderedDict
from pathlib import Path
from typing import Any

log = logging.getLogger("gitbot.state")

MAX_DELIVERIES = 5000
MAX_PR_MESSAGES = 2000
MAX_PR_STATE = 2000
MAX_RELEASES = 1000


class State:
    def __init__(self) -> None:
        self.deliveries: OrderedDict[str, bool] = OrderedDict()
        self.pr_messages: OrderedDict[str, int] = OrderedDict()
        # repo#number -> "state:merged:head_sha", so the poller sees what changed
        self.pr_state: OrderedDict[str, str] = OrderedDict()
        # repo@tag of a release already announced, so the webhook and the poller
        # never post the same release twice
        self.releases: OrderedDict[str, bool] = OrderedDict()

    @staticmethod
    def pr_key(repo_full_name: str, number: int) -> str:
        return f"{repo_full_name}#{number}"

    @staticmethod
    def release_key(repo_full_name: str, tag: str) -> str:
        return f"{repo_full_name}@{tag}"

    @classmethod
    def load(cls, path: Path) -> State:
        st = cls()
        if not path.exists():
            return st
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.error("unreadable state file %s (%s); starting fresh", path, exc)
            return st
        for did in list(raw.get("deliveries", []))[-MAX_DELIVERIES:]:
            st.deliveries[str(did)] = True
        for key, mid in dict(raw.get("pr_messages", {})).items():
            try:
                st.pr_messages[str(key)] = int(mid)
            except (TypeError, ValueError):
                continue
        for key, sig in dict(raw.get("pr_state", {})).items():
            st.pr_state[str(key)] = str(sig)
        for key in list(raw.get("releases", []))[-MAX_RELEASES:]:
            st.releases[str(key)] = True
        return st

    def save(self, path: Path) -> None:
        data: dict[str, Any] = {
            "deliveries": list(self.deliveries.keys())[-MAX_DELIVERIES:],
            "pr_messages": dict(list(self.pr_messages.items())[-MAX_PR_MESSAGES:]),
            "pr_state": dict(list(self.pr_state.items())[-MAX_PR_STATE:]),
            "releases": list(self.releases.keys())[-MAX_RELEASES:],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        tmp.replace(path)

    def seen(self, delivery_id: str) -> bool:
        """Records a delivery id and returns True if it was already present."""
        if not delivery_id:
            return False
        if delivery_id in self.deliveries:
            return True
        self.deliveries[delivery_id] = True
        while len(self.deliveries) > MAX_DELIVERIES:
            self.deliveries.popitem(last=False)
        return False

    def remember_pr(self, repo_full_name: str, number: int, message_id: int) -> None:
        key = self.pr_key(repo_full_name, number)
        self.pr_messages[key] = message_id
        self.pr_messages.move_to_end(key)
        while len(self.pr_messages) > MAX_PR_MESSAGES:
            self.pr_messages.popitem(last=False)

    def pr_message(self, repo_full_name: str, number: int) -> int | None:
        return self.pr_messages.get(self.pr_key(repo_full_name, number))

    def release_seen(self, repo_full_name: str, tag: str) -> bool:
        """Records a release and returns True if it was already announced."""
        key = self.release_key(repo_full_name, tag)
        if key in self.releases:
            return True
        self.releases[key] = True
        while len(self.releases) > MAX_RELEASES:
            self.releases.popitem(last=False)
        return False

    def pr_signature(self, key: str) -> str | None:
        return self.pr_state.get(key)

    def set_pr_signature(self, key: str, signature: str) -> None:
        self.pr_state[key] = signature
        self.pr_state.move_to_end(key)
        while len(self.pr_state) > MAX_PR_STATE:
            self.pr_state.popitem(last=False)
