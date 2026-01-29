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
from .uploader import handle_upload, DuplicateVideoError
from .queue_manager import handle_queue_deletion

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
            context.user_data.clear()
            return ConversationHandler.END

        except DuplicateVideoError as dup:
            msg = (
                f"⚠️ <b>Duplicate Detected!</b>\n\n"
                f"<b>Existing Video:</b>\n"
                f"📅 Date: {dup.date}\n"
                f"📝 Title: {dup.title}\n\n"
                f"<b>New Video:</b>\n"
                f"📝 Title: {title}\n\n"
                f"Do you want to force upload anyway?"
            )
            keyboard = [
                [
                    InlineKeyboardButton("⚠️ Yes, Force Upload", callback_data="force_upload"),
                    InlineKeyboardButton("❌ Cancel", callback_data="cancel_upload")
                ]
            ]
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
            return CONFIRM  # Stay in CONFIRM state to handle force_upload

        except Exception as e:
            log.exception("Upload failed: %s", e)
            await query.edit_message_text(f"❌ <b>Error:</b> {e}", parse_mode="HTML")
            context.user_data.clear()
            return ConversationHandler.END
            
    if query.data == "force_upload":
        await query.edit_message_text("⏳ <b>Force Uploading...</b>\n<i>Ignoring duplicate warning...</i>", parse_mode="HTML")
        
        info = context.user_data.get("video_info")
        title = context.user_data.get("video_title")
        
        if not info or not title:
            await query.edit_message_text("❌ Session expired. Please /upload again.")
            return ConversationHandler.END

        try:
            # Perform force upload
            result = await handle_upload(context.application.bot, cfg, info["tg_file_id"], info["name"], title, force_upload=True)
            await query.edit_message_text(result)
        except Exception as e:
            log.exception("Force upload failed: %s", e)
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


PAGE_SIZE = 5


def _format_queue_message(videos: list, page: int, total_count: int) -> tuple[str, InlineKeyboardMarkup]:
    """Format queue display with pagination."""
    total_pages = (total_count + PAGE_SIZE - 1) // PAGE_SIZE
    
    if not videos:
        return "📅 <b>Queue Empty</b>\n\nNo scheduled videos.", None
    
    msg_lines = [f"📅 <b>Scheduled Videos Queue</b>\nTotal: {total_count} video(s)\n"]
    
    # Group by date
    current_date = None
    now = dt.datetime.now(tz=dt.timezone.utc)
    today = now.date()
    tomorrow = today + dt.timedelta(days=1)
    
    for idx, (job_id, title, scheduled_at_str, seq_no, _) in enumerate(videos):
        scheduled_at = dt.datetime.fromisoformat(scheduled_at_str)
        video_date = scheduled_at.date()
        
        # Add date header
        if video_date != current_date:
            current_date = video_date
            if video_date == today:
                msg_lines.append("\n<b>📌 Today</b>")
            elif video_date == tomorrow:
                msg_lines.append("\n<b>📌 Tomorrow</b>")
            else:
                msg_lines.append(f"\n<b>📌 {video_date.strftime('%Y-%m-%d')}</b>")
        
        # Format time
        time_str = scheduled_at.strftime("%H:%M")
        truncated_title = title[:45] + "..." if len(title) > 45 else title
        
        position = page * PAGE_SIZE + idx + 1
        msg_lines.append(f"{position}. 🕐 {time_str} UTC - \"{truncated_title}\"")
    
    # Navigation buttons
    nav_buttons = []
    if total_pages > 1:
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("◀️ Prev", callback_data=f"queue_page_{page-1}"))
        nav_buttons.append(InlineKeyboardButton(f"Page {page+1}/{total_pages}", callback_data="queue_noop"))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton("Next ▶️", callback_data=f"queue_page_{page+1}"))
    
    # Delete buttons (one per video)
    keyboard = []
    for idx, (job_id, title, _, _, _) in enumerate(videos):
        position = page * PAGE_SIZE + idx + 1
        keyboard.append([InlineKeyboardButton(f"🗑️ Delete #{position}", callback_data=f"delete_confirm_{job_id}")])
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    return "\n".join(msg_lines), InlineKeyboardMarkup(keyboard) if keyboard else None


