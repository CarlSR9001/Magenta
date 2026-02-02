#!/usr/bin/env python3
"""Lean SQLite database for tracking notification processing state."""

import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Set

class NotificationDB:
    """Database for tracking notification processing state."""

    def __init__(self, db_path: str = "state/notifications.db"):
        """Initialize the notification database."""
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(exist_ok=True, parents=True)
        self.conn = None
        self._init_db()

    def _init_db(self):
        """Initialize database schema."""
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        
        # Create main notifications table
        # We value URI uniqueness to prevent re-processing
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                uri TEXT PRIMARY KEY,
                indexed_at TEXT,
                processed_at TEXT NOT NULL,
                status TEXT NOT NULL,
                reason TEXT
            )
        """)
        
        # Create index for faster lookups
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_processed_at 
            ON notifications(processed_at DESC)
        """)
        
        self.conn.commit()

    def is_processed(self, uri: str) -> bool:
        """Check if a URI has already been processed."""
        cursor = self.conn.execute("SELECT 1 FROM notifications WHERE uri = ?", (uri,))
        return cursor.fetchone() is not None

    def mark_processed(self, uri: str, status: str = "processed", reason: Optional[str] = None, indexed_at: Optional[str] = None):
        """Mark a notification as processed in the database."""
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute("""
            INSERT OR REPLACE INTO notifications (uri, indexed_at, processed_at, status, reason)
            VALUES (?, ?, ?, ?, ?)
        """, (uri, indexed_at, now, status, reason))
        self.conn.commit()

    def get_all_processed_uris(self) -> Set[str]:
        """Load all processed URIs into memory at startup."""
        cursor = self.conn.execute("SELECT uri FROM notifications")
        return {row["uri"] for row in cursor}

    def close(self):
        """Close the database connection."""
        if self.conn:
            self.conn.close()
