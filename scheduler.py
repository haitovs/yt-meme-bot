import datetime as dt
import logging
import tempfile
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler

import db
from youtube import upload_to_all

log = logging.getLogger(__name__)


def _start_of_day_utc(d: dt.date) -> dt.datetime:
    return dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc)


def compute_next_day_slot(date_utc: dt.date, start_hour: int, interval_min: int) -> dt.datetime:
    start = _start_of_day_utc(date_utc) + dt.timedelta(hours=start_hour)
    offset_n = db.count_scheduled_on(date_utc)
    return start + dt.timedelta(minutes=offset_n * interval_min)


def init_scheduler(application, cfg: dict):
    scheduler = AsyncIOScheduler(timezone="UTC")

    @scheduler.scheduled_job("interval", seconds=60, id="process_scheduled")
    async def process_scheduled():
        try:
            now = dt.datetime.now(tz=dt.timezone.utc)
            today = now.date()

            uploaded_today = db.count_uploaded_on(today)
            if uploaded_today >= cfg["daily_limit"]:
                return  # nothing to do until tomorrow

            due = db.due_jobs(now)
            if not due:
                return

            for (job_id, tg_file_id, title, description, tags_csv, channels_csv) in due:
                if uploaded_today >= cfg["daily_limit"]:
                    # reschedule for tomorrow
                    tomorrow = today + dt.timedelta(days=1)
                    new_time = compute_next_day_slot(tomorrow, cfg["upload_start_hour"], cfg["upload_interval_minutes"])
                    db.reschedule(job_id, new_time, "Daily limit reached while processing queue")
                    await application.bot.send_message(cfg["admin_id"], f"ℹ️ Daily limit reached. Job {job_id} moved to {new_time.isoformat()} UTC.")
                    continue

                # Download from Telegram and upload
                tmp_path = None
                try:
                    file = await application.bot.get_file(tg_file_id)
                    with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{job_id}.mp4") as tmp_file:
                        tmp_path = tmp_file.name
                    await file.download_to_drive(custom_path=tmp_path)

                    num_ok, results = upload_to_all(tmp_path, title, description, tags_csv.split(",") if tags_csv else [], cfg["channels_path"])
                    db.mark_uploaded(job_id, dt.datetime.now(tz=dt.timezone.utc))
                    uploaded_today += 1

                    # Cleanup
                    try:
                        Path(tmp_path).unlink(missing_ok=True)
                    except Exception as cleanup_exc:
                        log.warning("Failed to delete temp file %s: %s", tmp_path, cleanup_exc)

                    channel_list = [c for c in channels_csv.split(",") if c] if channels_csv else []
                    total = len(results) if results else len(channel_list)
                    failed = [f"{chan}: {status}" for chan, status in results.items() if not status.startswith("ok:")]
                    if failed:
                        preview = "\n".join(f"- {line}" for line in failed[:3])
                        if len(failed) > 3:
                            preview += f"\n... {len(failed) - 3} more failures."
                        msg = f"⚠️ Scheduled video uploaded to {num_ok}/{total} channels (job {job_id}).\n{preview}"
                    else:
                        msg = f"✅ Scheduled video uploaded to all {total} channels (job {job_id})."

                    await application.bot.send_message(cfg["admin_id"], msg)
                except Exception as e:
                    if tmp_path:
                        try:
                            Path(tmp_path).unlink(missing_ok=True)
                        except Exception:
                            pass

                    # Quota/network/etc: push to tomorrow first available slot
                    tomorrow = today + dt.timedelta(days=1)
                    new_time = compute_next_day_slot(tomorrow, cfg["upload_start_hour"], cfg["upload_interval_minutes"])
                    db.reschedule(job_id, new_time, str(e))
                    await application.bot.send_message(cfg["admin_id"], f"❌ Error on job {job_id}: {e}\nRescheduled for {new_time.isoformat()} UTC.")
        except Exception as e:
            log.exception("Scheduler loop crashed: %s", e)

    scheduler.start()
