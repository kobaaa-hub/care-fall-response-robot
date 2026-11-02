"""記録DB（SQLite）。巡回・判定・通報・職員の修正をここに溜める。"""
import json
import os
import sqlite3
import time

DB_PATH = os.environ.get("CARE_DB", os.path.expanduser("~/ros2_ws/results/care.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  run_id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at REAL, finished_at REAL,
  scenario TEXT, lighting TEXT, n_images INTEGER, truth_json TEXT, note TEXT
);
CREATE TABLE IF NOT EXISTS records (
  record_id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER, ts REAL, room TEXT,
  state TEXT, raw_state TEXT, confidence REAL, evidence TEXT, person_visible INTEGER,
  n_images INTEGER, seconds REAL, tokens_in INTEGER, tokens_out INTEGER, attempt INTEGER,
  image_dir TEXT, approval TEXT DEFAULT 'pending'
);
CREATE TABLE IF NOT EXISTS evals (
  record_id INTEGER PRIMARY KEY, truth TEXT, match INTEGER, false_alarm INTEGER, missed INTEGER
);
CREATE TABLE IF NOT EXISTS alerts (
  alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
  record_id INTEGER, run_id INTEGER, room TEXT, raised_at REAL, acknowledged_at REAL, staff_action TEXT
);
CREATE TABLE IF NOT EXISTS corrections (
  correction_id INTEGER PRIMARY KEY AUTOINCREMENT,
  record_id INTEGER, corrected_state TEXT, comment TEXT, created_at REAL, use_as_example INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS incidents (
  incident_id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER, room TEXT, truth TEXT,
  t_detect REAL, t_confirm REAL, confirmed INTEGER, second_state TEXT,
  t_alert REAL, t_staff_action REAL, staff_action TEXT,
  t_arrive_person REAL, t_escort_start REAL, t_staff_arrived REAL, t_escort_done REAL,
  note TEXT
);
CREATE TABLE IF NOT EXISTS speech (
  speech_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER, room TEXT, ts REAL, text TEXT
);
"""


class CareDB:
    def __init__(self, path=DB_PATH):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.path = path

    def start_run(self, scenario, lighting, n_images, truth, note=""):
        cur = self.conn.execute(
            "INSERT INTO runs(started_at, scenario, lighting, n_images, truth_json, note) VALUES (?,?,?,?,?,?)",
            (time.time(), scenario, lighting, n_images, json.dumps(truth, ensure_ascii=False), note))
        self.conn.commit()
        return cur.lastrowid

    def finish_run(self, run_id):
        self.conn.execute("UPDATE runs SET finished_at=? WHERE run_id=?", (time.time(), run_id))
        self.conn.commit()

    def add_record(self, run_id, room, r, image_dir, truth=None):
        cur = self.conn.execute(
            "INSERT INTO records(run_id, ts, room, state, raw_state, confidence, evidence, person_visible, n_images, "
            "seconds, tokens_in, tokens_out, attempt, image_dir) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, time.time(), room, r["state"], r.get("raw_state"), r["confidence"], r.get("evidence", ""),
             None if r.get("person_visible") is None else int(bool(r["person_visible"])),
             r.get("n_images", 0), r.get("seconds", 0.0), r.get("tokens_in", 0), r.get("tokens_out", 0),
             r.get("attempt", 1), image_dir))
        rid = cur.lastrowid
        if truth is not None:
            self.conn.execute(
                "INSERT OR REPLACE INTO evals(record_id, truth, match, false_alarm, missed) VALUES (?,?,?,?,?)",
                (rid, truth, int(r["state"] == truth),
                 int(r["state"] == "fall_suspected" and truth != "fall_suspected"),
                 int(truth == "fall_suspected" and r["state"] != "fall_suspected")))
        self.conn.commit()
        return rid

    def add_alert(self, record_id, run_id, room):
        cur = self.conn.execute("INSERT INTO alerts(record_id, run_id, room, raised_at) VALUES (?,?,?,?)",
                                (record_id, run_id, room, time.time()))
        self.conn.commit()
        return cur.lastrowid

    # --- 初動対応（層③） -----------------------------------------------------------
    def open_incident(self, run_id, room, truth, t_detect):
        cur = self.conn.execute("INSERT INTO incidents(run_id, room, truth, t_detect) VALUES (?,?,?,?)",
                                (run_id, room, truth, t_detect))
        self.conn.commit()
        return cur.lastrowid

    def update_incident(self, incident_id, **fields):
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        self.conn.execute(f"UPDATE incidents SET {cols} WHERE incident_id=?", (*fields.values(), incident_id))
        self.conn.commit()

    def add_speech(self, run_id, room, text):
        self.conn.execute("INSERT INTO speech(run_id, room, ts, text) VALUES (?,?,?,?)", (run_id, room, time.time(), text))
        self.conn.commit()

    def staff_action(self, alert_id):
        """職員が承認画面で押した指示（go / speak / approach / dismiss / arrived）。無ければ None。"""
        row = self.conn.execute("SELECT staff_action, acknowledged_at FROM alerts WHERE alert_id=?", (alert_id,)).fetchone()
        return (row["staff_action"], row["acknowledged_at"]) if row else (None, None)

    def set_staff_action(self, alert_id, action):
        self.conn.execute("UPDATE alerts SET staff_action=?, acknowledged_at=? WHERE alert_id=?",
                          (action, time.time(), alert_id))
        self.conn.commit()

    def clear_staff_action(self, alert_id):
        self.conn.execute("UPDATE alerts SET staff_action=NULL WHERE alert_id=?", (alert_id,))
        self.conn.commit()

    def add_correction(self, record_id, corrected_state, comment="", use_as_example=True):
        self.conn.execute(
            "INSERT INTO corrections(record_id, corrected_state, comment, created_at, use_as_example) VALUES (?,?,?,?,?)",
            (record_id, corrected_state, comment, time.time(), int(use_as_example)))
        self.conn.execute("UPDATE records SET approval='corrected', state=? WHERE record_id=?", (corrected_state, record_id))
        self.conn.commit()

    def approve(self, record_id):
        self.conn.execute("UPDATE records SET approval='approved' WHERE record_id=?", (record_id,))
        self.conn.commit()

    def examples(self, limit=3):
        """職員の修正のうち「次回の例に使う」ものを新しい順に返す: [(画像パス, 正しいラベル)]。"""
        rows = self.conn.execute(
            "SELECT c.corrected_state, r.image_dir FROM corrections c JOIN records r ON r.record_id=c.record_id "
            "WHERE c.use_as_example=1 ORDER BY c.created_at DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for row in rows:
            d = row["image_dir"]
            if d and os.path.isdir(d):
                imgs = sorted(p for p in os.listdir(d) if p.endswith(".jpg"))
                if imgs:
                    out.append((os.path.join(d, imgs[len(imgs) // 2]), row["corrected_state"]))
        return out

    def summary(self, run_id):
        rows = self.conn.execute(
            "SELECT r.room, r.state, r.confidence, r.evidence, e.truth, e.match, e.false_alarm, e.missed "
            "FROM records r LEFT JOIN evals e ON e.record_id=r.record_id WHERE r.run_id=? ORDER BY r.record_id",
            (run_id,)).fetchall()
        return [dict(x) for x in rows]
