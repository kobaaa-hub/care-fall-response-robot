import base64, io, json, os, sys
from anthropic import Anthropic
from PIL import Image

MODEL = os.environ.get("VLM_MODEL", "claude-sonnet-5-5")
LABELS = ["in_bed", "sitting", "standing", "eating", "absent", "fall_suspected", "uncertain"]
SYSTEM = (
    "あなたは介護施設の巡回ロボットが撮影した居室の画像から、利用者の状態を記録する補助者です。"
    "必ず次のラベルのいずれか1つで答えてください: " + ", ".join(LABELS) + "。"
    "判定規則: ベッドの外で床面に横たわっている→fall_suspected。テーブル前に着座し食器がある→eating。"
    "人が見えない→absent。暗くて輪郭が取れない→uncertain。迷ったら安全側(fall_suspected)に倒してください。"
    "複数の画像は同じ部屋を角度を変えて撮ったものなので、総合して1つの判定にしてください。"
    "出力は次のJSONオブジェクト1つだけ。説明文や前置きは書かないでください: "
    '{"state": ラベル, "confidence": 0.0-1.0, "evidence": "20字以内の根拠", "person_visible": true/false}'
)

def encode(path, max_edge=640):
    img = Image.open(path).convert("RGB")
    img.thumbnail((max_edge, max_edge))
    buf = io.BytesIO(); img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()

def text_of(msg):
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()

def judge(paths):
    content = []
    for i, p in enumerate(paths, 1):
        content.append({"type": "text", "text": f"Image {i}:"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": encode(p)}})
    content.append({"type": "text", "text": "上の画像から利用者の状態を判定し、JSONオブジェクトだけを返してください。"})
    client = Anthropic(default_headers={"Accept-Encoding": "gzip"})
    messages = [{"role": "user", "content": content}]
    for attempt in (1, 2):
        msg = client.messages.create(model=MODEL, max_tokens=1500, system=SYSTEM, messages=messages)
        text = text_of(msg)
        if "{" in text and "}" in text:
            try:
                result = json.loads(text[text.find("{"): text.rfind("}") + 1])
                if result.get("state") in LABELS:
                    return result, msg
            except json.JSONDecodeError:
                pass
        print(f"[試行{attempt}] JSONが取れませんでした。返事: {text!r}", file=sys.stderr)
        if attempt == 1:
            messages += [{"role": "assistant", "content": text or "(空)"},
                         {"role": "user", "content": "JSONオブジェクトだけを返してください。"}]
    sys.exit("VLMがJSONを返しませんでした。上の返事の内容を貼って相談してください。")

def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY が設定されていません。`source ~/.bashrc` を試してください。")
    paths = sys.argv[1:]
    if not paths:
        sys.exit("使い方: python3 test_vlm.py 画像.jpg [画像2.jpg ...]")
    result, msg = judge(paths)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"model: {msg.model} / tokens in: {msg.usage.input_tokens} out: {msg.usage.output_tokens}")

if __name__ == "__main__":
    main()
