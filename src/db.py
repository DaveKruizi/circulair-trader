"""
SQLite database layer for listing lifecycle tracking.

Tables:
- listings       : individual listing lifecycle per platform
- price_history  : price changes per listing over time
- price_snapshots: daily aggregated price intelligence per set/platform/condition
- rejection_log  : auto-rejected listings with reason (queryable in chat)
"""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

DB_PATH = Path("data/trading.db")


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS listings (
                id          TEXT NOT NULL,
                platform    TEXT NOT NULL,
                set_number  TEXT NOT NULL,
                title       TEXT,
                price       REAL,
                condition_category TEXT,
                url         TEXT,
                image_url   TEXT,
                seller_id   TEXT,
                first_seen  TEXT,
                last_seen   TEXT,
                status      TEXT DEFAULT 'active',
                days_listed_at_disappearance INTEGER,
                match_confidence REAL DEFAULT 0.95,
                PRIMARY KEY (id, platform)
            );

            CREATE TABLE IF NOT EXISTS price_history (
                id       TEXT NOT NULL,
                platform TEXT NOT NULL,
                date     TEXT NOT NULL,
                price    REAL NOT NULL,
                PRIMARY KEY (id, platform, date)
            );

            CREATE TABLE IF NOT EXISTS price_snapshots (
                snapshot_date      TEXT NOT NULL,
                set_number         TEXT NOT NULL,
                platform           TEXT NOT NULL,
                condition_category TEXT NOT NULL,
                active_count       INTEGER DEFAULT 0,
                disappeared_7d     INTEGER DEFAULT 0,
                p10_price          REAL,
                p20_price          REAL,
                p25_price          REAL,
                p50_price          REAL,
                sell_price_fast    REAL,
                sell_price_realistic REAL,
                PRIMARY KEY (snapshot_date, set_number, platform, condition_category)
            );

            CREATE TABLE IF NOT EXISTS rejection_log (
                log_date    TEXT NOT NULL,
                platform    TEXT NOT NULL,
                set_number  TEXT NOT NULL,
                listing_id  TEXT,
                title       TEXT,
                price       REAL,
                reason      TEXT,
                details     TEXT,
                image_url   TEXT DEFAULT '',
                url         TEXT DEFAULT ''
            );

            CREATE INDEX IF NOT EXISTS idx_listings_set
                ON listings(set_number, platform, status);
            CREATE INDEX IF NOT EXISTS idx_listings_status
                ON listings(status, last_seen);
            CREATE INDEX IF NOT EXISTS idx_snapshots_set
                ON price_snapshots(set_number, snapshot_date);
            CREATE INDEX IF NOT EXISTS idx_rejection_date
                ON rejection_log(log_date, set_number);
        """)
        # Migrate existing DBs that predate image_url/url columns
        for col, default in [("image_url", "''"), ("url", "''")] :
            try:
                conn.execute(
                    f"ALTER TABLE rejection_log ADD COLUMN {col} TEXT DEFAULT {default}"
                )
            except Exception:
                pass  # column already exists


def upsert_listing(
    listing_id: str,
    platform: str,
    set_number: str,
    title: str,
    price: float,
    condition_category: str,
    url: str,
    image_url: str,
    seller_id: str,
    today: str,
    match_confidence: float = 0.95,
) -> None:
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT first_seen, price FROM listings WHERE id=? AND platform=?",
            (listing_id, platform),
        ).fetchone()

        if existing:
            conn.execute(
                """UPDATE listings
                   SET title=?, price=?, condition_category=?, url=?, image_url=?,
                       last_seen=?, status='active', match_confidence=?
                   WHERE id=? AND platform=?""",
                (title, price, condition_category, url, image_url, today,
                 match_confidence, listing_id, platform),
            )
            if existing["price"] != price:
                conn.execute(
                    "INSERT OR IGNORE INTO price_history VALUES (?,?,?,?)",
                    (listing_id, platform, today, price),
                )
        else:
            conn.execute(
                """INSERT INTO listings
                   (id, platform, set_number, title, price, condition_category,
                    url, image_url, seller_id, first_seen, last_seen, status, match_confidence)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,'active',?)""",
                (listing_id, platform, set_number, title, price, condition_category,
                 url, image_url, seller_id, today, today, match_confidence),
            )
            conn.execute(
                "INSERT OR IGNORE INTO price_history VALUES (?,?,?,?)",
                (listing_id, platform, today, price),
            )


def mark_disappeared(platform: str, set_number: str, seen_ids: set, today: str) -> int:
    """Mark listings not in seen_ids as disappeared. Returns count marked."""
    with get_connection() as conn:
        active = conn.execute(
            """SELECT id, first_seen FROM listings
               WHERE platform=? AND set_number=? AND status='active'""",
            (platform, set_number),
        ).fetchall()

        count = 0
        for row in active:
            if row["id"] not in seen_ids:
                first_seen = row["first_seen"] or today
                try:
                    days_listed = (
                        datetime.fromisoformat(today) - datetime.fromisoformat(first_seen)
                    ).days
                except Exception:
                    days_listed = None
                conn.execute(
                    """UPDATE listings
                       SET status='disappeared', last_seen=?, days_listed_at_disappearance=?
                       WHERE id=? AND platform=?""",
                    (today, days_listed, row["id"], platform),
                )
                count += 1
        return count


def log_rejection(
    platform: str,
    set_number: str,
    listing_id: str,
    title: str,
    price: float,
    reason: str,
    details: str = "",
    image_url: str = "",
    url: str = "",
) -> None:
    today = datetime.now().date().isoformat()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO rejection_log
               (log_date, platform, set_number, listing_id, title, price, reason, details, image_url, url)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (today, platform, set_number, listing_id, title[:120], price, reason, details,
             image_url, url),
        )


def get_active_listings(set_number: str, platform: str, condition: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT id, price, first_seen, last_seen, title, url, image_url
               FROM listings
               WHERE set_number=? AND platform=? AND condition_category=? AND status='active'
               ORDER BY price""",
            (set_number, platform, condition),
        ).fetchall()
        return [dict(r) for r in rows]


