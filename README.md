# devkg-watcher

Twice-daily check of [devkg.com/ru/rabota](https://devkg.com/ru/rabota) for new vacancies with a Telegram digest.

- Walks all list pages (`?page=N`) until an empty one, parses cards, dedups by the numeric vacancy ID.
- New = ID not seen before (stored in SQLite). The list is not sorted by ID, so the whole list is scanned every run.
- All new vacancies are sent; keyword matches (see `devkg_watcher/relevance.py`, override with `DEVKG_KEYWORDS`) are marked with ⭐ and go first. Keywords are searched in the title and description preview; a stop word in the title (senior, lead, java, c#, .net, менеджер, ...; override with `DEVKG_EXCLUDE`) removes the ⭐.
- First run seeds the DB and sends a summary with the currently relevant vacancies only.
- Vacancies are stored only after a successful send, so a Telegram failure means a retry on the next run.
- If page 1 parses to zero vacancies (markup changed), an alert is sent and the run exits with code 1.

## Local

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt -r requirements-dev.txt
.\.venv\Scripts\ruff check . ; .\.venv\Scripts\ruff format --check .
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -X utf8 -m devkg_watcher --dry-run   # prints messages, writes nothing
```

## CI/CD

GitHub Actions (`.github/workflows/ci-cd.yml`) on every push to `main`:

1. **test**: `ruff check`, `ruff format --check`, `pytest` (also runs on pull requests).
2. **build**: native arm64 image on `ubuntu-24.04-arm`, pushed to `ghcr.io/acided/devkg-watcher` as `:<sha>` and `:latest`.
3. **deploy**: over SSH as `deploy@<server>` uploads `deploy/compose.yml`, pins `IMAGE_TAG=<sha>` in `/opt/devkg-watcher/.env`, pulls the image and runs an import smoke test.

The scheduled run itself is a systemd timer on the server (`deploy/devkg-watcher.timer`, 10:00 and 19:00 Asia/Bishkek) that calls `docker compose run --rm watcher`, so a deploy never interrupts a run in progress.

Repository secrets: `DEPLOY_HOST`, `DEPLOY_SSH_KEY` (private key of the `deploy` user), `DEPLOY_KNOWN_HOSTS`.

## Server (Ubuntu 24.04 arm64, Docker)

One-time setup, as root:

```bash
useradd -m -s /bin/bash deploy && usermod -aG docker deploy
install -d -o deploy -g deploy /opt/devkg-watcher
install -m 600 -o deploy -g deploy /dev/null /opt/devkg-watcher/app.env   # TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
cp deploy/devkg-watcher.service deploy/devkg-watcher.timer /etc/systemd/system/
systemctl daemon-reload
systemctl start devkg-watcher.service        # first run: seeds DB, sends summary
systemctl enable --now devkg-watcher.timer
```

Operations:

```bash
journalctl -u devkg-watcher -n 50                       # logs
systemctl list-timers devkg-watcher.timer               # next run
cd /opt/devkg-watcher && docker compose run --rm watcher --dry-run
# rollback: put an older sha into /opt/devkg-watcher/.env, then `docker compose pull`
```

The SQLite DB lives in the `devkg-watcher_data` Docker volume (`/data` in the container).