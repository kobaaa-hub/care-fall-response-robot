"""職員用の承認画面（層③・⑤）。ブラウザで http://localhost:8080 を開く。

    python3 ~/ros2_ws/src/care_patrol/care_patrol/staff_ui.py

できること:
  - 通報（転倒疑い）を見て、ロボットに指示する: 向かう / 声かけ / 近づく / 誤報
  - 到着ボタン（職員が出入口に着いたことをロボットに伝える → 先導が始まる）
  - 記録の下書きを承認・修正する（修正は次回の判定例として使われる）
  - ロボットのカメラ画像と発話を見る
ロボット側（patrol_node.py）はDBを数秒おきに読んで指示に従う。画面は3秒ごとに自動更新。
"""
import html
import os
import sys
import time

from flask import Flask, redirect, request, send_file

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
from care_db import CareDB, DB_PATH  # noqa: E402

RESULTS_ROOT = os.path.realpath(os.path.expanduser("~/ros2_ws/results"))
LABELS = ["in_bed", "sitting", "standing", "eating", "absent", "fall_suspected", "uncertain"]
JP = {"in_bed": "臥床", "sitting": "座位", "standing": "立位", "eating": "食事中", "absent": "不在",
      "fall_suspected": "転倒の疑い", "uncertain": "判定保留", "skipped": "未判定"}
ACTIONS = [("go", "向かう（出入口で合流）"), ("speak", "声かけ"), ("approach", "近づいて再確認"), ("dismiss", "誤報として閉じる")]

app = Flask(__name__)
db = CareDB(DB_PATH)


def fmt(ts):
    return time.strftime("%H:%M:%S", time.localtime(ts)) if ts else "-"


