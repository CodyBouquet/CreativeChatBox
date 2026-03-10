from apscheduler.schedulers.background import BackgroundScheduler
import sqlite3
import os
import logging
import requests
from datetime import datetime

logger = logging.getLogger(__name__)

DATABASE = os.getenv("DATABASE_PATH", "chat.db")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:5000")

def get_db():
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    return db

def check_inactivity():
    db = get_db()
    now = datetime.utcnow()

    open_threads = db.execute("""
        SELECT * FROM threads 
        WHERE status = 'open' 
        AND last_activity_at IS NOT NULL
    """).fetchall()

    for thread in open_threads:
        last_activity = datetime.fromisoformat(thread["last_activity_at"])
        hours_inactive = (now - last_activity).total_seconds() / 3600

        # Check if we already sent a 1hr reminder
        reminded = db.execute("""
            SELECT 1 FROM reminder_log WHERE thread_id = ? AND reminder_type = '1hr'
            AND sent_at > datetime('now', '-2 hours')
        """, (thread["id"],)).fetchone()

        if 1 <= hours_inactive < 24 and not reminded:
            send_reminder(thread, db)

        elif hours_inactive >= 24:
            auto_close_thread(thread)

    db.close()

def send_reminder(thread, db):
    # Log the reminder
    try:
        db.execute("""
            CREATE TABLE IF NOT EXISTS reminder_log (
                thread_id INTEGER,
                reminder_type TEXT,
                sent_at TEXT
            )
        """)
        db.execute("""
            INSERT INTO reminder_log (thread_id, reminder_type, sent_at)
            VALUES (?, '1hr', datetime('now'))
        """, (thread["id"],))
        db.commit()

        logger.info(
            f"1hr inactivity reminder for thread {thread['id']} "
            f"on deal {thread['deal_id']}: '{thread['title']}'"
        )

        # Store reminder in messages as a system message
        db.execute("""
            INSERT INTO messages (thread_id, user_id, user_name, content, created_at)
            VALUES (?, 0, 'System', '⚠️ Don't forget to close this conversation when you're done.', datetime('now'))
        """, (thread["id"],))
        db.commit()

    except Exception as e:
        logger.error(f"Failed to send reminder for thread {thread['id']}: {e}")

def auto_close_thread(thread):
    try:
        response = requests.post(
            f"{BACKEND_URL}/threads/{thread['id']}/close",
            json={"user_name": "System", "auto_closed": True}
        )
        if response.ok:
            logger.info(f"Auto-closed thread {thread['id']} after 24hrs inactivity")
        else:
            logger.error(f"Failed to auto-close thread {thread['id']}: {response.text}")
    except Exception as e:
        logger.error(f"Error auto-closing thread {thread['id']}: {e}")

def start_scheduler(app):
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        check_inactivity,
        trigger="interval",
        minutes=15,
        id="inactivity_check",
        replace_existing=True
    )
    scheduler.start()
    logger.info("Inactivity scheduler started — checking every 15 minutes")
    return scheduler