def get_disappeared_listings(
    set_number: str, platform: str, condition: str, max_days: int = 21
) -> list[dict]:
    """Get recently disappeared listings (sold proxy) within max_days of listing."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT price, days_listed_at_disappearance, last_seen
               FROM listings
               WHERE set_number=? AND platform=? AND condition_category=?
               AND status='disappeared'
               AND days_listed_at_disappearance IS NOT NULL
               AND days_listed_at_disappearance <= ?
               AND last_seen >= date('now', '-30 days')
               ORDER BY last_seen DESC""",
            (set_number, platform, condition, max_days),
        ).fetchall()
        return [dict(r) for r in rows]


def save_price_snapshot(
    snapshot_date: str,
    set_number: str,
    platform: str,
    condition_category: str,
    active_count: int,
    disappeared_7d: int,
    p10: Optional[float],
    p20: Optional[float],
    p25: Optional[float],
    p50: Optional[float],
    sell_price_fast: Optional[float],
    sell_price_realistic: Optional[float],
) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO price_snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (snapshot_date, set_number, platform, condition_category,
             active_count, disappeared_7d, p10, p20, p25, p50,
             sell_price_fast, sell_price_realistic),
        )


def get_price_history(
    set_number: str, platform: str, condition_category: str, limit: int = 90
) -> list[dict]:
    """Get historical price snapshots ordered oldest to newest."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT snapshot_date, active_count, sell_price_fast, sell_price_realistic, p50_price
               FROM price_snapshots
               WHERE set_number=? AND platform=? AND condition_category=?
               ORDER BY snapshot_date DESC
               LIMIT ?""",
            (set_number, platform, condition_category, limit),
        ).fetchall()
        return [dict(r) for r in reversed(rows)]


def get_recent_rejections(days: int = 7) -> list[dict]:
    """Return rejection log entries for the last N days."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT log_date, platform, set_number, listing_id, title, price, reason, details
               FROM rejection_log
               WHERE log_date >= date('now', ?)
               ORDER BY log_date DESC, platform, set_number""",
            (f"-{days} days",),
        ).fetchall()
        return [dict(r) for r in rows]


def get_price_too_low_details(days: int = 7) -> list[dict]:
    """Return price_too_low rejections with image/url for dashboard display."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT log_date, platform, set_number, listing_id, title, price, details,
                      image_url, url
               FROM rejection_log
               WHERE reason = 'price_too_low'
                 AND log_date >= date('now', ?)
               ORDER BY set_number, price ASC""",
            (f"-{days} days",),
        ).fetchall()
        return [dict(r) for r in rows]


def get_rejection_summary(days: int = 7) -> dict:
    """Summarize rejections by reason for the last N days."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT reason, COUNT(*) as count
               FROM rejection_log
               WHERE log_date >= date('now', ?)
               GROUP BY reason
               ORDER BY count DESC""",
            (f"-{days} days",),
        ).fetchall()
        return {r["reason"]: r["count"] for r in rows}