def mid_image(image_dir):
    if not image_dir or not os.path.isdir(image_dir):
        return None
    imgs = sorted(p for p in os.listdir(image_dir) if p.endswith(".jpg"))
    return os.path.join(image_dir, imgs[len(imgs) // 2]) if imgs else None


@app.route("/img")
def img():
    p = os.path.realpath(request.args.get("p", ""))
    if not p.startswith(RESULTS_ROOT) or not os.path.isfile(p):
        return "not found", 404
    return send_file(p, mimetype="image/jpeg")


@app.route("/act/<int:alert_id>/<action>", methods=["POST"])
def act(alert_id, action):
    if action in ("go", "speak", "approach", "dismiss", "arrived"):
        db.set_staff_action(alert_id, action)
    return redirect("/")


@app.route("/approve/<int:record_id>", methods=["POST"])
def approve(record_id):
    db.approve(record_id)
    return redirect("/")


@app.route("/correct/<int:record_id>", methods=["POST"])
def correct(record_id):
    st = request.form.get("state", "")
    if st in LABELS:
        db.add_correction(record_id, st, request.form.get("comment", ""), request.form.get("example") == "on")
    return redirect("/")


@app.route("/")
def index():
    c = db.conn
    alerts = c.execute(
        "SELECT a.*, r.evidence, r.image_dir, r.confidence FROM alerts a JOIN records r USING(record_id) "
        "ORDER BY a.alert_id DESC LIMIT 5").fetchall()
    recs = c.execute(
        "SELECT r.*, e.truth FROM records r LEFT JOIN evals e USING(record_id) ORDER BY r.record_id DESC LIMIT 12").fetchall()
    speech = c.execute("SELECT * FROM speech ORDER BY speech_id DESC LIMIT 3").fetchall()
    inc = c.execute("SELECT * FROM incidents ORDER BY incident_id DESC LIMIT 3").fetchall()

    def img_tag(d, w=260):
        p = mid_image(d)
        return f"<img src='/img?p={html.escape(p)}' width='{w}' style='border-radius:6px'>" if p else "<i>画像なし</i>"

    out = ["""<!doctype html><meta charset='utf-8'><meta http-equiv='refresh' content='3'>
<title>見守りロボット 職員画面</title>
<style>body{font-family:sans-serif;margin:16px;background:#f6f5f1;color:#222}
h1{font-size:20px} h2{font-size:16px;margin-top:24px} .card{background:#fff;border:1px solid #ddd;border-radius:10px;padding:12px;margin:8px 0}
.alert{border:2px solid #c8473a;background:#fdf0ee} .btn{display:inline-block;padding:6px 10px;margin:3px;border-radius:6px;border:1px solid #888;background:#fff;cursor:pointer}
.go{background:#2e7d6b;color:#fff;border-color:#2e7d6b} .dim{color:#777;font-size:12px} table{border-collapse:collapse;font-size:13px}
td,th{border-bottom:1px solid #e3e3e3;padding:4px 8px;text-align:left} .pill{padding:2px 8px;border-radius:10px;background:#e6efec;font-size:12px}
.fall{background:#f9e1dd;color:#9b2f24}</style>
<h1>見守りロボット 職員画面 <span class='dim'>（3秒ごとに更新）</span></h1>"""]

    out.append("<h2>通報</h2>")
    if not alerts:
        out.append("<div class='card dim'>通報はありません</div>")
    for a in alerts:
        done = a["staff_action"]
        out.append(f"<div class='card alert'><b>{html.escape(a['room'])}号室 転倒の疑い</b> &nbsp; {fmt(a['raised_at'])} "
                   f"&nbsp; 確信度 {a['confidence']:.2f} &nbsp; <span class='dim'>{html.escape(a['evidence'] or '')}</span><br>"
                   f"{img_tag(a['image_dir'])}<br>")
        if done:
            out.append(f"<span class='pill'>指示済み: {html.escape(done)} ({fmt(a['acknowledged_at'])})</span> ")
            if done == "go":
                out.append(f"<form style='display:inline' method='post' action='/act/{a['alert_id']}/arrived'>"
                           f"<button class='btn go'>出入口に到着した（先導を始める）</button></form>")
        else:
            for key, label in ACTIONS:
                cls = "btn go" if key == "go" else "btn"
                out.append(f"<form style='display:inline' method='post' action='/act/{a['alert_id']}/{key}'>"
                           f"<button class='{cls}'>{label}</button></form>")
        out.append("</div>")

    if speech:
        out.append("<h2>ロボットの発話</h2><div class='card'>")
        for s in speech:
            out.append(f"<div><span class='dim'>{fmt(s['ts'])} {html.escape(s['room'])}</span> 「{html.escape(s['text'])}」</div>")
        out.append("</div>")

    if inc:
        out.append("<h2>初動対応の記録</h2><div class='card'><table><tr><th>場所</th><th>検知</th><th>確定</th><th>通報</th>"
                   "<th>職員の指示</th><th>人のそばに到着</th><th>職員到着</th><th>先導完了</th></tr>")
        for i in inc:
            def d(t):  # 検知からの秒数
                return f"+{t - i['t_detect']:.0f}s" if t and i["t_detect"] else "-"
            out.append(f"<tr><td>{html.escape(i['room'])}</td><td>{fmt(i['t_detect'])}</td><td>{d(i['t_confirm'])} "
                       f"{'確定' if i['confirmed'] else ('要確認' if i['confirmed'] == 0 else '')}</td><td>{d(i['t_alert'])}</td>"
                       f"<td>{d(i['t_staff_action'])} {html.escape(i['staff_action'] or '')}</td><td>{d(i['t_arrive_person'])}</td>"
                       f"<td>{d(i['t_staff_arrived'])}</td><td>{d(i['t_escort_done'])}</td></tr>")
        out.append("</table></div>")

    out.append("<h2>記録の下書き（承認・修正）</h2>")
    for r in recs:
        st = r["state"]
        cls = "pill fall" if st == "fall_suspected" else "pill"
        truth = f" <span class='dim'>正解: {JP.get(r['truth'], r['truth'])}</span>" if r["truth"] else ""
        appr = {"approved": "承認済み", "corrected": "修正済み"}.get(r["approval"], "未承認")
        out.append(f"<div class='card'><div><b>{html.escape(r['room'])}</b> {fmt(r['ts'])} "
                   f"<span class='{cls}'>{JP.get(st, st)}</span> 確信度 {r['confidence']:.2f}{truth} "
                   f"<span class='dim'>[{appr}]</span></div><div class='dim'>{html.escape(r['evidence'] or '')}</div>"
                   f"<div style='display:flex;gap:12px;align-items:flex-start;margin-top:6px'>{img_tag(r['image_dir'], 200)}<div>")
        if r["approval"] == "pending":
            out.append(f"<form style='display:inline' method='post' action='/approve/{r['record_id']}'><button class='btn go'>承認</button></form>")
        opts = "".join(f"<option value='{k}' {'selected' if k == st else ''}>{JP[k]}</option>" for k in LABELS)
        out.append(f"<form style='display:inline' method='post' action='/correct/{r['record_id']}'>"
                   f"<select name='state'>{opts}</select> <input name='comment' placeholder='メモ' size='16'> "
                   f"<label><input type='checkbox' name='example' checked> 次回の判定例に使う</label> "
                   f"<button class='btn'>修正して保存</button></form></div></div></div>")
    return "".join(out)


if __name__ == "__main__":
    print(f"職員画面: http://localhost:8080  (DB: {DB_PATH})")
    app.run(host="0.0.0.0", port=8080, debug=False, threaded=True)
