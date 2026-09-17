# Operations

What the bot posts, what it drops, and how the messages read. The rules live
in `filters.py` and the shapes in `render.py`.

## Webhook events to enable

On the Forgejo organisation webhook, content type JSON, method POST, enable:

- Push
- Branch or tag creation
- Pull request
- Release

Leave the rest off. The bot also drops any event type it did not ask for, so
an over-broad webhook is harmless, just wasteful.

## What gets posted

**Commits.** Only pushes to a repository's default branch. The message shows
how many commits and who wrote them, taken from the commit authors, not the
`nonos-sync` account that carries them across. At most five commit subjects,
then "and N more" linking to the whole diff. Subjects are the first line
only, trimmed to about ninety characters.

**Pull requests.** Posted once when opened. Every later event, a new push to
the branch, a close, a merge, edits that same message so a pull request is
one line that changes its own state. A title starting with WIP is treated as
a draft and skipped until it is renamed, unless `SKIP_DRAFTS` is off.

**Releases.** Posted when published, with the tag, the name and the asset
count.

## What gets dropped

- Pushes to any branch other than the default. That work arrives as a pull
  request anyway.
- New and deleted branches. Tags still produce a line.
- Draft pull requests, until marked ready.
- Anything in a private repository. All of ours are public today; the check
  is there for the day one is not.
- Duplicate deliveries. Forgejo retries, and admins can redeliver by hand.

## Pull requests

The forge is fed from GitHub by a sync account and does not fire pull_request
webhooks for that activity, so the bot does not learn about pull requests from
the webhook stream. Instead it polls the forge PR API every PR_POLL_SECONDS and
posts when a pull request opens, gets new commits, merges or closes, keeping one
message per pull request that is edited in place. The first run after a fresh
state learns the current open pull requests without posting them.

## Releases

A release created on GitHub reaches the forge through the same sync account and
does not fire a release webhook, so, like pull requests, releases are polled.
Every `RELEASE_POLL_SECONDS` the bot reads each repository's releases and posts
the ones it has not seen, with the file list and checksums, and a pre-release is
labelled as such. The dedup is shared with the webhook path through the state,
so a release that does arrive as a webhook is never posted twice. The first run
after a fresh state records the current releases without posting them.

## Reviews

With `REVIEWS_ENABLED` on, the poller also reads each open pull request's
reviews and folds the outcome into its message: a green line naming who
approved, or a red line naming who requested changes. Only each reviewer's
most recent decisive review counts, so an approval that is later followed by a
request for changes reads as changes requested. A review change edits the same
pull request message the poller already keeps, so it does not add a new post.
An approved pull request also switches to the approval banner until it merges.

## Digest

With `DIGEST_ENABLED` on, the bot posts a weekly summary of the forge on
`DIGEST_DOW` at `DIGEST_HOUR` UTC (default Sunday 16:00): pull requests merged,
commits landed across the active repositories, and any releases cut over the
last seven days. A quiet week says so rather than staying silent. The same
summary is available on demand with /digest.

## Commands

Anyone in the group can ask, read only, rate limited: /prs [repo] lists open
pull requests, /latest <repo> shows recent commits on the default branch,
/repo <repo> summarises a repository, /repos lists the repositories being
watched, /digest shows what landed this week, /status reports bot health,
/help lists the commands. The bot needs group privacy disabled in BotFather to
see them.

## Banners

Every posted event carries a banner rendered from the site's design, with
the message as the caption: commits, pull request opened, merged and closed,
and release. A pull request keeps one message; its banner and caption are
swapped together with editMessageMedia as it opens, merges or closes. Tags
have no banner and go as a plain message. The images live in the media
directory and come from nonos-next/tools/forge/banners/, so a wording change
is a rerun of that tool, not a code change. A photo caption is limited to
1024 characters, so a long commit list is trimmed to fit.

## Message shapes

A push:

```
NON-OS/nonos-micro-kernel · main
3 commits by eKisNonos

· Directory records as one layout
· Same-length replacement in the store
· Reply inbox names stored inline
View the diff
```

A pull request, which becomes "Pull request merged" in place when it lands:

```
Pull request opened · nonos-micro-kernel #12
A key only this machine can derive
by eKisNonos · main (GitHub #485)
https://git.nonos.software/NON-OS/nonos-micro-kernel/pulls/12
```

## Tuning

- `MAX_COMMITS` and `SUMMARY_CHARS` control how much of a big push is shown.
- `SKIP_DRAFTS=0` posts WIP pull requests immediately.
- `REVIEWS_ENABLED=0` drops the approval and change-request lines.
- `PR_POLL_SECONDS` and `RELEASE_POLL_SECONDS` set the poll intervals; either
  at 0 turns that poller off.
- `DIGEST_DOW` and `DIGEST_HOUR` move the weekly digest; `DIGEST_ENABLED=0`
  turns it off while leaving /digest available.
- To move the feed to a different group, change `CHAT_ID`. To post into one
  topic of a group that uses topics, set `MESSAGE_THREAD_ID`.

## Health

The long-running tasks, the two pollers and the command loop, report each
completed cycle into a small liveness registry. The HTTP endpoint at `/healthz`
returns it as JSON: overall `ok`, uptime, and per-task last-cycle age, failure
count and last error. It answers 200 while every task is fresh and 503 once any
task has missed several of its own intervals, so a monitor can alert on a wedged
poller rather than on the process merely being up. The same view is in /status
in the group. When a poller fails several cycles in a row and an admin chat is
configured, it also raises an alert there, throttled to once an hour.

## Rate limits

Telegram allows roughly one message per second to a chat and about twenty a
minute in a group. The bot serialises all sends through one worker with a
small gap between them, and on a 429 waits the delay Telegram returns. A
push of forty commits is one message, not forty, so the limit is rarely near.
