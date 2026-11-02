#!/usr/bin/env bash
# フロアを起動して巡回を1回行い、終わったら止める（ブラウザのLXTerminalから打つ）。
#   bash ~/ros2_ws/src/care_patrol/run_patrol.sh               S1 を昼、3枚判定で1巡回
#   bash ~/ros2_ws/src/care_patrol/run_patrol.sh S2 night 1    S2 を夜、1枚判定
#   bash ~/ros2_ws/src/care_patrol/run_patrol.sh S1 day 3 --no-vlm   APIを使わず動きだけ確認
#   bash ~/ros2_ws/src/care_patrol/run_patrol.sh S1 day 3 --staff-wait 0   職員を待たず自動で（計測用）
#   bash ~/ros2_ws/src/care_patrol/run_patrol.sh DEMO_GARDEN day 3 --staff-wait 300   デモ撮影（画面で指示する）
set +u
SC="${1:-S1}"; LT="${2:-day}"; N="${3:-3}"
# 先頭3つ（シナリオ・昼夜・枚数）を取り除き、残りを巡回ノードへの追加引数にする
[ $# -gt 0 ] && shift; [ $# -gt 0 ] && shift; [ $# -gt 0 ] && shift   # 残りの "$@" は巡回ノードへ
source /opt/ros/humble/setup.bash
export TURTLEBOT3_MODEL=waffle_pi
export LIBGL_ALWAYS_SOFTWARE=1
if [ -z "$DISPLAY" ]; then for s in /tmp/.X11-unix/X*; do [ -e "$s" ] && export DISPLAY=":${s##*/X}" && break; done; fi
if [ -z "$ANTHROPIC_API_KEY" ] && [ -f ~/.bashrc ]; then eval "$(grep '^export ANTHROPIC_API_KEY=' ~/.bashrc | tail -n 1)"; fi

HERE="$(cd "$(dirname "$0")" && pwd)"
# 職員画面（承認UI）が動いていなければ裏で起動する
if ! (echo > /dev/tcp/127.0.0.1/8080) >/dev/null 2>&1; then
  nohup python3 "$HERE/care_patrol/staff_ui.py" > "$HOME/ros2_ws/results/staff_ui.log" 2>&1 &
  sleep 1
fi
echo "職員画面: コンテナのデスクトップでブラウザを開き http://localhost:8080 （ブラウザが無ければ staff_cli.py）"
WORLD="$HOME/ros2_ws/src/care_world"
OUT="$HOME/ros2_ws/results"; mkdir -p "$OUT"
LOG="$OUT/patrol_$(date +%Y%m%d_%H%M%S).log"

bash "$WORLD/stop_sim.sh" >/dev/null 2>&1
echo "フロアを起動中 (scenario=$SC lighting=$LT) ..."
ros2 launch "$WORLD/launch/care_ward.launch.py" scenario:="$SC" lighting:="$LT" >> "$LOG" 2>&1 &
LAUNCH_PID=$!
ok=0
for i in $(seq 1 24); do   # 最長およそ4分待つ（初回起動は遅い）
  if SNAP_TIMEOUT=8 python3 "$HOME/ros2_ws/vlm_kit/snap.py" /tmp/vlm_probe/p 1 >/dev/null 2>&1; then ok=1; break; fi
  sleep 2
done
if [ "$ok" != 1 ]; then
  echo "カメラ画像が来ません。ログ: $LOG"; ros2 topic list --no-daemon | sed 's/^/  /'
  kill $LAUNCH_PID 2>/dev/null; bash "$WORLD/stop_sim.sh" >/dev/null 2>&1; exit 1
fi
sleep 3
echo "巡回開始（ログ: $LOG）"
python3 "$HERE/care_patrol/patrol_node.py" --images "$N" "$@"
kill $LAUNCH_PID 2>/dev/null
bash "$WORLD/stop_sim.sh" >/dev/null 2>&1
echo "終了"
