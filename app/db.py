import datetime as dt
import sqlite3
from typing import List, Optional, Tuple

DB_PATH = None


def _conn():
    con = sqlite3.connect(DB_PATH, isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA foreign_keys=ON;")
    return con


def init_db(path: str):
    global DB_PATH
    DB_PATH = path
    con = _conn()
    cur = con.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS uploads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tg_file_id TEXT,
        file TEXT,
        title TEXT,
        description TEXT,
        tags TEXT,
        channels TEXT,
        scheduled_at TEXT,      -- ISO UTC time the job is scheduled to run
        uploaded_at TEXT,       -- ISO UTC time actually uploaded
        status TEXT,            -- 'scheduled' | 'uploaded' | 'failed'
        error TEXT,
        seq_no INTEGER
    )
    """)
    # Lightweight migrations (in case table existed)
    for col in ["tg_file_id", "channels", "uploaded_at", "error", "seq_no", "file_hash"]:
        try:
            cur.execute(f"ALTER TABLE uploads ADD COLUMN {col} TEXT")
        except sqlite3.OperationalError:
            pass
    con.commit()
    con.close()


def log_new_job(
    *,
    tg_file_id: str,
    local_file: Optional[str],
    title: str,
    description: str,
    tags: List[str],
    channels: List[str],
    scheduled_at: dt.datetime,
    status: str,
    seq_no: int,
    file_hash: str | None = None,
    uploaded_at: Optional[dt.datetime] = None,
    error: Optional[str] = None,
):
    con = _conn()
    con.execute(
        """
        INSERT INTO uploads (tg_file_id, file, title, description, tags, channels,
                             scheduled_at, uploaded_at, status, error, seq_no, file_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (
            tg_file_id,
            local_file,
            title,
            description,
            ",".join(tags),
            ",".join(channels),
            _iso(scheduled_at),
            _iso(uploaded_at) if uploaded_at else None,
            status,
            (error or "")[:500] if error else None,
            seq_no,
            file_hash
        ),
    )
    con.close()


def check_if_hash_exists(file_hash: str) -> Optional[dt.date]:
    """Returns date of first upload if hash exists, else None."""
    if not file_hash:
        return None
    con = _conn()
    cur = con.execute("SELECT scheduled_at FROM uploads WHERE file_hash = ? LIMIT 1", (file_hash,))
    row = cur.fetchone()
    con.close()
    if row:
        try:
            return dt.datetime.fromisoformat(row[0]).date()
        except ValueError:
            return None
    return None


def mark_uploaded(job_id: int, when: dt.datetime):
    con = _conn()
    con.execute("""
        UPDATE uploads SET status='uploaded', uploaded_at=? WHERE id=?
    """, (_iso(when), job_id))
    con.close()


def mark_failed(job_id: int, error_text: str):
    con = _conn()
    con.execute("UPDATE uploads SET status='failed', error=? WHERE id=?", (error_text[:500], job_id))
    con.close()


def reschedule(job_id: int, new_time: dt.datetime, reason: Optional[str] = None):
    con = _conn()
    con.execute("""
        UPDATE uploads SET status='scheduled', scheduled_at=?, error=? WHERE id=?
    """, (_iso(new_time), reason, job_id))
    con.close()


def count_uploaded_on(date_utc: dt.date) -> int:
    con = _conn()
    like = date_utc.isoformat() + "%"
    cur = con.execute("""
        SELECT COUNT(*) FROM uploads
        WHERE status='uploaded' AND uploaded_at LIKE ?
    """, (like,))
    c = int(cur.fetchone()[0])
    con.close()
    return c


def count_scheduled_on(date_utc: dt.date) -> int:
    con = _conn()
    like = date_utc.isoformat() + "%"
    cur = con.execute("""
        SELECT COUNT(*) FROM uploads
        WHERE status='scheduled' AND scheduled_at LIKE ?
    """, (like,))
    c = int(cur.fetchone()[0])
    con.close()
    return c


def next_seq_no(base: int = 100) -> int:
    con = _conn()
    cur = con.execute("SELECT COALESCE(MAX(seq_no), ?) + 1 FROM uploads", (base - 1,))
    seq = int(cur.fetchone()[0])
    con.close()
    return seq


def due_jobs(now_utc: dt.datetime) -> List[Tuple]:
    con = _conn()
    cur = con.execute(
        """
        SELECT id, tg_file_id, title, description, tags, channels
        FROM uploads
        WHERE status='scheduled' AND scheduled_at <= ?
        ORDER BY scheduled_at ASC, id ASC
    """, (_iso(now_utc),))
    rows = cur.fetchall()
    con.close()
    return rows


def _iso(x: dt.datetime) -> str:
    if x.tzinfo is None:
        x = x.replace(tzinfo=dt.timezone.utc)
    return x.astimezone(dt.timezone.utc).isoformat()
