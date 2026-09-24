from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

from .config import EASTMONEY_URL, FETCH_DAYS_BACK, PAGE_SIZE, RAW_DIR, USER_AGENT
from .db import connect, init_db, insert_announcement, utc_now

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("collector")

def fetch_page(session, target_date, page):
    params = {
        "sr": "-1",
        "page_size": PAGE_SIZE,
        "page_index": page,
        "ann_type": "A",
        "client_source": "web",
        "begin_time": target_date,
        "end_time": target_date,
        "f_node": "0",
        "s_node": "0",
    }
    last = None
    for attempt in range(5):
        try:
            r = session.get(EASTMONEY_URL, params=params, timeout=30)
            if r.status_code == 429 or r.status_code >= 500:
                raise requests.HTTPError(f"HTTP {r.status_code}")
            r.raise_for_status()
            data = r.json()
            if data.get("success") is False:
                raise RuntimeError(str(data))
            return data
        except Exception as exc:
            last = exc
            if attempt == 4:
                raise
            time.sleep(min(2 ** attempt, 16))
    raise last

def save_raw(target_date, page, payload):
    folder = RAW_DIR / target_date[:7].replace("-", "/") / target_date
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"page_{page:04d}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

def fetch_date(target_date):
    init_db()
    started = utc_now()
    pages = 0
    expected = 0
    received = 0
    inserted = 0
    duplicate = 0
    seen_codes = set()
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json,text/plain,*/*"})

    try:
        with connect() as conn:
            page = 1
            while True:
                payload = fetch_page(session, target_date, page)
                save_raw(target_date, page, payload)
                data = payload.get("data") or {}
                items = data.get("list") or []
                expected = int(data.get("total_hits") or expected or 0)
                pages = page
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    code = str(item.get("art_code") or "").strip()
                    if not code or code in seen_codes:
                        continue
                    seen_codes.add(code)
                    received += 1
                    _, is_new = insert_announcement(conn, item)
                    if is_new:
                        inserted += 1
                    else:
                        duplicate += 1
                conn.commit()
                if not items or page * PAGE_SIZE >= expected:
                    break
                page += 1
                time.sleep(0.15)

            finished = utc_now()
            conn.execute(
                """INSERT INTO fetch_logs
                (fetch_date,started_at,finished_at,page_size,pages,expected_count,
                 received_count,inserted_count,duplicate_count,success)
                VALUES (?,?,?,?,?,?,?,?,?,1)""",
                (target_date,started,finished,PAGE_SIZE,pages,expected,received,inserted,duplicate)
            )
            conn.commit()
        log.info("%s ok expected=%s received=%s new=%s duplicate=%s pages=%s",
                 target_date, expected, received, inserted, duplicate, pages)
        return True
    except Exception as exc:
        with connect() as conn:
            conn.execute(
                """INSERT INTO fetch_logs
                (fetch_date,started_at,finished_at,page_size,pages,expected_count,
                 received_count,inserted_count,duplicate_count,success,error_message)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (target_date,started,utc_now(),PAGE_SIZE,pages,expected,received,
                 inserted,duplicate,0,str(exc)[:2000])
            )
            conn.commit()
        log.exception("fetch failed: %s", target_date)
        return False

def run_incremental(days_back=FETCH_DAYS_BACK):
    today = date.today()
    ok = True
    for offset in range(days_back, -1, -1):
        ok = fetch_date((today - timedelta(days=offset)).isoformat()) and ok
    return ok

def run_backfill(start, end):
    d = date.fromisoformat(start)
    last = date.fromisoformat(end)
    if d > last:
        raise ValueError("start date after end date")
    ok = True
    while d <= last:
        ok = fetch_date(d.isoformat()) and ok
        d += timedelta(days=1)
    return ok

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--incremental", action="store_true")
    group.add_argument("--backfill", nargs=2, metavar=("START", "END"))
    args = parser.parse_args()
    if args.incremental:
        raise SystemExit(0 if run_incremental() else 1)
    raise SystemExit(0 if run_backfill(*args.backfill) else 1)
