"""巡回ノード（層②）: 待機ステーションから4部屋を順に回り、各部屋の入口で撮影→VLM判定→記録する。

使い方（コンテナ側。care_ward.launch.py でフロアを起動してから）:
    python3 ~/ros2_ws/src/care_patrol/care_patrol/patrol_node.py            通常の巡回（3枚判定）
    python3 ~/ros2_ws/src/care_patrol/care_patrol/patrol_node.py --images 1  1枚判定
    python3 ~/ros2_ws/src/care_patrol/care_patrol/patrol_node.py --rooms 101,104   一部の部屋だけ
    python3 ~/ros2_ws/src/care_patrol/care_patrol/patrol_node.py --no-vlm   撮影だけ（APIを使わない。正解が転倒なら初動対応の動きだけ再現）
    python3 ~/ros2_ws/src/care_patrol/care_patrol/patrol_node.py --staff-wait 0   職員を待たず自動で進める（計測用）
    python3 ~/ros2_ws/src/care_patrol/care_patrol/patrol_node.py --no-respond     通報だけで駆けつけない（層②の動き）

動き:
  ステーション(0,0) → 101の入口 → 撮影・判定 → 廊下へ戻る → 103 → 102 → 104 → ステーションへ戻る
  各部屋では入口から0.6m入った点で部屋の奥を向き、ヨー角を -15°/0°/+15° に振って撮る。
  転倒疑いなら: 近づいて撮り直し（二段階確認）→ 声かけ → /care/alert で通報 → 職員の指示を待つ
  （承認画面 staff_ui.py か staff_cli.py）→ 出入口で職員を迎えて現場まで先導 → 引き継ぎ。
  最後に庭（廊下の東端の出入口の先）も回る。
結果は SQLite（~/ros2_ws/results/care.db）と画面の表に出る。
"""
import argparse
import json
import math
import os
import sys
import time

import cv2
import rclpy
from cv_bridge import CvBridge
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image, LaserScan
from std_msgs.msg import String

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "care_world", "care_world"))
import ward_gen  # noqa: E402
from care_db import CareDB  # noqa: E402

ROOM_ORDER = ["101", "103", "102", "104", "garden"]
DITHER_DEG = (-15, 0, 15)         # 既定の振り角（庭は ward_gen.dither で広め）
LIN_MAX, ANG_MAX = 0.22, 0.9          # waffle_pi の上限に近い安全な値
GOAL_TOL, YAW_TOL = 0.10, 0.06        # 到達判定 [m], [rad]
FRONT_STOP = 0.30                      # 前方これ以下 [m] なら停止して待つ


def wrap(a):
    while a > math.pi: a -= 2 * math.pi
    while a < -math.pi: a += 2 * math.pi
    return a


