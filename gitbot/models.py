"""The shapes the bot works with, decoded from a webhook payload. Pure data
plus the small derived properties the renderer and filters ask for."""

from __future__ import annotations

from dataclasses import dataclass, field

ZERO_SHA = "0" * 40


@dataclass
class Commit:
    id: str
    message: str
    url: str
    author_name: str
    author_login: str


@dataclass
class Repo:
    full_name: str
    html_url: str
    default_branch: str
    private: bool


@dataclass
class Push:
    repo: Repo
    ref: str
    before: str
    after: str
    compare_url: str
    total_commits: int
    commits: list[Commit]
    pusher: str

    @property
    def branch(self) -> str:
        return self.ref.split("refs/heads/", 1)[-1] if self.ref.startswith("refs/heads/") else self.ref

    @property
    def is_tag(self) -> bool:
        return self.ref.startswith("refs/tags/")

    @property
    def tag_name(self) -> str:
        return self.ref.split("refs/tags/", 1)[-1]

    @property
    def is_new_branch(self) -> bool:
        return self.before == ZERO_SHA

    @property
    def is_deleted_branch(self) -> bool:
        return self.after == ZERO_SHA


@dataclass
class PullRequest:
    repo: Repo
    action: str
    number: int
    title: str
    url: str
    state: str
    merged: bool
    base_ref: str
    head_label: str
    body: str
    opener: str
    head_sha: str = ""
    changed_files: int = 0
    draft: bool = False
    approved_by: tuple[str, ...] = ()
    changes_by: tuple[str, ...] = ()

    @property
    def is_draft(self) -> bool:
        return self.draft or self.title.upper().startswith(("WIP:", "[WIP]", "DRAFT:"))

    @property
    def gh_number(self) -> str:
        """The GitHub number for a synced PR, taken from a head label like
        `owner/repo:gh-485`. Empty when this is a native pull request."""
        tail = self.head_label.rsplit(":", 1)[-1]
        return tail[3:] if tail.startswith("gh-") and tail[3:].isdigit() else ""


@dataclass
class Release:
    repo: Repo
    action: str
    tag_name: str
    name: str
    url: str
    assets: list[tuple[str, int]] = field(default_factory=list)
    draft: bool = False
    prerelease: bool = False
