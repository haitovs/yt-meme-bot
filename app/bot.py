import datetime as dt
import logging
from pathlib import Path
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from . import db
from .config import ConfigError, load_config
from .db import init_db
from .scheduler import init_scheduler
from .uploader import handle_upload

# Ensure logs directory exists
log_dir = Path("logs")
log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(log_dir / "bot.log", encoding="utf-8"),
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
ASK_VIDEO, ASK_TITLE, CONFIRM = range(3)


def _is_authorized(update: Update) -> bool:
    user = update.effective_user
    return bool(user and user.id == ADMIN_ID)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        await update.message.reply_text("❌ Access denied.")
        return
    await update.message.reply_text(
        f"👋 <b>Hello Admin!</b>\n"
        f"You are successfully authorized.\n\n"
        f"🚀 <b>Ready to deploy?</b>\n"
        f"Send /upload to start the process.",
        parse_mode="HTML"
    )


async def upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        await update.message.reply_text("❌ Access denied.")
        return ConversationHandler.END
    
    await update.message.reply_text("📤 <b>Step 1/3:</b> Send me the MP4 video file.", parse_mode="HTML")
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
        return {"tg_file_id": v.file_id, "size": v.file_size, "name": "video.mp4", "duration": v.duration}

    # Fallback: document as mp4
    if msg.document:
        d = msg.document
        if d.mime_type != "video/mp4" and not (d.file_name or "").lower().endswith(".mp4"):
            return None
        return {"tg_file_id": d.file_id, "size": d.file_size, "name": d.file_name or "video.mp4", "duration": 0}

    return None


async def receive_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    info = _extract_file(update)
    if not info:
        await update.message.reply_text("❌ Please send a valid MP4 video file.")
        return ASK_VIDEO
    
    if info.get("size", 0) > 50 * 1024 * 1024:
        await update.message.reply_text("❌ Video is too large (max 50MB). Try a smaller file.")
        return ASK_VIDEO

    context.user_data["video_info"] = info
    await update.message.reply_text("📝 <b>Step 2/3:</b> Now send me the title/caption.", parse_mode="HTML")
    return ASK_TITLE


async def receive_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    title = (update.message.text or "").strip()
    if not title:
        await update.message.reply_text("❌ Title cannot be empty. Please send text.")
        return ASK_TITLE

    context.user_data["video_title"] = title
    
    # Confirmation Card
    info = context.user_data["video_info"]
    duration = info.get('duration', 0)
    mins = duration // 60
    secs = duration % 60
    size_mb = round(info.get('size', 0) / (1024 * 1024), 2)

    msg = (
        f"🎬 <b>Confirmation Preview</b>\n\n"
        f"<b>Title:</b> {title}\n"
        f"<b>File:</b> {info['name']} ({size_mb} MB)\n"
        f"<b>Length:</b> {mins}:{secs:02d}\n\n"
        f"Ready to upload?"
    )

    keyboard = [
        [
            InlineKeyboardButton("✅ Confirm Upload", callback_data="confirm_upload"),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel_upload")
        ]
    ]
    
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    return CONFIRM


async def confirm_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "cancel_upload":
        await query.edit_message_text("❌ Upload cancelled.")
        context.user_data.clear()
        return ConversationHandler.END

    if query.data == "confirm_upload":
        await query.edit_message_text("⏳ <b>Processing...</b>\n<i>Creating thumbnail & optimizing video...</i>", parse_mode="HTML")
        
        info = context.user_data.get("video_info")
        title = context.user_data.get("video_title")
        
        if not info or not title:
            await query.edit_message_text("❌ Session expired. Please /upload again.")
            return ConversationHandler.END

        try:
            # Perform upload
            result = await handle_upload(context.application.bot, cfg, info["tg_file_id"], info["name"], title)
            await query.edit_message_text(result)
        except Exception as e:
            log.exception("Upload failed: %s", e)
            await query.edit_message_text(f"❌ <b>Error:</b> {e}", parse_mode="HTML")
        
        context.user_data.clear()
        return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Action cancelled.")
    context.user_data.clear()
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
        "📊 <b>System Status</b>\n"
        f"- Uploaded today: {uploaded_today}/{cfg['daily_limit']}\n"
        f"- Scheduled today: {scheduled_today}\n"
        f"- Scheduled tomorrow: {scheduled_tomorrow}",
        parse_mode="HTML"
    )


def main():
    app = Application.builder().token(cfg["telegram_token"]).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("upload", upload)],
        states={
            ASK_VIDEO: [MessageHandler(filters.VIDEO | filters.Document.MimeType("video/mp4"), receive_video)],
            ASK_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_title)],
            CONFIRM: [CallbackQueryHandler(confirm_handler)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("status", status))

    # Start background scheduler (due uploads, rescheduling)
    init_scheduler(app, cfg)

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

