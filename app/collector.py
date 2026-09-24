from __future__ import annotations
import argparse, json, logging, random, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
import requests
from .config import EASTMONEY_URL, PAGE_SIZE, RAW_DIR, USER_AGENT
from .db import connect, get_settings, init_db, insert_announcement, utc_now

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("collector")
_request_lock = threading.Lock()
_last_request = 0.0
_requests_today = 0
_request_day = None

def settings():
    s = get_settings()
    return {k:int(v) if k not in ("schedule_start_time","backup_time") else v for k,v in s.items()}

def throttle(s):
    global _last_request, _requests_today, _request_day
    today = date.today()
    with _request_lock:
        if _request_day != today:
            _request_day, _requests_today = today, 0
        if _requests_today >= s["daily_request_limit"]:
            raise RuntimeError("daily request limit reached")
        delay = s["request_interval_ms"] / 1000 + random.uniform(0, s["random_jitter_ms"] / 1000)
        wait = delay - (time.monotonic() - _last_request)
        if wait > 0: time.sleep(wait)
        _last_request = time.monotonic()
        _requests_today += 1

def fetch_page(target_date, page, s):
    params={"sr":"-1","page_size":PAGE_SIZE,"page_index":page,"ann_type":"A","client_source":"web",
            "begin_time":target_date,"end_time":target_date,"f_node":"0","s_node":"0"}
    last=None
    for attempt in range(s["max_retries"]):
        try:
            throttle(s)
            r=requests.get(EASTMONEY_URL,params=params,timeout=30,
                           headers={"User-Agent":USER_AGENT,"Accept":"application/json,text/plain,*/*"})
            if r.status_code in (403,429) or r.status_code>=500:
                raise requests.HTTPError(f"HTTP {r.status_code}")
            r.raise_for_status()
            payload=r.json()
            if payload.get("success") is False: raise RuntimeError(str(payload))
            return page,payload
        except Exception as exc:
            last=exc
            if attempt+1 >= s["max_retries"]: raise
            time.sleep(min(s["backoff_base_seconds"]*(2**attempt)+random.random(),60))
    raise last

def save_raw(target_date,page,payload):
    folder=RAW_DIR/target_date[:7].replace("-","/")/target_date
    folder.mkdir(parents=True,exist_ok=True)
    (folder/f"page_{page:04d}.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")

def fetch_date(target_date):
    init_db(); s=settings(); started=utc_now()
    pages=expected=received=inserted=duplicate=0
    try:
        first_page,payload=fetch_page(target_date,1,s)
        save_raw(target_date,1,payload)
        data=payload.get("data") or {}; items=data.get("list") or []
        expected=int(data.get("total_hits") or 0); pages=1
        page_payloads=[(1,payload)]
        total_pages=(expected+PAGE_SIZE-1)//PAGE_SIZE
        if total_pages>1:
            with ThreadPoolExecutor(max_workers=max(1,min(s["max_concurrency"],8))) as pool:
                futures=[pool.submit(fetch_page,target_date,p,s) for p in range(2,total_pages+1)]
                for f in as_completed(futures):
                    p,pay=f.result(); page_payloads.append((p,pay))
        page_payloads.sort()
        seen=set()
        with connect() as conn:
            for p,pay in page_payloads:
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
        log.info("%s ok expected=%s received=%s new=%s duplicate=%s pages=%s",target_date,expected,received,inserted,duplicate,pages)
        return True
    except Exception as exc:
        with connect() as conn:
            conn.execute("""INSERT INTO fetch_logs
            (fetch_date,started_at,finished_at,page_size,pages,expected_count,received_count,inserted_count,duplicate_count,success,error_message)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (target_date,started,utc_now(),PAGE_SIZE,pages,expected,received,inserted,duplicate,0,str(exc)[:2000]))
            conn.commit()
        log.exception("fetch failed: %s",target_date); return False

def run_incremental(days_back=None):
    s=settings(); days_back=s["fetch_days_back"] if days_back is None else days_back
    today=date.today(); ok=True
    for offset in range(days_back,-1,-1):
        ok=fetch_date((today-timedelta(days=offset)).isoformat()) and ok
    return ok

def run_backfill(start,end):
    d=date.fromisoformat(start); last=date.fromisoformat(end)
    if d>last: raise ValueError("start date after end date")
    ok=True
    while d<=last: ok=fetch_date(d.isoformat()) and ok; d+=timedelta(days=1)
    return ok

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    g=parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--incremental",action="store_true"); g.add_argument("--backfill",nargs=2,metavar=("START","END"))
    a=parser.parse_args()
    raise SystemExit(0 if (run_incremental() if a.incremental else run_backfill(*a.backfill)) else 1)
