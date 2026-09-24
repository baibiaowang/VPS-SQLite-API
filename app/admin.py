from __future__ import annotations
import secrets, subprocess, sys
from html import escape
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from .auth import make_session,new_csrf,read_session,verify_password
from .config import DB_PATH,RAW_DIR
from .db import connect,get_settings,set_settings
router=APIRouter()
def layout(title,body): return HTMLResponse(f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)}</title><style>body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f5f6f8;margin:0;color:#1f2937}}.wrap{{max-width:1100px;margin:30px auto;padding:0 18px}}.card{{background:#fff;border-radius:16px;padding:20px;margin:14px 0;box-shadow:0 2px 12px #0001}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px}}label{{display:block;font-size:13px;font-weight:600;margin-bottom:5px}}input,select{{padding:10px;border:1px solid #d1d5db;border-radius:9px;width:100%;box-sizing:border-box}}button{{border:0;border-radius:9px;padding:10px 14px;background:#111827;color:#fff;cursor:pointer;margin:4px}}button.secondary{{background:#64748b}}.muted{{color:#64748b;font-size:13px}}.stat{{font-size:28px;font-weight:700}}table{{width:100%;border-collapse:collapse}}th,td{{padding:9px;border-bottom:1px solid #eee;text-align:left;font-size:13px}}</style></head><body><div class="wrap">{body}</div></body></html>''')
def sess(request): return read_session(request)
@router.get("/admin/login",response_class=HTMLResponse)
def login_page(): return layout("Eastmoney 管理登录",'<div class="card" style="max-width:420px;margin:80px auto"><h1>公告数据库管理</h1><form method="post"><input type="password" name="password" placeholder="管理密码" autocomplete="current-password" required><br><br><button>登录</button></form></div>')
@router.post("/admin/login")
async def login(request:Request,password:str=Form(...)):
    if not verify_password(password): return layout("登录失败",'<div class="card"><h1>密码错误</h1><a href="/admin/login">返回</a></div>')
    response=RedirectResponse("/admin",status_code=303); response.set_cookie("eastmoney_session",make_session(new_csrf()),httponly=True,secure=request.url.scheme=="https",samesite="lax",max_age=86400,path="/"); return response
