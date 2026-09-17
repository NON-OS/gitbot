"""Parse Forgejo webhook payloads into the model objects. Only the fields the
bot renders are pulled out; everything else in the payload is ignored. Field
names match what Forgejo 16.x sends."""

from __future__ import annotations

from .models import Commit, PullRequest, Push, Release, Repo


def _repo(payload: dict) -> Repo:
    r = payload.get("repository", {}) or {}
    return Repo(
        full_name=r.get("full_name", "?"),
        html_url=r.get("html_url", ""),
        default_branch=r.get("default_branch", "main"),
        private=bool(r.get("private", False)),
    )


def parse_push(payload: dict) -> Push:
    commits = [
        Commit(
            id=c.get("id", ""),
            message=c.get("message", ""),
            url=c.get("url", ""),
            author_name=(c.get("author", {}) or {}).get("name", ""),
            author_login=(c.get("author", {}) or {}).get("username", ""),
        )
        for c in (payload.get("commits") or [])
    ]
    return Push(
        repo=_repo(payload),
        ref=payload.get("ref", ""),
        before=payload.get("before", ""),
        after=payload.get("after", ""),
        compare_url=payload.get("compare_url", ""),
        total_commits=int(payload.get("total_commits", len(commits)) or len(commits)),
        commits=commits,
        pusher=(payload.get("pusher", {}) or {}).get("login", ""),
    )


def parse_pull_request(payload: dict) -> PullRequest:
    pr = payload.get("pull_request", {}) or {}
    return PullRequest(
        repo=_repo(payload),
        action=payload.get("action", ""),
        number=int(pr.get("number", payload.get("number", 0)) or 0),
        title=pr.get("title", ""),
        url=pr.get("html_url", ""),
        state=pr.get("state", ""),
        merged=bool(pr.get("merged", False)),
        base_ref=(pr.get("base", {}) or {}).get("ref", ""),
        head_label=(pr.get("head", {}) or {}).get("label", ""),
        body=pr.get("body", "") or "",
        opener=(pr.get("user", {}) or {}).get("login", ""),
    )


def parse_release(payload: dict) -> Release:
    rel = payload.get("release", {}) or {}
    assets = [(a.get("name", ""), int(a.get("size", 0) or 0)) for a in (rel.get("assets") or [])]
    return Release(
        repo=_repo(payload),
        action=payload.get("action", ""),
        tag_name=rel.get("tag_name", ""),
        name=rel.get("name", ""),
        url=rel.get("html_url", ""),
        assets=assets,
        draft=bool(rel.get("draft", False)),
        prerelease=bool(rel.get("prerelease", False)),
    )
