# Deployment

The bot runs on the same server as the forge, sandboxed the way the sync
receiver is. It needs outbound HTTPS to `api.telegram.org` and to the forge,
a loopback port the forge can reach, and a writable state directory. No
inbound port from the internet.

## systemd

`deploy/gitbot.service` runs it as its own user with the sandbox the brief
asks for: `ProtectSystem=strict`, `ProtectHome=true`, `PrivateTmp=true`,
`NoNewPrivileges=true`, an empty `CapabilityBoundingSet`, and
`RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX`.

```sh
sudo useradd -r -s /usr/sbin/nologin gitbot
sudo mkdir -p /opt/nonos-gitbot /etc/nonos-gitbot
sudo cp -r . /opt/nonos-gitbot
sudo python3 -m venv /opt/nonos-gitbot/.venv
sudo /opt/nonos-gitbot/.venv/bin/pip install -r /opt/nonos-gitbot/requirements.txt

# secrets, root-owned, mode 600, handed to the unit by LoadCredential
printf '%s' "<telegram bot token>" | sudo tee /etc/nonos-gitbot/bot_token >/dev/null
printf '%s' "<forgejo webhook secret>" | sudo tee /etc/nonos-gitbot/webhook_secret >/dev/null
sudo chmod 600 /etc/nonos-gitbot/*

echo "CHAT_ID=-1002548279653" | sudo tee /opt/nonos-gitbot/.env
sudo cp deploy/gitbot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now gitbot
journalctl -u gitbot -f
```

The unit reads `BOT_TOKEN` and `WEBHOOK_SECRET` from the credential
directory, so they never appear in the environment or the process list.
State lives in `/var/lib/nonos-gitbot` via `StateDirectory`.

## The forge webhook

The bot listens on `127.0.0.1:3191`; 3190 is the sync receiver. Forgejo
refuses to deliver to loopback by default, so the forge admin allows that one
address, then creates the organisation webhook pointing at
`http://127.0.0.1:3191/forgejo` with a fresh secret. See
[operations.md](operations.md) for the events to enable.

## The GitHub webhook

Separate from the bot, and it accelerates GitHub to forge sync. In the
GitHub organisation, Settings, Webhooks: payload URL
`https://git.nonos.software/hooks/github`, content type JSON, the shared
secret, events Pushes, Branch or tag creation, Pull requests, Releases. With
it in place, pushes reach the forge in seconds instead of on the poll
interval. Adding it needs organisation admin rights.

## Verifying

- `systemctl status gitbot` should be active; a restart loop almost always
  means configuration, and the log names the variable it rejected.
- The forge webhook page has Test delivery and a log of recent deliveries
  with the request and response of each, and can resend one.
- `curl -s localhost:3191/healthz` returns the health JSON: overall `ok`,
  uptime and per-task last-cycle age. It answers 200 while the tasks are fresh
  and 503 once a poller has stalled, so it can back a monitor or a reverse-proxy
  check.

## Upgrading

```sh
sudo systemctl stop gitbot
sudo git -C /opt/nonos-gitbot pull
sudo systemctl start gitbot
```

Do not delete `state.json`. It holds the dedup ring and the PR message map;
losing it means a redelivered event could post twice, and a merge could no
longer edit the message the open created.

## Security notes

- The webhook HMAC is verified over the raw body before parsing, in constant
  time. A bad signature gets a 401 and the payload is never logged.
- The bot token and forge secret load from credentials, never the
  environment, and are redacted from logs.
- It listens on loopback only and holds no key that can change anything on
  the forge or the chain. It reads the forge and posts to one chat.
