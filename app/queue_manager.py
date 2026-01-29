"""Queue management helpers for rescheduling logic."""
import datetime as dt
from typing import Dict, Any

from . import db


def handle_queue_deletion(cfg: Dict[str, Any], deleted_time: dt.datetime) -> int:
    """
    When a video is deleted, shift all subsequent videos forward.
    Returns: number of videos rescheduled
    """
    interval = cfg["upload_interval_minutes"]
    
    # Get all videos scheduled after this one
    later_videos = db.get_scheduled_after(deleted_time)
    
    # Move each one forward by interval minutes
    count = 0
    for job_id, old_time_str in later_videos:
        old_time = dt.datetime.fromisoformat(old_time_str)
        new_time = old_time - dt.timedelta(minutes=interval)
        db.reschedule_forward(job_id, new_time)
        count += 1
    
    return count
