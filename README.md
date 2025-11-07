# yt-meme-bot

Telegram bot that accepts short MP4 memes from a trusted admin account, enriches the metadata, and uploads them to every configured YouTube channel. When the daily upload quota is reached, videos are automatically queued and posted in evenly spaced slots the next day.

## Prerequisites

- Python 3.10+
- Telegram bot token and your Telegram user id (admin)  
- Google Cloud project with the YouTube Data API enabled

## 1. Install dependencies

```bash
git clone https://github.com/haitovs/yt-meme-bot.git
cd yt-meme-bot
python -m venv .venv
.venv\Scripts\activate  # or source .venv/bin/activate on Linux/macOS
pip install -r requirements.txt
```

## 2. Configure the bot

Edit `config.yaml` and set:

- `telegram_token` – token from @BotFather
- `admin_id` – your Telegram numeric user id (messages from others are rejected)
- `daily_limit` – how many uploads per UTC day can go live immediately
- `upload_start_hour` / `upload_interval_minutes` – define the queue window for the next day
- `channels_path` (optional) – folder that stores authorized YouTube credentials (defaults to `channels/`)
- `db_path` (optional) – SQLite database path (defaults to `uploads.db`)

The loader validates the values and creates the folders automatically.

## 3. Add YouTube credentials

1. Create an OAuth consent screen + Desktop app credentials in Google Cloud.  
2. Run the OAuth flow (e.g. via the [YouTube Data API Python quickstart](https://developers.google.com/youtube/v3/quickstart/python)) for each channel you want to target.  
3. Save the resulting **authorized user** JSON (`token`, `refresh_token`, `client_id`, …) inside the `channels/` folder. Use one file per channel.  
4. See `channels/README.md` for an example format. The folder is ignored by git so you don’t leak secrets.

## 4. (Optional) Customize templates

Update the JSON arrays inside `templates/description.json` and `templates/tags.json` to control the random description snippets and the tag pool. When missing or invalid, the bot falls back to safe built‑in defaults.

## Running

```bash
python bot.py
```

Available commands (admin only):

- `/upload` – guided flow to send an MP4 (≤ 50 MB) and the base title
- `/status` – shows how many videos were uploaded today and how many are queued

Uploads start immediately while you are under `daily_limit`. Once the cap is hit, the bot schedules new jobs for the next UTC day, spacing them by `upload_interval_minutes` starting at `upload_start_hour`. The async scheduler checks the queue every minute and retries/reschedules failed jobs automatically.

Runtime artifacts:

- `uploads.db` – SQLite log of all jobs (auto-created if missing, ignored by git)
- `bot.log` – combined console/file log for debugging

## Troubleshooting

- `ConfigError`: ensure `config.yaml` exists and all required keys are set.  
- `❌ No YouTube channel credentials...`: drop at least one authorized user JSON into `channels/`.  
- API quota/HTTP errors: the scheduler automatically reschedules for the next day and includes the reason in the admin notification. Check `bot.log` for stack traces.
