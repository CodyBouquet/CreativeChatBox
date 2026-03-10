import sqlite3
import os
from flask import g

DATABASE = os.getenv("DATABASE_PATH", "chat.db")

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db

def init_db():
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE IF NOT EXISTS threads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            deal_id INTEGER NOT NULL,
            title TEXT NOT NULL DEFAULT 'New Thread',
            created_by INTEGER NOT NULL,
            created_by_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL,
            last_activity_at TEXT,
            closed_at TEXT,
            last_read_at TEXT
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id INTEGER NOT NULL REFERENCES threads(id),
            user_id INTEGER NOT NULL,
            user_name TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS participants (
            thread_id INTEGER NOT NULL REFERENCES threads(id),
            user_id INTEGER NOT NULL,
            user_name TEXT NOT NULL,
            PRIMARY KEY (thread_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS read_receipts (
            thread_id INTEGER NOT NULL REFERENCES threads(id),
            user_id INTEGER NOT NULL,
            last_read_at TEXT NOT NULL,
            PRIMARY KEY (thread_id, user_id)
        );

        CREATE INDEX IF NOT EXISTS idx_threads_deal ON threads(deal_id);
        CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages(thread_id);
        CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at);
        CREATE INDEX IF NOT EXISTS idx_threads_activity ON threads(last_activity_at);
    """)
    db.commit()
    db.close()
    print("Database initialized")