class Patrol(Node):
    def __init__(self, args):
        super().__init__("care_patrol")
        self.args = args
        self.pose = None            # (x, y, yaw)
        self.scan_front = 9.9
        self.last_img = None
        self.bridge = CvBridge()
        self.cmd = self.create_publisher(Twist, "/cmd_vel", 10)
        self.rec_pub = self.create_publisher(String, "/care/record", 10)
        self.alert_pub = self.create_publisher(String, "/care/alert", 10)
        self.speech_pub = self.create_publisher(String, "/care/speech", 10)
        self.run_id, self.truth = None, {}
        self.create_subscription(Odometry, "/odom", self.on_odom, 20)
        self.create_subscription(LaserScan, "/scan", self.on_scan, qos_profile_sensor_data)
        self.create_subscription(Image, "/camera/image_raw", self.on_image, qos_profile_sensor_data)
        self.vlm = None
        if not args.no_vlm:
            from vlm_client import VlmClient
            self.vlm = VlmClient()
        self.db = CareDB()
        self.dither = DITHER_DEG

    # --- センサ -----------------------------------------------------------------
    def on_odom(self, msg):
        p, q = msg.pose.pose.position, msg.pose.pose.orientation
        yaw = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))
        self.pose = (p.x, p.y, yaw)

    def on_scan(self, msg):
        n = len(msg.ranges)
        if n == 0:
            return
        k = max(1, int(n * 20 / 360))   # 前方 ±20°
        vals = [r for r in (list(msg.ranges[:k]) + list(msg.ranges[-k:])) if msg.range_min < r < msg.range_max]
        self.scan_front = min(vals) if vals else 9.9

    def on_image(self, msg):
        self.last_img = msg

    # --- 低レベルの動き ---------------------------------------------------------------
    def spin(self, dt=0.05):
        rclpy.spin_once(self, timeout_sec=dt)

    def drive(self, lin, ang):
        t = Twist(); t.linear.x = float(lin); t.angular.z = float(ang); self.cmd.publish(t)

    def stop(self):
        self.drive(0, 0); self.spin(0.1)

    def wait_pose(self):
        t0 = time.time()
        while self.pose is None and time.time() - t0 < 20:
            self.spin()
        if self.pose is None:
            raise RuntimeError("/odom が来ません。Gazeboとロボットが起動しているか確認してください")

    def face(self, yaw, timeout=15):
        t0 = time.time()
        while time.time() - t0 < timeout:
            self.spin()
            err = wrap(yaw - self.pose[2])
            if abs(err) < YAW_TOL:
                self.stop(); return True
            self.drive(0, max(-ANG_MAX, min(ANG_MAX, 1.8 * err)))
        self.stop(); return False

    def goto(self, x, y, timeout=90):
        """目的地へ直進する（向きを合わせてから進む。前方に障害物があれば止まって待つ）。"""
        t0 = time.time()
        while time.time() - t0 < timeout:
            self.spin()
            px, py, pyaw = self.pose
            dx, dy = x - px, y - py
            dist = math.hypot(dx, dy)
            if dist < GOAL_TOL:
                self.stop(); return True
            err = wrap(math.atan2(dy, dx) - pyaw)
            if abs(err) > 0.35:                      # 向きが大きくずれているときはその場で回る
                self.drive(0, max(-ANG_MAX, min(ANG_MAX, 1.8 * err)))
                continue
            if self.scan_front < FRONT_STOP:          # 人や物が前にいる → 停止して待つ
                self.drive(0, 0)
                self.get_logger().warn(f"前方 {self.scan_front:.2f}m に障害物。停止して待機")
                time.sleep(0.5)
                continue
            lin = min(LIN_MAX, 0.6 * dist + 0.05)
            self.drive(lin, max(-ANG_MAX, min(ANG_MAX, 1.5 * err)))
        self.stop()
        self.get_logger().error(f"({x:.1f},{y:.1f}) に {timeout}s で到達できませんでした。現在 {self.pose}")
        return False

    # --- 撮影と判定 ---------------------------------------------------------------------
    def capture(self, out_dir, base_yaw, n):
        os.makedirs(out_dir, exist_ok=True)
        angles = self.dither if n >= 3 else ((0,) if n == 1 else (-10, 10))
        paths = []
        for i, d in enumerate(angles[:n]):
            self.face(base_yaw + math.radians(d))
            self.last_img = None
            t0 = time.time()
            while self.last_img is None and time.time() - t0 < 10:
                self.spin()
            if self.last_img is None:
                self.get_logger().error("カメラ画像が来ません")
                break
            img = self.bridge.imgmsg_to_cv2(self.last_img, "bgr8")
            p = os.path.join(out_dir, f"frame_{i}.jpg")
            cv2.imwrite(p, img); paths.append(p)
        self.face(base_yaw)
        return paths

    def judge(self, room, paths, examples):
        if self.vlm is None:
            return {"state": "skipped", "raw_state": "skipped", "confidence": 0.0, "evidence": "--no-vlm",
                    "person_visible": None, "seconds": 0.0, "tokens_in": 0, "tokens_out": 0, "attempt": 0}
        return self.vlm.judge_room(paths, room, examples=examples)

    # --- 声かけ・通報・職員の指示 ----------------------------------------------------------
    def say(self, room, text):
        self.db.add_speech(self.run_id, room, text)
        self.speech_pub.publish(String(data=json.dumps({"room": room, "text": text}, ensure_ascii=False)))
        self.get_logger().info(f"🔊 「{text}」")

    def wait_staff(self, alert_id, timeout, accept=("go", "speak", "approach", "dismiss")):
        """承認画面（staff_ui.py）か staff_cli.py からの指示を待つ。timeout 秒で None。"""
        t0 = time.time()
        while time.time() - t0 < timeout:
            action, _ = self.db.staff_action(alert_id)
            if action in accept:
                return action
            self.spin(0.3)
        return None

    def observe(self, room, img_root, tag, base_yaw, n, examples):
        """その場で撮って判定し、記録する。戻り値 (result, record_id)。"""
        paths = self.capture(os.path.join(img_root, f"{room}_{tag}"), base_yaw, n)
        r = self.judge(room, paths, examples)
        r["n_images"] = len(paths)
        rid = self.db.add_record(self.run_id, room, r, os.path.join(img_root, f"{room}_{tag}"), self.truth.get(room))
        self.rec_pub.publish(String(data=json.dumps(
            dict(r, room=room, run_id=self.run_id, record_id=rid, truth=self.truth.get(room), tag=tag, ts=time.time()),
            ensure_ascii=False)))
        return r, rid

    def respond(self, room, rid, r, img_root, examples):
        """転倒疑いへの初動対応（層③）。二段階確認 → 声かけ → 通報 → 職員の指示 → 先導。
        戻り値: "handled"（引き継ぎ完了）/ "dismissed" / "unconfirmed"（撮り直しで否定）。"""
        label = f"{room}号室" if room != "garden" else "庭"
        t_detect = time.time()
        inc = self.db.open_incident(self.run_id, room, self.truth.get(room), t_detect)
        self.get_logger().warn(f"!!! {label} 転倒の疑い（1回目 {r['confidence']:.2f}）→ 近づいて確認します")

        # 1) 近づいて撮り直す（二段階確認）
        ax, ay, ayaw = ward_gen.approach_pose(room)
        self.goto(ax, ay, timeout=45)
        self.face(ayaw)
        self.db.update_incident(inc, t_arrive_person=time.time())
        r2, rid2 = self.observe(room, img_root, "approach", ayaw, self.args.images, examples)
        confirmed = (r2["state"] == "fall_suspected") or self.args.no_vlm
        self.db.update_incident(inc, t_confirm=time.time(), confirmed=int(confirmed), second_state=r2["state"])
        if not confirmed:
            self.get_logger().info(f"{label}: 近づいて再確認 → {r2['state']}（転倒ではない）。要確認として記録し、巡回を続けます")
            self.db.update_incident(inc, note="second look negative")
            return "unconfirmed"

        # 2) 声かけ → 通報
        self.say(room, "大丈夫ですか。職員を呼びます。動かずにお待ちください。")
        aid = self.db.add_alert(rid2, self.run_id, room)
        self.db.update_incident(inc, t_alert=time.time())
        self.alert_pub.publish(String(data=json.dumps(
            {"alert_id": aid, "record_id": rid2, "run_id": self.run_id, "room": room, "ts": time.time(),
             "evidence": r2["evidence"], "confirmed": True}, ensure_ascii=False)))
        self.get_logger().warn(f"!!! {label} 転倒を確定（2回目 {r2['confidence']:.2f}）→ 職員に通報。指示を待ちます "
                               f"(最長 {self.args.staff_wait:.0f}s。職員画面 http://localhost:8080)")

        # 3) 職員の指示（承認画面）。時間内に無ければ「向かう」とみなす
        action = self.wait_staff(aid, self.args.staff_wait)
        auto = action is None
        if auto:
            action = "go"
        self.db.update_incident(inc, t_staff_action=time.time(), staff_action=action + (" (auto)" if auto else ""))
        self.get_logger().info(f"職員の指示: {action}{'（時間切れのため自動）' if auto else ''}")
        for _ in range(3):   # 声かけ・再接近は何度か受け付ける
            if action == "speak":
                self.say(room, "職員が向かっています。そのままお待ちください。")
                self.db.clear_staff_action(aid)
                action = self.wait_staff(aid, self.args.staff_wait) or "go"
            elif action == "approach":
                r3, _ = self.observe(room, img_root, "recheck", ayaw, self.args.images, examples)
                self.get_logger().info(f"再確認: {r3['state']} ({r3['confidence']:.2f}) {r3['evidence']}")
                self.db.clear_staff_action(aid)
                action = self.wait_staff(aid, self.args.staff_wait) or "go"
            else:
                break
        if action == "dismiss":
            self.say(room, "失礼しました。巡回に戻ります。")
            self.db.update_incident(inc, note="dismissed by staff")
            return "dismissed"

        # 4) 出入口（待機ステーション）へ戻って職員を迎え、現場まで先導する
        self.say(room, "出入口で職員を迎えに行きます。すぐ戻ります。")
        self.db.update_incident(inc, t_escort_start=time.time())
        cx, cy = ward_gen.corridor_point(room)
        self.face(wrap(ayaw + math.pi)); self.goto(cx, cy, timeout=60)
        sx, sy = ward_gen.STATION
        self.goto(sx, sy); self.face(0.0)
        self.get_logger().info(f"出入口で職員を待っています（職員画面の「到着」ボタン、最長 {self.args.staff_wait:.0f}s）")
        arrived = self.wait_staff(aid, self.args.staff_wait, accept=("arrived",))
        self.db.update_incident(inc, t_staff_arrived=time.time())
        self.say(room, f"{label}へご案内します。こちらです。")
        self.goto(cx, cy); self.face(ayaw); self.goto(ax, ay, timeout=45); self.face(ayaw)
        self.db.update_incident(inc, t_escort_done=time.time(),
                                note="escort done" + ("" if arrived else " (staff arrival auto)"))
        self.say(room, "こちらです。引き継ぎます。")
        self.get_logger().info(f"{label}: 先導完了。職員に引き継ぎました")
        return "handled"

    # --- 巡回本体 -----------------------------------------------------------------------
    def run(self):
        self.wait_pose()
        cur = {}
        try:
            with open("/tmp/care_ward_current.json", encoding="utf-8") as f:
                cur = json.load(f)
        except FileNotFoundError:
            self.get_logger().warn("/tmp/care_ward_current.json が無いので正解との照合はしません")
        self.truth = cur.get("states", {})
        scenario, lighting = cur.get("scenario", "?"), cur.get("lighting", "?")
        rooms = self.args.rooms.split(",") if self.args.rooms else ROOM_ORDER
        n = self.args.images
        self.run_id = run_id = self.db.start_run(scenario, lighting, n, self.truth, note=self.args.note)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        img_root = os.path.expanduser(f"~/ros2_ws/results/patrol_{stamp}_run{run_id}")
        examples = self.db.examples() if self.args.use_examples else []
        self.get_logger().info(f"巡回開始 run_id={run_id} scenario={scenario} lighting={lighting} rooms={rooms} "
                               f"images={n} 修正例={len(examples)}件 初動対応={'なし' if self.args.no_respond else 'あり'}")
        t_start = time.time()
        results = []
        handled = False

        for room in rooms:
            label = f"{room}号室" if room != "garden" else "庭"
            cx, cy = ward_gen.corridor_point(room)
            ex, ey, eyaw = ward_gen.entry_pose(room)
            self.get_logger().info(f"--- {label}へ ---")
            if not self.goto(cx, cy):
                break
            self.face(eyaw)
            if not self.goto(ex, ey, timeout=45):
                break
            self.face(eyaw)
            t0 = time.time()
            self.dither = ward_gen.dither(room)
            r, rid = self.observe(room, img_root, "entry", eyaw, n, examples)
            truth = self.truth.get(room)
            mark = "" if truth is None else ("○" if r["state"] == truth else "×")
            self.get_logger().info(f"{label}: {r['state']} ({r['confidence']:.2f}) {r['evidence']} "
                                   f"[{time.time()-t0:.1f}s] {mark}")
            results.append((room, r, truth, mark))

            if r["state"] == "fall_suspected" or (self.args.no_vlm and truth == "fall_suspected"):
                if self.args.no_respond:
                    aid = self.db.add_alert(rid, run_id, room)
                    self.alert_pub.publish(String(data=json.dumps(
                        {"alert_id": aid, "record_id": rid, "run_id": run_id, "room": room, "ts": time.time(),
                         "evidence": r["evidence"]}, ensure_ascii=False)))
                    self.get_logger().warn(f"!!! {label} 転倒の疑い → /care/alert を発行（初動対応なし）")
                else:
                    outcome = self.respond(room, rid, r, img_root, examples)
                    if outcome == "handled":
                        handled = True
                        break    # 引き継いだので巡回はここで終える
            # 廊下へ戻る（後ろ向きに出ると壁に当たるので、向きを変えて前進）
            self.face(wrap(eyaw + math.pi))
            self.goto(cx, cy, timeout=45)

        if not handled:
            sx, sy = ward_gen.STATION
            self.goto(sx, sy)
            self.face(0.0)
        self.db.finish_run(run_id)
        total = time.time() - t_start

        print("\n| 場所 | 正解 | 判定 | 確信度 | 根拠 | 一致 |")
        print("| --- | --- | --- | --- | --- | --- |")
        hits = 0
        for room, r, t, mark in results:
            hits += (mark == "○")
            print(f"| {room} | {t or '-'} | {r['state']} | {r['confidence']:.2f} | {r['evidence']} | {mark} |")
        print(f"\n一致 {hits}/{len(results)}  巡回 {total:.0f}秒  run_id={run_id}  DB={self.db.path}  画像={img_root}")
        inc = self.db.conn.execute("SELECT * FROM incidents WHERE run_id=? ORDER BY incident_id", (run_id,)).fetchall()
        for i in inc:
            d = lambda t: f"+{t - i['t_detect']:.0f}s" if t else "-"
            print(f"初動対応 {i['room']}: 確定 {d(i['t_confirm'])}({'確定' if i['confirmed'] else '否定'}) 通報 {d(i['t_alert'])} "
                  f"指示 {d(i['t_staff_action'])}({i['staff_action'] or '-'}) 人のそば {d(i['t_arrive_person'])} "
                  f"職員到着 {d(i['t_staff_arrived'])} 先導完了 {d(i['t_escort_done'])} {i['note'] or ''}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", type=int, default=3, help="1部屋あたりの撮影枚数（1 または 3）")
    ap.add_argument("--rooms", default="", help="回る部屋をカンマ区切りで（既定: 101,103,102,104）")
    ap.add_argument("--no-vlm", action="store_true", help="VLMを呼ばず撮影だけ")
    ap.add_argument("--use-examples", action="store_true", help="職員の修正例をプロンプトに添える（層C）")
    ap.add_argument("--note", default="", help="runs.note に残すメモ")
    ap.add_argument("--no-respond", action="store_true", help="転倒疑いでも通報だけして初動対応（駆けつけ・先導）をしない")
    ap.add_argument("--staff-wait", type=float, default=45.0,
                    help="職員の指示・到着を待つ秒数。0 にすると待たずに自動で進む（計測用）")
    args = ap.parse_args()
    rclpy.init()
    node = Patrol(args)
    try:
        node.run()
    except KeyboardInterrupt:
        pass
    finally:
        node.stop()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
