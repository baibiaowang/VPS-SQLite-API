from __future__ import annotations
import secrets, subprocess, sys
from datetime import datetime, timedelta
from html import escape
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from .auth import make_session,new_csrf,read_session,verify_password
from .config import DB_PATH
from .db import connect,get_settings,set_settings,request_count_today
router=APIRouter()

def layout(title,body,refresh=False):
    meta='<meta http-equiv="refresh" content="5">' if refresh else ''
    return HTMLResponse(f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">{meta}<title>{escape(title)}</title><style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f5f6f8;margin:0;color:#1f2937}}
.wrap{{max-width:1150px;margin:30px auto;padding:0 18px}}.card{{background:#fff;border-radius:16px;padding:20px;margin:14px 0;box-shadow:0 2px 12px #0001}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}}label{{display:block;font-size:13px;font-weight:600;margin-bottom:5px}}
input,select{{padding:10px;border:1px solid #d1d5db;border-radius:9px;width:100%;box-sizing:border-box}}
button{{border:0;border-radius:9px;padding:10px 14px;background:#111827;color:#fff;cursor:pointer;margin:4px}}button.secondary{{background:#64748b}}button.warn{{background:#b45309}}button.danger{{background:#b91c1c}}
.muted{{color:#64748b;font-size:13px}}.stat{{font-size:28px;font-weight:700}}.badge{{display:inline-block;padding:5px 10px;border-radius:999px;background:#eef2ff}}
table{{width:100%;border-collapse:collapse}}th,td{{padding:9px;border-bottom:1px solid #eee;text-align:left;font-size:13px}}
</style></head><body><div class="wrap">{body}</div></body></html>''')

def sess(request): return read_session(request)

@router.get("/admin/login",response_class=HTMLResponse)
def login_page():
    return layout("Eastmoney 管理登录",'<div class="card" style="max-width:420px;margin:80px auto"><h1>公告数据库管理</h1><form method="post"><input type="password" name="password" placeholder="管理密码" autocomplete="current-password" required><br><br><button>登录</button></form></div>')

@router.post("/admin/login")
async def login(request:Request,password:str=Form(...)):
    if not verify_password(password):
        return layout("登录失败",'<div class="card"><h1>密码错误</h1><a href="/admin/login">返回</a></div>')
    csrf=new_csrf()
    response=RedirectResponse("/admin",status_code=303)
    response.set_cookie("eastmoney_session",make_session(csrf),httponly=True,secure=request.url.scheme=="https",samesite="lax",max_age=86400,path="/")
    return response

@router.get("/admin")
def dashboard(request:Request):
    s=sess(request)
    if not s:return RedirectResponse("/admin/login",status_code=303)
    cfg=get_settings()
    with connect() as conn:
        stats={k:conn.execute(q).fetchone()["n"] for k,q in {
            "announcements":"SELECT COUNT(*) n FROM announcements",
            "stocks":"SELECT COUNT(*) n FROM announcement_stocks",
            "columns":"SELECT COUNT(*) n FROM announcement_columns"}.items()}
        logs=[dict(x) for x in conn.execute("SELECT * FROM fetch_logs ORDER BY id DESC LIMIT 20").fetchall()]
    status=cfg.get("collector_status","idle")
    running=status in ("running","paused")
    today_req=request_count_today()
    limit=int(cfg.get("daily_request_limit","500"))
    pct=min(100,int(today_req*100/max(1,limit)))
    next_text="未计算"
    if cfg.get("schedule_enabled")=="1":
        try:
            now=datetime.now()
            last=datetime.fromisoformat(cfg.get("last_scheduled_run","")) if cfg.get("last_scheduled_run") else None
            if last:
                nxt=last+timedelta(minutes=int(cfg["schedule_interval_minutes"]))
            else:
                hh,mm=map(int,cfg["schedule_start_time"].split(":"))
                nxt=now.replace(hour=hh,minute=mm,second=0,microsecond=0)
                if nxt<now:nxt+=timedelta(days=1)
            next_text=nxt.strftime("%Y-%m-%d %H:%M")
        except Exception: next_text="—"
    status_label={"idle":"空闲","running":"采集中","paused":"已暂停","error":"上次出错"}.get(status,status)
    rows="".join(f"<tr><td>{escape(str(x['fetch_date']))}</td><td>{x['received_count']}</td><td>{x['inserted_count']}</td><td>{x['duplicate_count']}</td><td>{'成功' if x['success'] else '失败'}</td><td>{escape(str(x.get('error_message') or ''))}</td></tr>" for x in logs)
    checked=" checked" if cfg["schedule_enabled"]=="1" else ""
    csrf=escape(s["csrf"])
    state_card=f'''<div class="card"><h2>当前采集状态</h2><div class="grid">
<div><div class="stat">{status_label}</div><div class="muted">状态</div></div>
<div><div class="stat">{today_req}/{limit}</div><div class="muted">今日请求数 / 上限</div></div>
<div><div class="stat">{cfg.get("collector_page","0")}/{cfg.get("collector_total_pages","0")}</div><div class="muted">当前页 / 总页数</div></div>
<div><div class="stat">{cfg.get("collector_inserted","0")}</div><div class="muted">本次新增</div></div>
<div><div class="stat">{cfg.get("collector_duplicate","0")}</div><div class="muted">本次重复</div></div>
<div><div class="stat">{escape(cfg.get("collector_target","—"))}</div><div class="muted">当前日期</div></div>
</div>
<p class="muted">运行ID：{escape(cfg.get("collector_run_id","—"))} · 开始：{escape(cfg.get("collector_started_at","—"))} · 下次计划：{escape(next_text)}</p>
<p class="muted">错误/提示：{escape(cfg.get("collector_error","") or "无")}</p>
<form method="post" action="/admin/action">
<input type="hidden" name="csrf" value="{csrf}">
<button name="action" value="fetch">立即增量抓取</button>
<button name="action" value="pause" class="warn">暂停</button>
<button name="action" value="resume" class="secondary">继续</button>
<button name="action" value="stop" class="danger">停止当前采集</button>
<button name="action" value="backup" class="secondary">立即备份</button>
</form></div>'''
    settings_card=f'''<div class="card"><h2>采集计划与防封设置</h2><form method="post" action="/admin/settings">
<input type="hidden" name="csrf" value="{csrf}"><div class="grid">
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
<p class="muted">所有采集任务共享一个文件锁；请求计数写入 SQLite，不因进程重启清零。遇到 403/429 自动进入 15 分钟冷却。1 核 1GB VPS 建议并发 1–2。</p></div>'''
    body=f'''<h1>公告数据库管理面板</h1><p><a href="/admin/logout">退出</a> · <a href="/docs">API 文档</a></p>
<div class="grid"><div class="card"><div class="stat">{stats["announcements"]}</div><div class="muted">公告</div></div><div class="card"><div class="stat">{stats["stocks"]}</div><div class="muted">股票关联</div></div><div class="card"><div class="stat">{stats["columns"]}</div><div class="muted">东方财富栏目</div></div></div>
{state_card}{settings_card}
<div class="card"><h2>最近采集</h2><table><tr><th>日期</th><th>收到</th><th>新增</th><th>重复</th><th>状态</th><th>错误</th></tr>{rows}</table></div>'''
    return layout("公告数据库管理",body,refresh=running)

@router.post("/admin/settings")
def save_settings(request:Request, csrf:str=Form(...), schedule_enabled:str|None=Form(None),
                  schedule_interval_minutes:int=Form(...), schedule_start_time:str=Form(...),
                  fetch_days_back:int=Form(...), max_concurrency:int=Form(...),
                  request_interval_ms:int=Form(...), random_jitter_ms:int=Form(...),
                  max_retries:int=Form(...), backoff_base_seconds:int=Form(...),
                  daily_request_limit:int=Form(...)):
    s=sess(request)
    if not s or not secrets.compare_digest(csrf,s.get("csrf","")): return HTMLResponse("Forbidden",status_code=403)
    vals={"schedule_enabled":"1" if schedule_enabled else "0",
          "schedule_interval_minutes":max(5,min(10080,schedule_interval_minutes)),
          "schedule_start_time":schedule_start_time,
          "fetch_days_back":max(0,min(7,fetch_days_back)),
          "max_concurrency":max(1,min(8,max_concurrency)),
          "request_interval_ms":max(100,min(60000,request_interval_ms)),
          "random_jitter_ms":max(0,min(60000,random_jitter_ms)),
          "max_retries":max(1,min(10,max_retries)),
          "backoff_base_seconds":max(1,min(120,backoff_base_seconds)),
          "daily_request_limit":max(10,min(100000,daily_request_limit))}
    set_settings(vals)
    return RedirectResponse("/admin",status_code=303)

@router.post("/admin/action")
def action(request:Request,action:str=Form(...),csrf:str=Form(...)):
    s=sess(request)
    if not s or not secrets.compare_digest(csrf,s.get("csrf","")): return HTMLResponse("Forbidden",status_code=403)
    if action=="pause":
        set_settings({"collector_pause_requested":"1"})
    elif action=="resume":
        set_settings({"collector_pause_requested":"0","collector_stop_requested":"0"})
    elif action=="stop":
        set_settings({"collector_stop_requested":"1","collector_pause_requested":"0"})
    elif action=="fetch":
        set_settings({"collector_stop_requested":"0","collector_pause_requested":"0"})
        subprocess.Popen([sys.executable,"-m","app.collector","--incremental"],cwd="/opt/eastmoney",
                         start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    elif action=="backup":
        subprocess.Popen([sys.executable,"-m","app.backup"],cwd="/opt/eastmoney",
                         start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    return RedirectResponse("/admin",status_code=303)

@router.get("/admin/logout")
def logout():
    r=RedirectResponse("/admin/login",status_code=303)
    r.delete_cookie("eastmoney_session",path="/")
    return r
