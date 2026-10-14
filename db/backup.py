"""SQLite online backup and restore utility for EnjoyAnime.

Uses SQLite's online backup API to perform consistent snapshots
without database locking or risk of corrupting active read/write transactions.
"""
import logging
import os
import sqlite3
from pathlib import Path

_log = logging.getLogger(__name__)


def create_backup(source_path: str, backup_path: str, pages: int = -1) -> bool:
    """Creates a consistent online backup of source_path SQLite database into backup_path.
    
    If pages is -1, all pages are copied in a single continuous step.
    """
    if not os.path.exists(source_path):
        raise FileNotFoundError(f"Source database not found: {source_path}")

    Path(backup_path).parent.mkdir(parents=True, exist_ok=True)

    src_conn = sqlite3.connect(source_path)
    dst_conn = sqlite3.connect(backup_path)
    try:
        with dst_conn:
            src_conn.backup(dst_conn, pages=pages)
        _log.info("Backup successfully written to %s", backup_path)
        return True
    finally:
        dst_conn.close()
        src_conn.close()


def restore_backup(backup_path: str, target_path: str) -> bool:
    """Restores database from backup_path into target_path safely."""
    if not os.path.exists(backup_path):
        raise FileNotFoundError(f"Backup file not found: {backup_path}")

    Path(target_path).parent.mkdir(parents=True, exist_ok=True)

    src_conn = sqlite3.connect(backup_path)
    dst_conn = sqlite3.connect(target_path)
    try:
        with dst_conn:
            src_conn.backup(dst_conn, pages=-1)
        _log.info("Database restored successfully to %s", target_path)
        return True
    finally:
        dst_conn.close()
        src_conn.close()
