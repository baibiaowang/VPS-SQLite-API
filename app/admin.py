from __future__ import annotations

import os
import secrets
import subprocess
import sys
from html import escape

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .auth import make_session, new_csrf, read_session, verify_password
from .config import DB_PATH, RAW_DIR
from .db import connect

router = APIRouter()

def layout(title, body):
    return HTMLResponse(f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f5f6f8;margin:0;color:#1f2937}}
.wrap{{max-width:1100px;margin:30px auto;padding:0 18px}}
.card{{background:white;border-radius:16px;padding:20px;margin:14px 0;box-shadow:0 2px 12px #0000000d}}
h1{{margin-top:0}} table{{width:100%;border-collapse:collapse}}th,td{{padding:9px;border-bottom:1px solid #eee;text-align:left;font-size:13px}}
button{{border:0;border-radius:9px;padding:9px 14px;background:#111827;color:#fff;cursor:pointer}}button.secondary{{background:#64748b}}
input{{padding:10px;border:1px solid #d1d5db;border-radius:9px;width:100%;box-sizing:border-box}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}}
.stat{{font-size:28px;font-weight:700}} .muted{{color:#64748b;font-size:13px}}
a{{color:#2563eb;text-decoration:none}} form.inline{{display:inline}}
</style></head><body><div class="wrap">{body}</div></body></html>""")

def session_or_login(request):
    s = read_session(request)
    if s is None:
        return None
    return s

@router.get("/admin/login", response_class=HTMLResponse)
def login_page():
    return layout("Eastmoney 管理登录", """
<div class="card" style="max-width:420px;margin:80px auto">
<h1>公告数据库管理</h1><p class="muted">Eastmoney SQLite API</p>
<form method="post">
<input type="password" name="password" placeholder="管理密码" autocomplete="current-password" required>
<br><br><button type="submit">登录</button>
</form></div>""")

@router.post("/admin/login")
async def login(request: Request, password: str = Form(...)):
    if not verify_password(password):
        return layout("登录失败", '<div class="card"><h1>密码错误</h1><a href="/admin/login">返回</a></div>')
    csrf = new_csrf()
    response = RedirectResponse("/admin", status_code=303)
    response.set_cookie(
        "eastmoney_session", make_session(csrf), httponly=True,
        secure=request.url.scheme == "https", samesite="lax", max_age=86400, path="/"
    )
    return response

@router.get("/admin")
def dashboard(request: Request):
    session = session_or_login(request)
    if not session:
        return RedirectResponse("/admin/login", status_code=303)
    with connect() as conn:
        stats = {
            "announcements": conn.execute("SELECT COUNT(*) n FROM announcements").fetchone()["n"],
            "stocks": conn.execute("SELECT COUNT(*) n FROM announcement_stocks").fetchone()["n"],
            "columns": conn.execute("SELECT COUNT(*) n FROM announcement_columns").fetchone()["n"],
        }
        logs = [dict(x) for x in conn.execute(
            "SELECT * FROM fetch_logs ORDER BY id DESC LIMIT 20"
        ).fetchall()]
    rows = "".join(
        f"<tr><td>{escape(str(x['fetch_date']))}</td><td>{x['received_count']}</td>"
        f"<td>{x['inserted_count']}</td><td>{x['duplicate_count']}</td>"
        f"<td>{'成功' if x['success'] else '失败'}</td><td>{escape(str(x.get('error_message') or ''))}</td></tr>"
        for x in logs
    )
    body = f"""
<h1>公告数据库管理面板</h1>
<p><a href="/admin/logout">退出登录</a> · <a href="/docs">API 文档</a></p>
<div class="grid">
<div class="card"><div class="stat">{stats['announcements']}</div><div class="muted">公告</div></div>
<div class="card"><div class="stat">{stats['stocks']}</div><div class="muted">股票关联</div></div>
<div class="card"><div class="stat">{stats['columns']}</div><div class="muted">东方财富栏目</div></div>
</div>
<div class="card">
<h2>运维</h2>
<form class="inline" method="post" action="/admin/action"><input type="hidden" name="csrf" value="{escape(session['csrf'])}"><input type="hidden" name="action" value="fetch"><button>立即增量抓取</button></form>
<form class="inline" method="post" action="/admin/action"><input type="hidden" name="csrf" value="{escape(session['csrf'])}"><input type="hidden" name="action" value="backup"><button class="secondary">立即备份</button></form>
<p class="muted">数据库：{escape(str(DB_PATH))}<br>原始数据：{escape(str(RAW_DIR))}</p>
</div>
<div class="card"><h2>最近抓取</h2>
<table><tr><th>日期</th><th>收到</th><th>新增</th><th>重复</th><th>状态</th><th>错误</th></tr>{rows}</table></div>
"""
    return layout("公告数据库管理", body)

@router.post("/admin/action")
def action(request: Request, action: str = Form(...), csrf: str = Form(...)):
    session = session_or_login(request)
    if not session or not secrets.compare_digest(csrf, session.get("csrf", "")):
        return HTMLResponse("Forbidden", status_code=403)
    if action == "fetch":
        subprocess.Popen([sys.executable, "-m", "app.collector", "--incremental"],
                         cwd="/opt/eastmoney", start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif action == "backup":
        subprocess.Popen([sys.executable, "-m", "app.backup"],
                         cwd="/opt/eastmoney", start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return RedirectResponse("/admin", status_code=303)

@router.get("/admin/logout")
def logout():
    response = RedirectResponse("/admin/login", status_code=303)
    response.delete_cookie("eastmoney_session", path="/")
    return response
