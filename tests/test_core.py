import os
import tempfile
import unittest
from datetime import datetime, timedelta

_TMP = tempfile.TemporaryDirectory()
os.environ["EASTMONEY_BASE_DIR"] = _TMP.name
os.environ["EASTMONEY_DB"] = os.path.join(_TMP.name, "data", "eastmoney.db")

from app import db
from app.scheduler import due


class CoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()

    def test_request_limit_is_atomic(self):
        self.assertTrue(db.reserve_request_slot(2))
        self.assertTrue(db.reserve_request_slot(2))
        self.assertFalse(db.reserve_request_slot(2))
        self.assertEqual(db.request_count_today(), 2)

    def test_duplicate_announcement_refreshes_metadata_and_relations(self):
        item = {
            "art_code": "TEST001",
            "title": "旧标题",
            "notice_date": "2026-09-24",
            "codes": [{"stock_code": "000001", "short_name": "旧名"}],
            "columns": [{"column_code": "C1", "column_name": "栏目1"}],
        }
        with db.connect() as conn:
            ann_id, inserted = db.insert_announcement(conn, item)
            conn.commit()
            self.assertTrue(inserted)
            item["title"] = "新标题"
            item["codes"][0]["short_name"] = "新名"
            db.insert_announcement(conn, item)
            conn.commit()
            row = conn.execute(
                "SELECT title FROM announcements WHERE id=?", (ann_id,)
            ).fetchone()
            stock = conn.execute(
                "SELECT stock_name FROM announcement_stocks WHERE announcement_id=?",
                (ann_id,),
            ).fetchone()
        self.assertEqual(row["title"], "新标题")
        self.assertEqual(stock["stock_name"], "新名")

    def test_scheduler_does_not_overlap_running_collector(self):
        now = datetime.now()
        settings = {
            "schedule_enabled": "1",
            "schedule_interval_minutes": "5",
            "schedule_start_time": "00:00",
            "collector_status": "running",
            "last_scheduled_run": "",
        }
        self.assertFalse(due(settings, now))

    def test_scheduler_respects_interval(self):
        now = datetime.now()
        settings = {
            "schedule_enabled": "1",
            "schedule_interval_minutes": "30",
            "schedule_start_time": "00:00",
            "collector_status": "idle",
            "last_scheduled_run": (now - timedelta(minutes=10)).isoformat(),
        }
        self.assertFalse(due(settings, now))


if __name__ == "__main__":
    unittest.main()
