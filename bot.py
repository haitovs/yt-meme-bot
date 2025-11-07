import datetime as dt
import logging
from typing import Optional

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import db
from config import ConfigError, load_config
from db import init_db
from scheduler import init_scheduler
from uploader import handle_upload

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("yt-meme-bot")

try:
    cfg = load_config()
except ConfigError as exc:
    log.error("Configuration error: %s", exc)
    raise
init_db(cfg["db_path"])

ADMIN_ID = cfg["admin_id"]
ASK_VIDEO, ASK_TITLE = range(2)


def _is_authorized(update: Update) -> bool:
    user = update.effective_user
    return bool(user and user.id == ADMIN_ID)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        await update.message.reply_text("❌ Access denied.")
        return
    await update.message.reply_text("Send /upload to upload a new meme video.")


async def upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        await update.message.reply_text("❌ Access denied.")
        return ConversationHandler.END
    await update.message.reply_text("Send me the MP4 file (max 50MB).")
    return ASK_VIDEO


def _extract_file(update: Update) -> Optional[dict]:
    """Return dict with tg_file_id, size, name if valid MP4 <=50MB; else None."""
    msg = update.message
    if not msg:
        return None

    # Prefer native video
    if msg.video:
        v = msg.video
        if v.mime_type != "video/mp4":
            return None
        if v.file_size and v.file_size > 50 * 1024 * 1024:
            return None
        return {"tg_file_id": v.file_id, "size": v.file_size, "name": "video.mp4"}

    # Fallback: document as mp4
    if msg.document:
        d = msg.document
        if d.mime_type != "video/mp4" and not (d.file_name or "").lower().endswith(".mp4"):
            return None
        if d.file_size and d.file_size > 50 * 1024 * 1024:
            return None
        return {"tg_file_id": d.file_id, "size": d.file_size, "name": d.file_name or "video.mp4"}

    return None


async def receive_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    info = _extract_file(update)
    if not info:
        await update.message.reply_text("❌ Please send an MP4 video up to 50MB.")
        return ASK_VIDEO
    context.user_data["video_info"] = info
    await update.message.reply_text("Now send me the title text.")
    return ASK_TITLE


async def receive_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    title = (update.message.text or "").strip()
    if not title:
        await update.message.reply_text("❌ Title cannot be empty. Please send the title text.")
        return ASK_TITLE
    info = context.user_data.get("video_info")
    if not info:
        await update.message.reply_text("❌ I lost the video reference. Please start again with /upload.")
        return ConversationHandler.END
    await update.message.reply_text("⏳ Processing upload...")

    try:
        result = await handle_upload(context.application.bot, cfg, info["tg_file_id"], info["name"], title)
        await update.message.reply_text(result)
    except Exception as e:
        log.exception("Upload failed: %s", e)
        await update.message.reply_text(f"❌ Error: {e}")
    finally:
        context.user_data.pop("video_info", None)

    return ConversationHandler.END


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        await update.message.reply_text("❌ Access denied.")
        return
    today = dt.datetime.now(tz=dt.timezone.utc).date()
    tomorrow = today + dt.timedelta(days=1)
    uploaded_today = db.count_uploaded_on(today)
    scheduled_today = db.count_scheduled_on(today)
    scheduled_tomorrow = db.count_scheduled_on(tomorrow)
    await update.message.reply_text(
        "📊 Status\n"
        f"- Uploaded today: {uploaded_today}/{cfg['daily_limit']}\n"
        f"- Scheduled today: {scheduled_today}\n"
        f"- Scheduled tomorrow: {scheduled_tomorrow}"
    )


def main():
    app = Application.builder().token(cfg["telegram_token"]).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("upload", upload)],
        states={
            ASK_VIDEO: [MessageHandler(filters.VIDEO | filters.Document.MimeType("video/mp4"), receive_video)],
            ASK_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_title)],
        },
        fallbacks=[],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("status", status))

    # Start background scheduler (due uploads, rescheduling)
    init_scheduler(app, cfg)

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
