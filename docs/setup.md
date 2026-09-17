# Setup

The bot needs a Telegram bot token, the group id, and the Forgejo webhook
secret. Everything else has a working default.

## 1. The Telegram bot

Talk to [@BotFather](https://t.me/BotFather), `/newbot`, copy the token. This
bot only posts, it takes no commands, so group privacy does not matter and
it does not need to be an admin. A plain member can post as long as the group
lets members send messages.

Add it to the group that should receive the feed. Consider whether that is
the main community chat or a separate developer group; a commit and pull
request feed is developer traffic and can read as noise next to price talk.

## 2. The group id

Add the bot, send any message in the group, then open
`https://api.telegram.org/bot<TOKEN>/getUpdates` and read `message.chat.id`.
Supergroup ids are negative and start with `-100`.

## 3. The Forgejo webhook secret

The forge admin creates one organisation webhook covering every repository
and hands you the secret out of band. It never goes in a repository or a
chat. See [operations.md](operations.md) for the events to enable.

## 4. Configure

```sh
cp .env.example .env
```

| Variable | Required | Default | Notes |
| --- | --- | --- | --- |
| `BOT_TOKEN` | yes | | from BotFather, or `BOT_TOKEN_FILE`, or a systemd credential |
| `CHAT_ID` | yes | | the group id, negative |
| `WEBHOOK_SECRET` | yes | | the Forgejo secret, or `WEBHOOK_SECRET_FILE`, or a credential |
| `MESSAGE_THREAD_ID` | no | `0` | a topic id, only if the group uses topics |
| `LISTEN_HOST` | no | `127.0.0.1` | loopback; the forge reaches it locally |
| `LISTEN_PORT` | no | `3191` | 3190 is the sync receiver |
| `WEBHOOK_PATH` | no | `/forgejo` | the path the webhook posts to |
| `FORGE_BASE` | no | `https://git.nonos.software` | for the author lookup |
| `ORG` | no | `NON-OS` | the organisation |
| `MAX_COMMITS` | no | `5` | commits shown before "and N more" |
| `SUMMARY_CHARS` | no | `90` | commit subject trim length |
| `SKIP_DRAFTS` | no | `1` | skip pull requests titled WIP until marked ready |
| `BATCH_SECONDS` | no | `60` | coalesce commit pushes per branch for this many seconds, 0 for immediate |
| `ADMIN_CHAT_ID` | no | `0` | private chat for failure alerts, 0 disables |
| `PR_POLL_SECONDS` | no | `90` | how often to poll the forge for pull request changes, 0 disables |
| `RELEASE_POLL_SECONDS` | no | `300` | how often to poll the forge for new releases, 0 disables |
| `COMMANDS_ENABLED` | no | `1` | answer read-only group commands, needs group privacy off |
| `REVIEWS_ENABLED` | no | `1` | show approvals and change requests on open pull requests |
| `DIGEST_ENABLED` | no | `1` | post the weekly summary on a schedule |
| `DIGEST_DOW` | no | `6` | weekday for the digest, Monday 0 to Sunday 6 |
| `DIGEST_HOUR` | no | `16` | hour of day for the digest, 0 to 23, UTC |
| `LOG_LEVEL` | no | `INFO` | DEBUG, INFO, WARNING or ERROR |

Every value is validated at start. A malformed token, a non-numeric chat id
or an out-of-range port stops the bot immediately with a one line reason,
rather than failing at the first delivery.

Secrets load from a file or a systemd credential before the environment, so
a long-lived process never carries the token in its environment. Set
`BOT_TOKEN_FILE` and `WEBHOOK_SECRET_FILE`, or run under the unit in
[deployment.md](deployment.md), which uses `LoadCredential`.

## 5. Run

```sh
python3 -m pip install -r requirements.txt
python3 -m gitbot
```

It listens on `127.0.0.1:3191/forgejo` and answers `/healthz`. Use the
webhook page's Test delivery to send a sample without pushing a commit.

## The two webhooks

Do not confuse them.

- **GitHub to forge.** A webhook in the GitHub organisation that tells
  git.nonos.software to sync now, so pushes arrive in seconds instead of on
  the poll interval. This bot never sees it.
- **Forge to bot.** The Forgejo organisation webhook that posts to this bot
  at `127.0.0.1:3191/forgejo`. This is the one the bot receives.
