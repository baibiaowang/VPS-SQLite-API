from __future__ import annotations
import os
from pathlib import Path

BASE_DIR = Path(os.getenv("EASTMONEY_BASE_DIR", "/opt/eastmoney"))
DB_PATH = Path(os.getenv("EASTMONEY_DB", str(BASE_DIR / "data" / "eastmoney.db")))
RAW_DIR = Path(os.getenv("EASTMONEY_RAW_DIR", str(BASE_DIR / "data" / "raw")))
BACKUP_DIR = Path(os.getenv("EASTMONEY_BACKUP_DIR", str(BASE_DIR / "data" / "backup")))
LOG_DIR = Path(os.getenv("EASTMONEY_LOG_DIR", str(BASE_DIR / "logs")))
API_TOKEN = os.getenv("EASTMONEY_API_TOKEN", "")
ADMIN_PASSWORD_HASH = os.getenv("EASTMONEY_ADMIN_PASSWORD_HASH", "")
SESSION_SECRET = os.getenv("EASTMONEY_SESSION_SECRET", "")
PORT = int(os.getenv("EASTMONEY_PORT", "8080"))
PAGE_SIZE = min(max(int(os.getenv("EASTMONEY_PAGE_SIZE", "100")), 20), 100)
FETCH_DAYS_BACK = max(int(os.getenv("EASTMONEY_FETCH_DAYS_BACK", "1")), 0)
BACKUP_DAILY_KEEP = max(int(os.getenv("EASTMONEY_BACKUP_DAILY_KEEP", "7")), 1)
EASTMONEY_URL = "https://np-anotice-stock.eastmoney.com/api/security/ann"
USER_AGENT = "VPS-SQLite-API/1.0"