async def queue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display scheduled videos queue."""
    if not _is_authorized(update):
        await update.message.reply_text("❌ Access denied.")
        return
    
    total_count = db.count_scheduled_videos()
    videos = db.get_scheduled_videos(limit=PAGE_SIZE, offset=0)
    
    msg, keyboard = _format_queue_message(videos, page=0, total_count=total_count)
    await update.message.reply_text(msg, reply_markup=keyboard, parse_mode="HTML")


async def queue_page_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle queue pagination."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "queue_noop":
        return
    
    # Extract page number
    page = int(query.data.split("_")[-1])
    
    total_count = db.count_scheduled_videos()
    videos = db.get_scheduled_videos(limit=PAGE_SIZE, offset=page * PAGE_SIZE)
    
    msg, keyboard = _format_queue_message(videos, page=page, total_count=total_count)
    await query.edit_message_text(msg, reply_markup=keyboard, parse_mode="HTML")


async def delete_confirm_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show confirmation dialog for video deletion."""
    query = update.callback_query
    await query.answer()
    
    job_id = int(query.data.split("_")[-1])
    
    # Get video details
    details = db.get_video_details(job_id)
    if not details:
        await query.edit_message_text("❌ Video not found or already deleted.")
        return
    
    _, title, scheduled_at_str = details
    scheduled_at = dt.datetime.fromisoformat(scheduled_at_str)
    
    msg = (
        f"⚠️ <b>Confirm Deletion</b>\n\n"
        f"<b>Title:</b> {title}\n"
        f"<b>Scheduled:</b> {scheduled_at.strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        f"Are you sure? Other videos will move forward."
    )
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Yes, Delete", callback_data=f"delete_yes_{job_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data="delete_cancel")
        ]
    ]
    
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


async def delete_yes_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Execute video deletion and rescheduling."""
    query = update.callback_query
    await query.answer()
    
    job_id = int(query.data.split("_")[-1])
    
    # Get details before deleting
    details = db.get_video_details(job_id)
    if not details:
        await query.edit_message_text("❌ Video not found or already deleted.")
        return
    
    _, title, scheduled_at_str = details
    scheduled_at = dt.datetime.fromisoformat(scheduled_at_str)
    
    # Delete
    db.delete_scheduled_video(job_id)
    
    # Reschedule later videos
    rescheduled_count = handle_queue_deletion(cfg, scheduled_at)
    
    msg = (
        f"✅ <b>Deleted Successfully</b>\n\n"
        f"Video removed from queue.\n"
    )
    
    if rescheduled_count > 0:
        interval = cfg['upload_interval_minutes']
        msg += f"📊 {rescheduled_count} video(s) shifted forward by {interval} min."
    
    keyboard = [[InlineKeyboardButton("🔙 Back to Queue", callback_data="back_to_queue")]]
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


async def delete_cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel deletion and return to queue."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ Deletion cancelled.")


async def back_to_queue_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Return to queue view after deletion."""
    query = update.callback_query
    await query.answer()
    
    total_count = db.count_scheduled_videos()
    videos = db.get_scheduled_videos(limit=PAGE_SIZE, offset=0)
    
    msg, keyboard = _format_queue_message(videos, page=0, total_count=total_count)
    await query.edit_message_text(msg, reply_markup=keyboard, parse_mode="HTML")



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
    app.add_handler(CommandHandler("queue", queue))
    
    # Queue management callbacks
    app.add_handler(CallbackQueryHandler(queue_page_handler, pattern=r"^queue_page_\d+$"))
    app.add_handler(CallbackQueryHandler(queue_page_handler, pattern=r"^queue_noop$"))
    app.add_handler(CallbackQueryHandler(delete_confirm_handler, pattern=r"^delete_confirm_\d+$"))
    app.add_handler(CallbackQueryHandler(delete_yes_handler, pattern=r"^delete_yes_\d+$"))
    app.add_handler(CallbackQueryHandler(delete_cancel_handler, pattern=r"^delete_cancel$"))
    app.add_handler(CallbackQueryHandler(back_to_queue_handler, pattern=r"^back_to_queue$"))

    # Start background scheduler (due uploads, rescheduling)
    init_scheduler(app, cfg)

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

