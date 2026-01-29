from __future__ import annotations

import datetime as dt
import json
import logging
import os
import random
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import hashlib
import subprocess

class DuplicateVideoError(Exception):
    def __init__(self, date: dt.date, title: str):
        self.date = date
        self.title = title
        super().__init__(f"Duplicate video from {date} ({title})")

from . import db
from .youtube import list_channel_credentials, upload_to_all

log = logging.getLogger(__name__)
_warned_templates: set[Path] = set()


DEFAULT_DESCRIPTIONS = [
    "Hilarious meme video! Subscribe for more laughs! 😂 #meme",
    "Epic meme alert! Like and subscribe! 😜 #funny",
    "LOL with this meme! More coming soon! 🚀 #viral",
]


def _load_templates() -> Tuple[List[str], List[str]]:
    """Load description and tags templates with fallbacks."""
    desc_path = Path(__file__).parent / "templates" / "description.json"
    tags_path = Path(__file__).parent / "templates" / "tags.json"

    descriptions = _load_json_list(desc_path) or list(DEFAULT_DESCRIPTIONS)
    tag_pool = _load_json_list(tags_path)
    return descriptions, tag_pool


def _load_json_list(path: Path) -> List[str]:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [str(item).strip() for item in data if isinstance(item, str)]
    except FileNotFoundError:
        if path not in _warned_templates:
            log.warning("Template file missing: %s (using defaults)", path)
            _warned_templates.add(path)
    except json.JSONDecodeError as exc:
        if path not in _warned_templates:
            log.warning("Template file %s is invalid JSON: %s", path, exc)
            _warned_templates.add(path)
    return []


def _extract_title_tags(title: str) -> List[str]:
    words = re.findall(r"[A-Za-z0-9#@]+", title)
    base = [w.lower() for w in words if len(w) >= 4]
    base += ["meme", "funny", "viral"]
    # Dedup while keeping order
    seen = set()
    out = []
    for t in base:
        if t not in seen:
            out.append(t)
            seen.add(t)
    return out


def _limit_tags(tags: List[str]) -> List[str]:
    # YouTube tags limit ~500 chars
    out = []
    total = 0
    for t in tags:
        add = len(t) + (1 if out else 0)
        if total + add > 490:
            break
        out.append(t)
        total += add
    return out


def enhance_metadata(base_title: str, seq_no: int) -> Tuple[str, str, List[str]]:
    if len(base_title.strip()) < 4:
        base_title = "Random funny content"
    title = f"{base_title}... memes I found on TikTok #{seq_no}"
    descriptions, tag_pool = _load_templates()
    description = random.choice(descriptions)
    tags = _extract_title_tags(title)
    # sprinkle a few random tags from pool
    extra_tags = tag_pool[:]
    random.shuffle(extra_tags)
    tags.extend(extra_tags[:10])
    tags = _limit_tags(list(dict.fromkeys(tags)))  # dedup+limit
    return title[:100], description, tags


def _next_available_slot(cfg: Dict[str, Any], target_date: dt.date) -> dt.datetime:
    """Compute the next upload slot for the given date."""
    start = dt.datetime(
        target_date.year,
        target_date.month,
        target_date.day,
        hour=int(cfg["upload_start_hour"]),
        minute=0,
        tzinfo=dt.timezone.utc,
    )
    offset = db.count_scheduled_on(target_date)
    return start + dt.timedelta(minutes=offset * int(cfg["upload_interval_minutes"]))


def _format_results(results: Dict[str, str], total_channels: int) -> str:
    failed = [f"{chan}: {status}" for chan, status in results.items() if not status.startswith("ok:")]
    if not failed:
        return ""
    preview = "\n".join(f"- {line}" for line in failed[:3])
    if len(failed) > 3:
        preview += f"\n... {len(failed) - 3} more failures."
    return f"\n⚠️ Issues on {len(failed)}/{total_channels} channels:\n{preview}"


import hashlib
import subprocess

