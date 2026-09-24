from __future__ import annotations
from datetime import datetime
import subprocess, sys
from .db import get_settings, set_settings

def due(s, now):
    if s["schedule_enabled"] != "1":
        return False
    interval = max(5, int(s["schedule_interval_minutes"]))
    cooldown = s.get("cooldown_until","")
    if cooldown:
        try:
            if datetime.fromisoformat(cooldown) > now:
                return False
        except ValueError:
            pass
    last = s.get("last_scheduled_run","")
    if last:
        try:
            previous = datetime.fromisoformat(last)
            if previous.tzinfo is None and now.tzinfo is not None:
                previous = previous.replace(tzinfo=now.tzinfo)
            if (now - previous).total_seconds() < interval * 60:
                return False
        except ValueError:
            pass
    start=s["schedule_start_time"]
    hh,mm=map(int,start.split(":"))
    if not last and (now.hour,now.minute)<(hh,mm):
        return False
    return True

def tick():
    s=get_settings()
    now=datetime.now().astimezone()
    if not due(s,now):
        return False
    result=subprocess.run(
        [sys.executable,"-m","app.collector","--incremental"],
        cwd="/opt/eastmoney",
        start_new_session=True,
    )
    if result.returncode == 0:
        set_settings({"last_scheduled_run":now.isoformat()})
        return True
    if result.returncode == 2:
        # Another collector already owns the lock. Do not consume the scheduled slot.
        return False
    return False

if __name__=="__main__":
    tick()
