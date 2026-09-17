"""Which banner image goes with which event. The files live in the media
directory and are rendered from nonos-next/tools/forge/banners/."""

from __future__ import annotations

from pathlib import Path

from .models import PullRequest

COMMITS = "banner-commits.png"
REPO_NEW = "banner-repo-new.png"
PR_OPENED = "banner-pr-opened.png"
PR_MERGED = "banner-pr-merged.png"
PR_CLOSED = "banner-pr-closed.png"
PR_APPROVED = "banner-pr-approved.png"
RELEASE = "banner-release.png"
DIGEST = "banner-digest.png"


def path(media_dir: Path, name: str) -> Path:
    return media_dir / name


def for_pull_request(pr: PullRequest) -> str:
    """The banner for a pull request in its current state. A PR is one message
    whose image and caption change together, so this is derived fresh on every
    event rather than stored."""
    if pr.action == "closed" and pr.merged:
        return PR_MERGED
    if pr.action == "closed":
        return PR_CLOSED
    if pr.approved_by and not pr.changes_by:
        return PR_APPROVED
    return PR_OPENED