def calculate_hash(file_path: str) -> str:
    """Calculate SHA256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            sha256.update(chunk)
    return sha256.hexdigest()


def extract_thumbnail(video_path: str) -> Optional[str]:
    """Extract a thumbnail from the middle of the video using ffmpeg."""
    try:
        # Get duration
        cmd_dur = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", video_path]
        duration = float(subprocess.check_output(cmd_dur).strip())
        
        timestamp = duration / 2
        thumb_path = str(Path(video_path).with_suffix(".jpg"))
        
        # Extract frame
        cmd_thumb = [
            "ffmpeg", "-y", "-ss", str(timestamp), 
            "-i", video_path, 
            "-vframes", "1", 
            "-q:v", "2", 
            thumb_path
        ]
        subprocess.run(cmd_thumb, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if Path(thumb_path).exists():
            return thumb_path
    except Exception as e:
        log.warning("Failed to extract thumbnail: %s", e)
    return None


def process_video(input_path: str) -> Optional[str]:
    """
    Standardize video for YouTube to prevent infinite processing.
    - Container: MP4
    - Video: H.264 (libx264)
    - Audio: AAC
    - Moov atom: at start (faststart)
    """
    try:
        output_path = str(Path(input_path).with_name("processed_" + Path(input_path).name))
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            output_path
        ]
        log.info("Running FFmpeg standardization: %s", " ".join(cmd))
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        
        if Path(output_path).exists():
            return output_path
    except subprocess.CalledProcessError as e:
        log.error("FFmpeg processing failed: %s", e)
    return None



async def handle_upload(bot, cfg: Dict[str, Any], tg_file_id: str, original_filename: str, base_title: str, force_upload: bool = False) -> str:
    # Determine today's upload count
    now = dt.datetime.now(tz=dt.timezone.utc)
    today = now.date()
    uploaded_today = db.count_uploaded_on(today)
    seq_no = db.next_seq_no(base=100)
    title, desc, tags = enhance_metadata(base_title or Path(original_filename).stem or "", seq_no)

    channel_files = sorted(list_channel_credentials(cfg["channels_path"]))
    if not channel_files:
        return "❌ No YouTube channel credentials found in channels/."
    channel_names = [os.path.basename(p) for p in channel_files]
    
    # Download from Telegram into a temp file
    f = await bot.get_file(tg_file_id)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp_file:
        temp_name = tmp_file.name
    
    thumbnail_path = None
    file_hash = None
    processed_file = None
    
    try:
        await f.download_to_drive(custom_path=temp_name)
        
        # 1. Check for duplicates
        if not force_upload:
            file_hash = calculate_hash(temp_name)
            dup_info = db.check_if_hash_exists(file_hash)
            if dup_info:
                existing_date, existing_title = dup_info
                raise DuplicateVideoError(existing_date, existing_title)
        else:
            # Need hash for logging anyway
            file_hash = calculate_hash(temp_name)

        # 2. Extract thumbnail
        thumbnail_path = extract_thumbnail(temp_name)

        # 3. Standardize video (Fix for YouTube hang)
        processed_file = process_video(temp_name)
        if not processed_file:
             return "❌ Error: Failed to process video (FFmpeg). Check logs."
        
        # Use the processed file for upload
        final_file = processed_file

        # If under limit, upload immediately

        if uploaded_today < cfg["daily_limit"]:
            num_ok, results = upload_to_all(final_file, title, desc, tags, cfg["channels_path"], thumbnail_path=thumbnail_path)
            
            # log as uploaded now
            db.log_new_job(
                tg_file_id=tg_file_id,
                local_file=None,
                title=title
,
                description=desc,
                tags=tags,
                channels=channel_names,
                scheduled_at=now,  # for record
                status="uploaded",
                seq_no=seq_no,
                file_hash=file_hash,
                uploaded_at=now,
            )
            
            summary = _format_results(results, len(channel_files))
            if num_ok == len(channel_files):
                return f"✅ Video uploaded to all {num_ok} channels!"
            return f"⚠️ Uploaded to {num_ok}/{len(channel_files)} channels.{summary}"
        else:
            # schedule for tomorrow in 15-min slots starting at cfg["upload_start_hour"]
            tomorrow = today + dt.timedelta(days=1)
            scheduled_time = _next_available_slot(cfg, tomorrow)

            db.log_new_job(
                tg_file_id=tg_file_id,
                local_file=None,
                title=title,
                description=desc,
                tags=tags,
                channels=channel_names,
                scheduled_at=scheduled_time,
                status="scheduled",
                seq_no=seq_no,
                file_hash=file_hash,
            )
            return f"✅ Daily limit reached. Video scheduled for {scheduled_time.isoformat()} UTC."

    finally:
        try:
            if 'temp_name' in locals() and os.path.exists(temp_name):
                os.remove(temp_name)
            if 'processed_file' in locals() and processed_file and os.path.exists(processed_file):
                os.remove(processed_file)
            if thumbnail_path and os.path.exists(thumbnail_path):
                os.remove(thumbnail_path)
        except FileNotFoundError:
            pass
