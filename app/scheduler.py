from __future__ import annotations
from datetime import datetime
import subprocess, sys
from .db import get_settings, set_settings

def due(s, now):
    if s["schedule_enabled"] != "1" or s.get("collector_status") == "running": return False
    interval = max(5, int(s["schedule_interval_minutes"]))
    last = s.get("last_scheduled_run","")
    if last:
        try:
            if (now - datetime.fromisoformat(last)).total_seconds() < interval*60: return False
        except ValueError: pass
    start=s["schedule_start_time"]
    hh,mm=map(int,start.split(":"))
    if not last and (now.hour,now.minute)<(hh,mm): return False
    return True

def tick():
    s=get_settings()
    now=datetime.now()
    if due(s,now):
        set_settings({"last_scheduled_run":now.isoformat()})
        subprocess.Popen([sys.executable,"-m","app.collector","--incremental"],
                         cwd="/opt/eastmoney",start_new_session=True)
        return True
    return False

if __name__=="__main__":
    tick()
