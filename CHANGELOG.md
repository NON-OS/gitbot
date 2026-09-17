# Changelog

## Unreleased

- Health and self-monitoring. The pollers and the command loop report each
  completed cycle into a liveness registry. `/healthz` now returns JSON (overall
  ok, uptime, per-task last-cycle age, failures and last error) and answers 503
  once a task has stalled, so a monitor can catch a wedged poller. /status shows
  the same in the group, a new /repos lists what is watched, and a poller that
  fails several cycles in a row alerts the admin chat, throttled hourly.

- Poll the forge for releases. A release created on GitHub reaches the forge
  through the sync account and does not fire a release webhook, so releases were
  only ever surfaced in the weekly digest. The bot now reads each repository's
  releases every `RELEASE_POLL_SECONDS` (default 300) and posts a new one with
  its files and checksums, labelling a pre-release. The dedup is shared with the
  webhook path, so a release is never posted twice, and the first run records
  the current releases without posting them.

- Weekly digest. On a schedule (`DIGEST_DOW`, `DIGEST_HOUR`, default Sunday
  16:00 UTC) the bot posts a summary of the last seven days: pull requests
  merged, commits landed across the active repositories, and releases cut. A
  quiet week says so. The same summary is on demand with /digest.

- Show pull request reviews. The poller reads each open pull request's reviews
  and adds a line naming who approved or who requested changes, counting each
  reviewer's most recent decisive review, edited into the existing PR message
  (`REVIEWS_ENABLED`, default on). An approved PR uses the approval banner.

- Read-only group commands answered from the forge API: /prs, /latest, /repo,
  /digest, /status, /help. Rate limited, answered only in the configured chat
  or in private. Needs group privacy off so the bot can see the commands.

- Poll the forge for pull request changes. The forge does not fire
  pull_request webhooks for its sync-driven activity, so the bot only ever saw
  main pushes. It now reads the forge PR API on an interval (PR_POLL_SECONDS,
  default 90) and announces a pull request when it opens, gets new commits,
  merges or closes, editing the one message per PR. The first run learns the
  current state without posting so it does not flood the group.

- Read a merge commit as a merged pull request. A merge done on GitHub reaches
  the forge as a push, not a pull_request event, so the merge is recognised
  from the commit subject, confirmed against the forge API, and announced as a
  merged PR that edits the existing message, instead of a generic "new commits
  on main".
- Announce a new repository once, when its first push creates the default
  branch with commits, instead of arriving silently.
- Batch commit pushes per repository and branch for a short window
  (`BATCH_SECONDS`, default 60) so a burst becomes one message. Pull requests
  and releases still post immediately.
- Richer releases: list the files with their sizes and surface a checksums
  asset, within the caption limit.
- Alert a private admin chat (`ADMIN_CHAT_ID`) when Telegram sends or webhook
  signatures keep failing, at most once an hour per fault.
- Pin `aiohttp` to the deployed version. A fully hash-pinned lock is a
  follow-up; generate it with pip-tools on the server.
- Events whose banner is not present yet fall back to a plain text message
  rather than failing.

## 1.0.0

- First release. Posts commits, pull requests and releases from
  git.nonos.software to Telegram, verifying every webhook delivery over the
  raw body, deduplicating by delivery id, and editing a pull request in place
  as it opens, merges or closes. Each event carries a banner.
