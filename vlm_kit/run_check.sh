#!/usr/bin/env bash
# ロボットのカメラで撮影 → VLMで判定、を1コマンドで行う。
#   bash run_check.sh            カメラから1枚撮って判定
#   bash run_check.sh 3          カメラから3枚撮って、まとめて1回判定
#   bash run_check.sh 画像.jpg    手元の画像を判定（Gazeboなしで試すとき）
set -e
cd "$(dirname "$0")"
source /opt/ros/humble/setup.bash

# ~/.bashrc はスクリプトからだと途中で読み込みが止まるので、キーの行だけ取り出す
if [ -z "$ANTHROPIC_API_KEY" ] && [ -f ~/.bashrc ]; then
  eval "$(grep '^export ANTHROPIC_API_KEY=' ~/.bashrc | tail -n 1)"
fi

if [ -n "$1" ] && [ -f "$1" ]; then
  FRAMES=("$@")
else
  N="${1:-1}"
  rm -rf /tmp/vlm_frames
  echo "カメラから ${N} 枚撮影中..."
  OUT="$(python3 snap.py /tmp/vlm_frames/frame "$N")"
  mapfile -t FRAMES <<< "$OUT"
  echo "撮影: ${FRAMES[*]}"
fi

echo "VLMで判定中..."
python3 test_vlm.py "${FRAMES[@]}"
