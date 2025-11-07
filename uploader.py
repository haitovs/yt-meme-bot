from __future__ import annotations

import datetime as dt
import json
import logging
import os
import random
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

import db
from youtube import list_channel_credentials, upload_to_all

log = logging.getLogger(__name__)
_warned_templates: set[Path] = set()


DEFAULT_DESCRIPTIONS = [
    "Hilarious meme video! Subscribe for more laughs! 😂 #meme",
    "Epic meme alert! Like and subscribe! 😜 #funny",
    "LOL with this meme! More coming soon! 🚀 #viral",
]


def _load_templates() -> Tuple[List[str], List[str]]:
    """Load description and tags templates with fallbacks."""
    desc_path = Path("templates") / "description.json"
    tags_path = Path("templates") / "tags.json"

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


async def handle_upload(bot, cfg: Dict[str, Any], tg_file_id: str, original_filename: str, base_title: str) -> str:
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

    # If under limit, upload immediately
    if uploaded_today < cfg["daily_limit"]:
        # Download from Telegram into a temp file
        f = await bot.get_file(tg_file_id)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp_file:
            temp_name = tmp_file.name
        try:
            await f.download_to_drive(custom_path=temp_name)
            num_ok, results = upload_to_all(temp_name, title, desc, tags, cfg["channels_path"])
        finally:
            try:
                os.remove(temp_name)
            except FileNotFoundError:
                pass

        # log as uploaded now
        db.log_new_job(
            tg_file_id=tg_file_id,
            local_file=None,
            title=title,
            description=desc,
            tags=tags,
            channels=channel_names,
            scheduled_at=now,  # for record
            status="uploaded",
            seq_no=seq_no,
            uploaded_at=now,
        )
        if num_ok == len(channel_files):
            return f"✅ Video uploaded to all {num_ok} channels!"
        summary = _format_results(results, len(channel_files))
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
        )
        return f"✅ Daily limit reached. Video scheduled for {scheduled_time.isoformat()} UTC."
