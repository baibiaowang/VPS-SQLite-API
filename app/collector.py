from __future__ import annotations
import argparse, json, logging, random, threading, time, uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import requests
from .config import EASTMONEY_URL, PAGE_SIZE, RAW_DIR, USER_AGENT, BASE_DIR
from .db import connect, get_settings, init_db, insert_announcement, utc_now, set_settings, request_count_today, record_request

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("collector")
_request_lock = threading.Lock()
_http_semaphore = threading.Semaphore(2)
_last_request = 0.0
_file_lock = None

def settings():
    s = get_settings()
    string_keys={"schedule_start_time","backup_time","cooldown_until","collector_status","collector_run_id",
                 "collector_started_at","collector_finished_at","collector_target","collector_error"}
    return {k: int(v) if k not in string_keys else v for k,v in s.items()}

def acquire_run_lock():
    global _file_lock
    lock_path = BASE_DIR / "data" / "collector.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock_path, "a+")
    try:
        import fcntl
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (ImportError, BlockingIOError):
        fh.close()
        return None
    _file_lock = fh
    return fh

def release_run_lock():
    global _file_lock
    if _file_lock:
        try:
            import fcntl
            fcntl.flock(_file_lock.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        _file_lock.close()
        _file_lock = None

def set_state(**values):
    set_settings(values)

def state_check():
    s = get_settings()
    if s.get("collector_stop_requested") == "1":
        raise RuntimeError("collector stop requested")
    while s.get("collector_pause_requested") == "1":
        set_state(collector_status="paused")
        time.sleep(2)
        s = get_settings()
        if s.get("collector_stop_requested") == "1":
            raise RuntimeError("collector stop requested")
    if s.get("collector_status") == "paused":
        set_state(collector_status="running")
    return s

def throttle(s):
    global _last_request
    with _request_lock:
        today = date.today().isoformat()
        limit = int(s["daily_request_limit"])
        if request_count_today() >= limit:
            raise RuntimeError("daily request limit reached")
        cooldown = s.get("cooldown_until","")
        if cooldown:
            try:
                if datetime.fromisoformat(cooldown) > datetime.now(timezone.utc):
                    raise RuntimeError("collector cooldown active")
            except ValueError:
                pass
        delay = int(s["request_interval_ms"]) / 1000 + random.uniform(0, int(s["random_jitter_ms"]) / 1000)
        wait = delay - (time.monotonic() - _last_request)
        if wait > 0:
            time.sleep(wait)
        _last_request = time.monotonic()
        record_request()

def fetch_page(target_date, page, s):
    global _http_semaphore
    _http_semaphore = threading.Semaphore(max(1, min(int(s["max_concurrency"]), 8)))
    params={"sr":"-1","page_size":PAGE_SIZE,"page_index":page,"ann_type":"A","client_source":"web",
            "begin_time":target_date,"end_time":target_date,"f_node":"0","s_node":"0"}
    last=None
    for attempt in range(int(s["max_retries"])):
        try:
            state_check()
            throttle(s)
            with _http_semaphore:
                r=requests.get(EASTMONEY_URL,params=params,timeout=30,
                               headers={"User-Agent":USER_AGENT,"Accept":"application/json,text/plain,*/*"})
            if r.status_code in (403,429):
                set_state(cooldown_until=(datetime.now(timezone.utc)+timedelta(minutes=15)).isoformat())
                raise requests.HTTPError(f"HTTP {r.status_code}")
            if r.status_code>=500:
                raise requests.HTTPError(f"HTTP {r.status_code}")
            r.raise_for_status()
            payload=r.json()
            if payload.get("success") is False:
                raise RuntimeError(str(payload))
            return page,payload
        except Exception as exc:
            last=exc
            if "cooldown" in str(exc).lower():
                raise
            if attempt+1 >= int(s["max_retries"]):
                raise
            time.sleep(min(int(s["backoff_base_seconds"])*(2**attempt)+random.random(),60))
    raise last

def save_raw(target_date,page,payload):
    folder=RAW_DIR/target_date[:7].replace("-","/")/target_date
    folder.mkdir(parents=True,exist_ok=True)
    (folder/f"page_{page:04d}.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")

def fetch_date(target_date):
    init_db()
    s=settings()
    started=utc_now()
    pages=expected=received=inserted=duplicate=0
    set_state(collector_target=target_date,collector_page="0",collector_total_pages="0")
    try:
        _,payload=fetch_page(target_date,1,s)
        save_raw(target_date,1,payload)
        data=payload.get("data") or {}
        expected=int(data.get("total_hits") or 0)
        pages=1
        set_state(collector_page="1",collector_total_pages=str(max(1,(expected+PAGE_SIZE-1)//PAGE_SIZE)))
        page_payloads=[(1,payload)]
        total_pages=(expected+PAGE_SIZE-1)//PAGE_SIZE
        if total_pages>1:
            with ThreadPoolExecutor(max_workers=max(1,min(int(s["max_concurrency"]),8))) as pool:
                futures=[pool.submit(fetch_page,target_date,p,s) for p in range(2,total_pages+1)]
                for f in as_completed(futures):
                    p,pay=f.result()
                    page_payloads.append((p,pay))
                    set_state(collector_page=str(p))
        page_payloads.sort()
        seen=set()
        with connect() as conn:
            for p,pay in page_payloads:
                state_check()
                if p!=1: save_raw(target_date,p,pay)
                its=(pay.get("data") or {}).get("list") or []
                pages=max(pages,p)
                for item in its:
                    if not isinstance(item,dict): continue
                    code=str(item.get("art_code") or "").strip()
                    if not code or code in seen: continue
                    seen.add(code); received+=1
                    _,new=insert_announcement(conn,item)
                    inserted += int(new); duplicate += int(not new)
            conn.commit()
            conn.execute("""INSERT INTO fetch_logs
            (fetch_date,started_at,finished_at,page_size,pages,expected_count,received_count,inserted_count,duplicate_count,success)
            VALUES (?,?,?,?,?,?,?,?,?,1)""",
            (target_date,started,utc_now(),PAGE_SIZE,pages,expected,received,inserted,duplicate))
            conn.commit()
        set_state(collector_received=str(received),collector_inserted=str(inserted),collector_duplicate=str(duplicate))
        log.info("%s ok expected=%s received=%s new=%s duplicate=%s pages=%s",target_date,expected,received,inserted,duplicate,pages)
        return True
    except Exception as exc:
        with connect() as conn:
            conn.execute("""INSERT INTO fetch_logs
            (fetch_date,started_at,finished_at,page_size,pages,expected_count,received_count,inserted_count,duplicate_count,success,error_message)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (target_date,started,utc_now(),PAGE_SIZE,pages,expected,received,inserted,duplicate,0,str(exc)[:2000]))
            conn.commit()
        set_state(collector_error=str(exc)[:500],collector_received=str(received),
                  collector_inserted=str(inserted),collector_duplicate=str(duplicate))
        log.exception("fetch failed: %s",target_date)
        return False

def run_incremental(days_back=None):
    s=settings()
    days_back=int(s["fetch_days_back"] if days_back is None else days_back)
    today=date.today()
    ok=True
    for offset in range(days_back,-1,-1):
        ok=fetch_date((today-timedelta(days=offset)).isoformat()) and ok
    return ok

def run_backfill(start,end):
    d=date.fromisoformat(start); last=date.fromisoformat(end)
    if d>last: raise ValueError("start date after end date")
    ok=True
    while d<=last:
        ok=fetch_date(d.isoformat()) and ok
        d+=timedelta(days=1)
    return ok

def main():
    parser=argparse.ArgumentParser()
    g=parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--incremental",action="store_true")
    g.add_argument("--backfill",nargs=2,metavar=("START","END"))
    a=parser.parse_args()
    fh=acquire_run_lock()
    if not fh:
        log.warning("another collector run is active; exiting")
        return 2
    run_id=uuid.uuid4().hex[:12]
    set_state(collector_status="running",collector_run_id=run_id,collector_started_at=utc_now(),
              collector_finished_at="",collector_error="",collector_stop_requested="0",
              collector_pause_requested="0",cooldown_until="",collector_page="0",
              collector_total_pages="0",collector_received="0",collector_inserted="0",collector_duplicate="0")
    try:
        ok=run_incremental() if a.incremental else run_backfill(*a.backfill)
        set_state(collector_status="idle" if ok else "error",collector_finished_at=utc_now())
        return 0 if ok else 1
    except Exception as exc:
        set_state(collector_status="error",collector_error=str(exc)[:500],collector_finished_at=utc_now())
        log.exception("collector aborted")
        return 1
    finally:
        release_run_lock()

if __name__=="__main__":
    raise SystemExit(main())
