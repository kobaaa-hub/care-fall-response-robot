"""VLM（Claude）に居室の画像を渡して、利用者の状態をJSONで受け取る。

呼び出しはこのファイルに閉じ込める。別社のAPIに替えるときはここだけ差し替える。
返り値の形: {"state", "confidence", "evidence", "person_visible", "seconds", "tokens_in", "tokens_out", "attempt"}
"""
import base64
import io
import json
import os
import time

from anthropic import Anthropic
from PIL import Image

MODEL = os.environ.get("VLM_MODEL", "claude-sonnet-5-5")
THRESHOLD = float(os.environ.get("VLM_THRESHOLD", "0.6"))
MAX_CALLS = int(os.environ.get("VLM_MAX_CALLS_PER_RUN", "40"))
LABELS = ["in_bed", "sitting", "standing", "eating", "absent", "fall_suspected", "uncertain"]

SYSTEM = (
    "あなたは介護施設の巡回ロボットが撮影した居室の画像から、利用者の状態を記録する補助者です。"
    "必ず次のラベルのいずれか1つで答えてください: " + ", ".join(LABELS) + "。"
    "画像は居室か、屋外の庭（小道・芝生・ベンチ）です。"
    "判定規則: ベッドの外の床面や、小道・芝生の上に横たわっている→fall_suspected。テーブル前に着座し食器がある→eating。"
    "ベンチに座っている→sitting。"
    "人が見えない→absent。暗くて輪郭が取れない→uncertain。迷ったら安全側(fall_suspected)に倒してください。"
    "複数の画像は同じ部屋を角度を変えて撮ったものなので、総合して1つの判定にしてください。"
    "出力は次のJSONオブジェクト1つだけ。説明文や前置きは書かないでください: "
    '{"state": ラベル, "confidence": 0.0-1.0, "evidence": "20字以内の根拠", "person_visible": true/false}'
)


def _encode(img, max_edge=640):
    if isinstance(img, str):
        img = Image.open(img)
    img = img.convert("RGB")
    img.thumbnail((max_edge, max_edge))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def _text_of(msg):
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()


class VlmClient:
    def __init__(self):
        self.client = Anthropic(default_headers={"Accept-Encoding": "gzip"})
        self.calls = 0

    def judge_room(self, images, room_id, examples=()):
        """images: PIL画像かパスのリスト。examples: [(画像, 正しいラベル), ...]（職員の修正例、任意）。"""
        if self.calls >= MAX_CALLS:
            raise RuntimeError(f"VLMの呼び出し上限 {MAX_CALLS} に達しました（暴走防止）")
        content = []
        for img, label in examples:
            content += [{"type": "text", "text": f"過去の判定例（職員が確認済み）: 正解は {label}"},
                        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": _encode(img)}}]
        for i, img in enumerate(images, 1):
            content += [{"type": "text", "text": f"Image {i}:"},
                        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": _encode(img)}}]
        content.append({"type": "text", "text": f"{room_id}号室の画像です。利用者の状態を判定し、JSONオブジェクトだけを返してください。"})
        messages = [{"role": "user", "content": content}]
        last = ""
        for attempt in (1, 2):
            t0 = time.time()
            self.calls += 1
            msg = self.client.messages.create(model=MODEL, max_tokens=1500, system=SYSTEM, messages=messages)
            text = _text_of(msg)
            try:
                r = json.loads(text[text.find("{"): text.rfind("}") + 1])
                if r.get("state") not in LABELS:
                    raise ValueError("label out of set")
                c = float(r.get("confidence", -1))
                if not 0.0 <= c <= 1.0:
                    raise ValueError("confidence out of range")
                r.update(confidence=c, evidence=str(r.get("evidence", "")), person_visible=r.get("person_visible"),
                         seconds=round(time.time() - t0, 2), tokens_in=msg.usage.input_tokens,
                         tokens_out=msg.usage.output_tokens, attempt=attempt, raw_state=r["state"])
                if c < THRESHOLD and r["state"] != "fall_suspected":
                    r["state"] = "uncertain"
                return r
            except (ValueError, json.JSONDecodeError) as e:
                last = f"{e}: {text[:120]!r}"
                messages += [{"role": "assistant", "content": text or "(空)"},
                             {"role": "user", "content": "JSONオブジェクトだけを返してください。"}]
        return {"state": "uncertain", "raw_state": "uncertain", "confidence": 0.0, "evidence": f"invalid response: {last}",
                "person_visible": None, "seconds": 0.0, "tokens_in": 0, "tokens_out": 0, "attempt": 2}
