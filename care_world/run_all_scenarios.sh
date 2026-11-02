#!/usr/bin/env bash
# 4つの状況（in_bed / fall_suspected / standing / absent）を順に起動して判定し、結果を1つの表にまとめる。
# Gazeboの画面はブラウザ側に出るが、触らなくてよい（画面なしだとカメラが動かない環境のため）。
#
#   bash ~/ros2_ws/src/care_world/run_all_scenarios.sh            昼で4つ
#   bash ~/ros2_ws/src/care_world/run_all_scenarios.sh night      夜で4つ
#   bash ~/ros2_ws/src/care_world/run_all_scenarios.sh day 1      昼、1枚判定で4つ（既定は3枚）
#   GUI=false bash ~/ros2_ws/src/care_world/run_all_scenarios.sh  画面なしで回す（カメラが出る環境のみ）
#
# 結果は ~/ros2_ws/results/layer1_<day|night>_<日時>.md と .jsonl に残る。
set +u
LIGHTING="${1:-day}"
N="${2:-3}"
GUI="${GUI:-true}"    # この環境ではカメラの描画にGazeboの画面が必要なので、既定は画面あり
SCENARIOS=(in_bed fall_suspected standing absent)
WAIT_SEC=120       # Gazeboの読み込み待ち（重ければ増やす）

source /opt/ros/humble/setup.bash
export TURTLEBOT3_MODEL=waffle_pi
export LIBGL_ALWAYS_SOFTWARE=1
# Gazeboのカメラは描画に画面（Xディスプレイ）が必要。Macから docker exec で入った
# ターミナルには DISPLAY が無いので、ブラウザのデスクトップが使っている画面を探して設定する。
if [ -z "${DISPLAY:-}" ]; then
  for s in /tmp/.X11-unix/X*; do
    [ -e "$s" ] && export DISPLAY=":${s##*/X}" && break
  done
  echo "DISPLAY を ${DISPLAY:-（見つからず）} に設定"
fi
if [ -z "${ANTHROPIC_API_KEY:-}" ] && [ -f ~/.bashrc ]; then
  eval "$(grep '^export ANTHROPIC_API_KEY=' ~/.bashrc | tail -n 1)"
fi

HERE="$(cd "$(dirname "$0")" && pwd)"
KIT="$HOME/ros2_ws/vlm_kit"
OUT="$HOME/ros2_ws/results"; mkdir -p "$OUT"
STAMP="$(date +%Y%m%d_%H%M%S)"
MD="$OUT/layer1_${LIGHTING}_${STAMP}.md"
JL="$OUT/layer1_${LIGHTING}_${STAMP}.jsonl"
LOG="$OUT/layer1_${LIGHTING}_${STAMP}.log"

stop_all() { bash "$HERE/stop_sim.sh" >/dev/null 2>&1 || true; }

{
  echo "# 層①の判定結果（lighting=$LIGHTING, 枚数=$N, $STAMP）"
  echo
  echo "| scenario（正解） | VLMの判定 | 確信度 | 根拠文 | 一致 |"
  echo "| --- | --- | --- | --- | --- |"
} > "$MD"

hits=0
for sc in "${SCENARIOS[@]}"; do
  echo "=== $sc ==="
  stop_all
  ros2 launch "$HERE/launch/care_room.launch.py" scenario:="$sc" lighting:="$LIGHTING" gui:="$GUI" >> "$LOG" 2>&1 &
  LAUNCH_PID=$!

  # カメラの画像が流れ始めるまで待つ（snap.py に任せる: トピックを探して1枚撮れたら成功）
  ok=0
  for i in $(seq 1 "$((WAIT_SEC / 10))"); do
    if SNAP_TIMEOUT=8 python3 "$KIT/snap.py" /tmp/vlm_probe/p 1 >/dev/null 2>&1; then ok=1; break; fi
    sleep 2
  done
  if [ "$ok" != 1 ]; then
    echo "  カメラ画像が ${WAIT_SEC} 秒以内に来ませんでした。"
    echo "  ログ: $LOG   トピック一覧:"; ros2 topic list --no-daemon 2>/dev/null | sed 's/^/    /'
    echo "| $sc | （起動失敗） | | | × |" >> "$MD"
    kill "$LAUNCH_PID" 2>/dev/null; stop_all; continue
  fi
  sleep 5   # 人物とベッドの描画が落ち着くのを待つ

  rm -rf /tmp/vlm_frames
  mapfile -t FRAMES < <(python3 "$KIT/snap.py" /tmp/vlm_frames/frame "$N" 2>>"$LOG")
  SAVE="$OUT/frames_${LIGHTING}_${STAMP}/$sc"; mkdir -p "$SAVE"; cp /tmp/vlm_frames/*.jpg "$SAVE/" 2>/dev/null || true

  JSON="$(python3 "$KIT/test_vlm.py" "${FRAMES[@]}" 2>>"$LOG" | sed -n '/^{/,/^}/p')"
  if [ -z "$JSON" ]; then
    echo "  VLMの判定に失敗しました。ログ: $LOG"
    echo "| $sc | （判定失敗） | | | × |" >> "$MD"
  else
    state="$(echo "$JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["state"])')"
    conf="$(echo "$JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["confidence"])')"
    ev="$(echo "$JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("evidence",""))')"
    if [ "$state" = "$sc" ]; then mark="○"; hits=$((hits+1)); else mark="×"; fi
    echo "  判定: $state ($conf) $ev → $mark"
    echo "| $sc | $state | $conf | $ev | $mark |" >> "$MD"
    echo "$JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); d.update(truth='$sc', lighting='$LIGHTING', n_images=$N); print(json.dumps(d, ensure_ascii=False))" >> "$JL"
  fi

  kill "$LAUNCH_PID" 2>/dev/null
  stop_all
done

echo >> "$MD"; echo "一致: $hits / ${#SCENARIOS[@]}" >> "$MD"
echo
echo "一致: $hits / ${#SCENARIOS[@]}"
echo "結果: $MD"
echo "撮影画像: $OUT/frames_${LIGHTING}_${STAMP}/"
echo
cat "$MD"
