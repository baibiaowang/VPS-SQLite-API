from __future__ import annotations

import json
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse

from .auth import verify_api_token
from .config import PAGE_SIZE
from .db import connect, init_db

app = FastAPI(title="Eastmoney Announcement API", version="1.0.0")

def auth(authorization: Optional[str] = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization[7:].strip()
    if not verify_api_token(token):
        raise HTTPException(status_code=401, detail="invalid bearer token")

def page_args(page: int, page_size: int):
    if page < 1:
        raise HTTPException(400, "page must be >= 1")
    if page_size < 1 or page_size > PAGE_SIZE:
        raise HTTPException(400, f"page_size must be 1..{PAGE_SIZE}")
    return (page - 1) * page_size, page_size

def list_rows(sql, args):
    with connect() as conn:
        return [dict(x) for x in conn.execute(sql, args).fetchall()]

@app.on_event("startup")
def startup():
    init_db()

@app.get("/api/v1/health")
def health(_: None = Depends(auth)):
    return {"ok": True, "service": "eastmoney"}

@app.get("/api/v1/stats")
def stats(_: None = Depends(auth)):
    with connect() as conn:
        a = conn.execute("SELECT COUNT(*) n FROM announcements").fetchone()["n"]
        s = conn.execute("SELECT COUNT(*) n FROM announcement_stocks").fetchone()["n"]
        c = conn.execute("SELECT COUNT(*) n FROM announcement_columns").fetchone()["n"]
        last = conn.execute(
            "SELECT * FROM fetch_logs ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return {"announcements": a, "stock_links": s, "column_links": c,
            "last_fetch": dict(last) if last else None}

@app.get("/api/v1/announcements/latest")
def latest(page: int = Query(1), page_size: int = Query(50), _: None = Depends(auth)):
    offset, limit = page_args(page, page_size)
    with connect() as conn:
        total = conn.execute("SELECT COUNT(*) n FROM announcements").fetchone()["n"]
        rows = conn.execute(
            """SELECT id,art_code,title,title_ch,notice_date,display_time,sort_date,
                      source_type,first_seen_at,last_seen_at
               FROM announcements
               ORDER BY COALESCE(sort_date,notice_date) DESC,id DESC
               LIMIT ? OFFSET ?""",
            (limit, offset)).fetchall()
    return {"page": page, "page_size": limit, "total": total, "items": [dict(x) for x in rows]}

@app.get("/api/v1/announcements")
def announcements(date: Optional[str] = None, page: int = Query(1),
                  page_size: int = Query(50), _: None = Depends(auth)):
    offset, limit = page_args(page, page_size)
    where = ""
    args = []
    if date:
        where = "WHERE notice_date LIKE ?"
        args.append(date + "%")
    with connect() as conn:
        total = conn.execute(f"SELECT COUNT(*) n FROM announcements {where}", args).fetchone()["n"]
        rows = conn.execute(
            f"""SELECT id,art_code,title,title_ch,notice_date,display_time,sort_date,
                       source_type,first_seen_at,last_seen_at
                FROM announcements {where}
                ORDER BY COALESCE(sort_date,notice_date) DESC,id DESC
                LIMIT ? OFFSET ?""",
            args + [limit, offset]).fetchall()
    return {"page": page, "page_size": limit, "total": total, "items": [dict(x) for x in rows]}

@app.get("/api/v1/stocks/{stock_code}/announcements")
def stock_announcements(stock_code: str, page: int = Query(1),
                        page_size: int = Query(50), _: None = Depends(auth)):
    offset, limit = page_args(page, page_size)
    with connect() as conn:
        total = conn.execute(
            "SELECT COUNT(*) n FROM announcement_stocks WHERE stock_code=?", (stock_code,)
        ).fetchone()["n"]
        rows = conn.execute(
            """SELECT a.id,a.art_code,a.title,a.title_ch,a.notice_date,a.display_time,
                      a.sort_date,s.stock_code,s.stock_name,s.inner_code,s.market_code,s.ann_type
               FROM announcements a
               JOIN announcement_stocks s ON s.announcement_id=a.id
               WHERE s.stock_code=?
               ORDER BY COALESCE(a.sort_date,a.notice_date) DESC,a.id DESC
               LIMIT ? OFFSET ?""",
            (stock_code, limit, offset)).fetchall()
    return {"stock_code": stock_code, "page": page, "page_size": limit,
            "total": total, "items": [dict(x) for x in rows]}

@app.get("/api/v1/announcements/{art_code}")
def detail(art_code: str, _: None = Depends(auth)):
    with connect() as conn:
        row = conn.execute("SELECT * FROM announcements WHERE art_code=?", (art_code,)).fetchone()
        if not row:
            raise HTTPException(404, "announcement not found")
        ann = dict(row)
        stocks = [dict(x) for x in conn.execute(
            "SELECT stock_code,stock_name,inner_code,market_code,ann_type FROM announcement_stocks WHERE announcement_id=?",
            (row["id"],)).fetchall()]
        columns = [dict(x) for x in conn.execute(
            "SELECT column_code,column_name FROM announcement_columns WHERE announcement_id=?",
            (row["id"],)).fetchall()]
    try:
        ann["raw"] = json.loads(ann.pop("raw_json"))
    except Exception:
        ann["raw"] = None
    ann["stocks"] = stocks
    ann["columns"] = columns
    return ann

@app.get("/api/v1/search")
def search(q: str = Query(min_length=1, max_length=100), page: int = Query(1),
           page_size: int = Query(50), _: None = Depends(auth)):
    offset, limit = page_args(page, page_size)
    term = "%" + q.replace("%", "\%").replace("_", "\_") + "%"
    with connect() as conn:
        total = conn.execute(
            "SELECT COUNT(*) n FROM announcements WHERE title LIKE ? ESCAPE '\\'", (term,)
        ).fetchone()["n"]
        rows = conn.execute(
            """SELECT id,art_code,title,title_ch,notice_date,display_time,sort_date
               FROM announcements WHERE title LIKE ? ESCAPE '\\'
               ORDER BY COALESCE(sort_date,notice_date) DESC,id DESC
               LIMIT ? OFFSET ?""",
            (term,limit,offset)).fetchall()
    return {"q": q, "page": page, "page_size": limit, "total": total, "items": [dict(x) for x in rows]}
