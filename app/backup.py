from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path

from .config import BACKUP_DIR, BACKUP_DAILY_KEEP, DB_PATH
from .db import connect, init_db

def backup():
    init_db()
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = BACKUP_DIR / f"eastmoney-{stamp}.db"
    with connect() as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        escaped = str(target).replace("'", "''")
        conn.execute(f"VACUUM INTO '{escaped}'")
    return target

def prune():
    files = sorted(BACKUP_DIR.glob("eastmoney-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[BACKUP_DAILY_KEEP:]:
        old.unlink(missing_ok=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.parse_args()
    if not DB_PATH.exists():
        init_db()
    target = backup()
    prune()
    print(target)
