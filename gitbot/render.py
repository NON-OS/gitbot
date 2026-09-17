"""Message shapes. Plain and scannable, the same voice as the site. Every
dynamic value is HTML-escaped; only the fixed markup is raw."""

from __future__ import annotations

import html

from .models import Commit, PullRequest, Push, Release


def _esc(text: str) -> str:
    return html.escape(text or "", quote=False)


def first_line(message: str, limit: int) -> str:
    line = (message or "").splitlines()[0] if message else ""
    line = line.strip()
    return line if len(line) <= limit else line[: limit - 1].rstrip() + "…"


def _author_label(commits: list[Commit]) -> str:
    names = []
    for c in commits:
        name = c.author_login or c.author_name
        if name and name not in names:
            names.append(name)
    if not names:
        return "unknown"
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return f"{names[0]} and {len(names) - 1} others"


def render_push(push: Push, max_commits: int, summary_chars: int) -> str:
    if push.is_tag:
        head = f"<b>{_esc(push.repo.full_name)}</b> · tag {_esc(push.tag_name)}"
        link = f"{push.repo.html_url}/releases/tag/{html.escape(push.tag_name, quote=True)}"
        return f'{head}\nTag created\n<a href="{link}">View the tag</a>'

    n = push.total_commits or len(push.commits)
    plural = "commit" if n == 1 else "commits"
    head = (
        f"<b>{_esc(push.repo.full_name)}</b> · {_esc(push.branch)}\n{n} {plural} by {_esc(_author_label(push.commits))}"
    )
    lines = [head, ""]
    for c in push.commits[:max_commits]:
        lines.append(f"· {_esc(first_line(c.message, summary_chars))}")
    hidden = n - min(len(push.commits), max_commits)
    if hidden > 0:
        lines.append(f"· and {hidden} more")
    if push.compare_url:
        lines.append(f'<a href="{push.compare_url}">View the diff</a>')
    return "\n".join(lines)


def render_repo_new(push: Push) -> str:
    n = push.total_commits or len(push.commits)
    plural = "commit" if n == 1 else "commits"
    head = f"<b>New repository</b> · {_esc(push.repo.full_name)}"
    meta = f"{n} {plural} by {_esc(_author_label(push.commits))} on {_esc(push.branch)}"
    return f'{head}\n{meta}\n<a href="{push.repo.html_url}">{_esc(push.repo.html_url)}</a>'


def _pr_headline(pr: PullRequest) -> str:
    if pr.action == "closed" and pr.merged:
        verb = "merged"
    elif pr.action == "closed":
        verb = "closed"
    elif pr.action == "reopened":
        verb = "reopened"
    else:
        verb = "opened"
    return f"Pull request {verb}"


def render_pull_request(pr: PullRequest, author: str) -> str:
    head = f"<b>{_esc(_pr_headline(pr))}</b> · {_esc(pr.repo.full_name)} #{pr.number}"
    title = _esc(pr.title)
    meta = f"by {_esc(author)}"
    if pr.base_ref:
        meta += f" · {_esc(pr.base_ref)}"
    if pr.gh_number:
        meta += f" (GitHub #{_esc(pr.gh_number)})"
    if pr.head_sha:
        meta += f" · {_esc(pr.head_sha[:7])}"
    review = ""
    if pr.changes_by:
        review = f"\n🔴 Changes requested by {_esc(', '.join(pr.changes_by))}"
    elif pr.approved_by:
        review = f"\n✅ Approved by {_esc(', '.join(pr.approved_by))}"
    return f'{head}\n{title}\n{meta}{review}\n<a href="{pr.url}">{_esc(pr.url)}</a>'


def _fmt_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def render_release(release: Release, max_files: int = 8) -> str:
    name = release.name or release.tag_name
    label = "Pre-release published" if release.prerelease else "Release published"
    head = f"<b>{label}</b> · {_esc(release.repo.full_name)}"
    lines = [head, _esc(name), ""]
    checksums = next((a for a in release.assets if a[0].upper().startswith("SHA256")), None)
    files = [a for a in release.assets if a is not checksums]
    for fname, size in files[:max_files]:
        lines.append(f"· {_esc(fname)} <i>({_fmt_size(size)})</i>")
    hidden = len(files) - min(len(files), max_files)
    if hidden > 0:
        lines.append(f"· and {hidden} more")
    if checksums:
        lines.append(f'<a href="{release.url}">🔒 {_esc(checksums[0])}</a>')
    lines.append(f'<a href="{release.url}">{_esc(release.url)}</a>')
    return "\n".join(lines)