@router.get("/admin")
def dashboard(request:Request):
    s=sess(request)
    if not s:return RedirectResponse("/admin/login",status_code=303)
    cfg=get_settings()
    with connect() as conn:
        stats={k:conn.execute(q).fetchone()["n"] for k,q in {"announcements":"SELECT COUNT(*) n FROM announcements","stocks":"SELECT COUNT(*) n FROM announcement_stocks","columns":"SELECT COUNT(*) n FROM announcement_columns"}.items()}
        logs=[dict(x) for x in conn.execute("SELECT * FROM fetch_logs ORDER BY id DESC LIMIT 20").fetchall()]
    rows="".join(f"<tr><td>{escape(str(x['fetch_date']))}</td><td>{x['received_count']}</td><td>{x['inserted_count']}</td><td>{x['duplicate_count']}</td><td>{'成功' if x['success'] else '失败'}</td></tr>" for x in logs)
    checked=" checked" if cfg["schedule_enabled"]=="1" else ""
    body=f'''<h1>公告数据库管理面板</h1><p><a href="/admin/logout">退出</a> · <a href="/docs">API 文档</a></p>
<div class="grid"><div class="card"><div class="stat">{stats["announcements"]}</div><div class="muted">公告</div></div><div class="card"><div class="stat">{stats["stocks"]}</div><div class="muted">股票关联</div></div><div class="card"><div class="stat">{stats["columns"]}</div><div class="muted">东方财富栏目</div></div></div>
<div class="card"><h2>采集计划与限速</h2><form method="post" action="/admin/settings"><div class="grid">
<div><label>自动采集</label><input type="checkbox" name="schedule_enabled"{checked}></div>
<div><label>循环频率（分钟）</label><input type="number" name="schedule_interval_minutes" min="5" max="10080" value="{cfg["schedule_interval_minutes"]}"></div>
<div><label>每日开始时间</label><input type="time" name="schedule_start_time" value="{cfg["schedule_start_time"]}"></div>
<div><label>回看天数</label><input type="number" name="fetch_days_back" min="0" max="7" value="{cfg["fetch_days_back"]}"></div>
<div><label>并发请求数</label><input type="number" name="max_concurrency" min="1" max="8" value="{cfg["max_concurrency"]}"></div>
<div><label>请求最小间隔（毫秒）</label><input type="number" name="request_interval_ms" min="100" max="60000" value="{cfg["request_interval_ms"]}"></div>
<div><label>随机抖动（毫秒）</label><input type="number" name="random_jitter_ms" min="0" max="60000" value="{cfg["random_jitter_ms"]}"></div>
<div><label>失败重试次数</label><input type="number" name="max_retries" min="1" max="10" value="{cfg["max_retries"]}"></div>
<div><label>退避基础秒数</label><input type="number" name="backoff_base_seconds" min="1" max="120" value="{cfg["backoff_base_seconds"]}"></div>
<div><label>每日最大请求数</label><input type="number" name="daily_request_limit" min="10" max="100000" value="{cfg["daily_request_limit"]}"></div>
</div><button>保存采集设置</button></form>
<p class="muted">建议默认：并发 2、间隔 500ms、随机抖动 500ms。遇到 403/429 会指数退避；达到每日请求上限自动停止。</p></div>
<div class="card"><h2>运维</h2><form class="inline" method="post" action="/admin/action"><input type="hidden" name="csrf" value="{escape(s["csrf"])}"><input type="hidden" name="action" value="fetch"><button>立即增量抓取</button></form><form class="inline" method="post" action="/admin/action"><input type="hidden" name="csrf" value="{escape(s["csrf"])}"><input type="hidden" name="action" value="backup"><button class="secondary">立即备份</button></form><p class="muted">数据库：{escape(str(DB_PATH))}</p></div>
<div class="card"><h2>最近采集</h2><table><tr><th>日期</th><th>收到</th><th>新增</th><th>重复</th><th>状态</th></tr>{rows}</table></div>'''
    return layout("公告数据库管理",body)
@router.post("/admin/settings")
def save_settings(request:Request, schedule_enabled:str|None=Form(None), schedule_interval_minutes:int=Form(...), schedule_start_time:str=Form(...), fetch_days_back:int=Form(...), max_concurrency:int=Form(...), request_interval_ms:int=Form(...), random_jitter_ms:int=Form(...), max_retries:int=Form(...), backoff_base_seconds:int=Form(...), daily_request_limit:int=Form(...)):
    s=sess(request)
    if not s:return RedirectResponse("/admin/login",status_code=303)
    vals={"schedule_enabled":"1" if schedule_enabled else "0","schedule_interval_minutes":max(5,min(10080,schedule_interval_minutes)),"schedule_start_time":schedule_start_time,"fetch_days_back":max(0,min(7,fetch_days_back)),"max_concurrency":max(1,min(8,max_concurrency)),"request_interval_ms":max(100,min(60000,request_interval_ms)),"random_jitter_ms":max(0,min(60000,random_jitter_ms)),"max_retries":max(1,min(10,max_retries)),"backoff_base_seconds":max(1,min(120,backoff_base_seconds)),"daily_request_limit":max(10,min(100000,daily_request_limit))}
    set_settings(vals); return RedirectResponse("/admin",status_code=303)
@router.post("/admin/action")
def action(request:Request,action:str=Form(...),csrf:str=Form(...)):
    s=sess(request)
    if not s or not secrets.compare_digest(csrf,s.get("csrf","")):return HTMLResponse("Forbidden",status_code=403)
    cmd=["-m","app.collector","--incremental"] if action=="fetch" else ["-m","app.backup"]
    subprocess.Popen([sys.executable,*cmd],cwd="/opt/eastmoney",start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    return RedirectResponse("/admin",status_code=303)
@router.get("/admin/logout")
def logout():
    r=RedirectResponse("/admin/login",status_code=303);r.delete_cookie("eastmoney_session",path="/");return r
