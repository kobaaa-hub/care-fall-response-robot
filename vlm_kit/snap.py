"""ロボットのカメラから画像を撮って保存し、終了する。

使い方:
    python3 snap.py [保存先の名前] [枚数]
    例) python3 snap.py /tmp/vlm_frames/frame 3
        -> /tmp/vlm_frames/frame_0.jpg, frame_1.jpg, frame_2.jpg
保存したファイルのパスを1行ずつ表示する（状況の説明は画面のエラー出力側に出る）。

カメラのトピックは自動で探す（/camera/image_raw があればそれを使う）。
環境変数で変えられる:
    SNAP_TOPIC=/別の/image_raw   使うトピックを指定
    SNAP_TIMEOUT=60              画像を待つ秒数（既定30秒）
"""
import os
import sys
import time

import cv2
import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image

DEFAULT_TOPIC = "/camera/image_raw"
TOPIC = os.environ.get("SNAP_TOPIC", "")
TIMEOUT_SEC = float(os.environ.get("SNAP_TIMEOUT", "30"))
DISCOVERY_SEC = 5.0   # トピックを探す時間
INTERVAL_SEC = 0.5    # 複数枚撮るときの間隔


def log(msg):
    print(msg, file=sys.stderr, flush=True)


class Snap(Node):
    def __init__(self, out, n):
        super().__init__("snap")
        self.out, self.n = out, n
        self.saved = []
        self.last = 0.0
        self.bridge = CvBridge()

    def image_topics(self):
        return sorted(name for name, types in self.get_topic_names_and_types()
                      if "sensor_msgs/msg/Image" in types)

    def find_topic(self):
        """画像トピックを探す。見つからなければ (None, [])。"""
        end = time.time() + DISCOVERY_SEC
        topics = []
        while time.time() < end:
            rclpy.spin_once(self, timeout_sec=0.2)
            topics = self.image_topics()
            if DEFAULT_TOPIC in topics:
                return DEFAULT_TOPIC, topics
        if topics:
            raw = [t for t in topics if t.endswith("image_raw")]
            return (raw or topics)[0], topics
        return None, []

    def start(self, topic):
        self.create_subscription(Image, topic, self.on_image, qos_profile_sensor_data)

    def on_image(self, msg):
        now = time.time()
        if len(self.saved) >= self.n or now - self.last < INTERVAL_SEC:
            return
        img = self.bridge.imgmsg_to_cv2(msg, "bgr8")
        path = f"{self.out}_{len(self.saved)}.jpg"
        cv2.imwrite(path, img)
        self.saved.append(path)
        self.last = now


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/vlm_frames/frame"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)

    rclpy.init()
    node = Snap(out, n)
    code = 0
    try:
        if TOPIC:
            topic, topics = TOPIC, node.image_topics()
        else:
            topic, topics = node.find_topic()

        if topic is None:
            log("画像のトピックが1つも見つかりません。次を確認してください:\n"
                "  1) ブラウザのデスクトップでGazeboが起動していて、ロボットが表示されているか\n"
                "  2) Gazeboを起動したターミナルで `echo $TURTLEBOT3_MODEL` が waffle_pi か（burgerにはカメラがない）\n"
                "  3) このターミナルがコンテナの中か（プロンプトが ubuntu@... になっているか）")
            code = 1
        else:
            log(f"カメラのトピック: {topic}")
            node.start(topic)
            start = time.time()
            while rclpy.ok() and len(node.saved) < n and time.time() - start < TIMEOUT_SEC:
                rclpy.spin_once(node, timeout_sec=0.2)
            if len(node.saved) < n:
                log(f"{topic} はあるのに、{TIMEOUT_SEC:.0f}秒待っても画像が届きませんでした。\n"
                    "  Gazeboが一時停止中か、起動直後でまだ重い可能性があります。\n"
                    f"  `ros2 topic hz {topic}` で画像が流れているか確認してください。\n"
                    f"  見つかった画像トピック: {', '.join(topics) or 'なし'}")
                code = 1
    finally:
        node.destroy_node()
        rclpy.shutdown()

    if code:
        sys.exit(code)
    for p in node.saved:
        print(p)


if __name__ == "__main__":
    main()
