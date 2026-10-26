"""
backup.py – Online Hot Backup & Integrity Verification Tool for SQLite
=======================================================================
Purpose:
  Safely creates an atomic, byte-for-byte consistent backup of innov8.db
  while the Flask server is running and taking active write requests.

Why NOT simple 'cp innov8.db backup.db'? (Important Viva Point)
  - If another thread or process is writing to the database mid-copy,
    a raw file copy can produce a torn page or corrupt header.
  - Python's sqlite3 provides the `Connection.backup()` method which uses
    SQLite's native online backup API. It locks pages gracefully, retries on
    busy locks, and yields consistent database snapshots.

Features:
  1. Creates timestamped backup file: backups/innov8_backup_YYYYMMDD_HHMMSS.db
  2. Runs 'PRAGMA integrity_check' on the backup to guarantee zero corruption
  3. Backup retention policy: keeps the last N backups (default: 7) to prevent
     disk exhaustion
  4. Returns proper exit codes (0 = success, 1 = error) for shell scripting

Usage:
  python3 backup.py [--max-backups 10]
"""

import os
import sys
import time
import glob
import sqlite3
import argparse

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
SOURCE_DB   = os.path.join(BASE_DIR, "innov8.db")
BACKUP_DIR  = os.path.join(BASE_DIR, "backups")


def create_backup(max_backups: int = 7) -> str:
    """Creates a verified hot backup of innov8.db."""
    if not os.path.exists(SOURCE_DB):
        raise FileNotFoundError(f"Source database not found at {SOURCE_DB}")

    # Ensure backups directory exists
    os.makedirs(BACKUP_DIR, exist_ok=True)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    backup_filename = f"innov8_backup_{timestamp}.db"
    backup_path = os.path.join(BACKUP_DIR, backup_filename)

    print(f"[backup] Starting atomic online backup...")
    print(f"         Source : {SOURCE_DB}")
    print(f"         Target : {backup_path}")

    start_time = time.time()

    # 1. Perform SQLite native hot backup
    src_conn = sqlite3.connect(SOURCE_DB)
    dst_conn = sqlite3.connect(backup_path)

    try:
        # sqlite3 Connection.backup locks pages and transfers without corruption
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()

    elapsed = (time.time() - start_time) * 1000.0
    backup_size = os.path.getsize(backup_path)
    print(f"[backup] Snapshot written in {elapsed:.1f}ms ({backup_size} bytes)")

    # 2. Integrity Verification
    print(f"[backup] Verifying backup integrity via 'PRAGMA integrity_check'...")
    check_conn = sqlite3.connect(backup_path)
    try:
        cursor = check_conn.cursor()
        cursor.execute("PRAGMA integrity_check")
        status = cursor.fetchone()[0]
        if status.lower() != "ok":
            raise RuntimeError(f"Integrity check failed: {status}")
        print(f"[backup] Integrity Check Result: OK ✓")
    finally:
        check_conn.close()

    # 3. Retention policy: Prune old backups
    all_backups = sorted(glob.glob(os.path.join(BACKUP_DIR, "innov8_backup_*.db")))
    if len(all_backups) > max_backups:
        to_delete = all_backups[:-max_backups]
        for old_file in to_delete:
            try:
                os.remove(old_file)
                print(f"[backup] Pruned old backup: {os.path.basename(old_file)}")
            except OSError as e:
                print(f"[backup] Warning: Failed to remove {old_file}: {e}")

    print(f"[backup] Success: Active backups retained = {min(len(all_backups), max_backups)}")
    return backup_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Innov8 SQLite Online Backup Tool")
    parser.add_argument(
        "--max-backups",
        type=int,
        default=7,
        help="Number of historical backup snapshots to retain (default: 7)"
    )
    args = parser.parse_args()

    try:
        created_file = create_backup(max_backups=args.max_backups)
        print(f"\n[backup] Backup completed successfully -> {created_file}\n")
        sys.exit(0)
    except Exception as exc:
        print(f"\n[backup] FATAL ERROR: {exc}\n", file=sys.stderr)
        sys.exit(1)
