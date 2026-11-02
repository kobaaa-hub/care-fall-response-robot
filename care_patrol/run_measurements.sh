#!/usr/bin/env bash
# 計測を自動で回す（ブラウザのLXTerminalから打つ。放っておけば終わる）。
# 職員の指示は待たない（--staff-wait 0）。結果は ~/ros2_ws/results/care.db に溜まる。
#
#   bash ~/ros2_ws/src/care_patrol/run_measurements.sh all      昼3枚・夜3枚・夜1枚 × 7シナリオ = 21巡回（約2.5時間）
#   bash ~/ros2_ws/src/care_patrol/run_measurements.sh day      昼3枚 × 7（約50分）
#   bash ~/ros2_ws/src/care_patrol/run_measurements.sh night3   夜3枚 × 7
#   bash ~/ros2_ws/src/care_patrol/run_measurements.sh night1   夜1枚 × 7
#   bash ~/ros2_ws/src/care_patrol/run_measurements.sh nightlit 夜・常夜灯あり3枚 × 7（約50分）
#   bash ~/ros2_ws/src/care_patrol/run_measurements.sh quick    S1 と N1 だけ昼3枚（動作確認、約15分）
# 途中で止めるときは Ctrl + C を2回。終わったら report.py で集計する。
set +u
SET="${1:-all}"
SCENARIOS=(S1 S2 S3 S4 S5 N1 N2)
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="$HOME/ros2_ws/results"; mkdir -p "$OUT"
LOG="$OUT/measurements_$(date +%Y%m%d_%H%M%S).log"

case "$SET" in
  all)    CONDS=("day 3" "night 3" "night 1") ;;
  day)    CONDS=("day 3") ;;
  night3) CONDS=("night 3") ;;
  night1) CONDS=("night 1") ;;
  nightlit) CONDS=("night_lit 3") ;;
  quick)  CONDS=("day 3"); SCENARIOS=(S1 N1) ;;
  *) echo "引数は all / day / night3 / night1 / nightlit / quick"; exit 1 ;;
esac

total=$(( ${#CONDS[@]} * ${#SCENARIOS[@]} )); i=0; t0=$(date +%s)
echo "計測開始: $total 巡回（ログ: $LOG）"
for cond in "${CONDS[@]}"; do
  set -- $cond; LT="$1"; N="$2"
  for sc in "${SCENARIOS[@]}"; do
    i=$((i+1)); el=$(( $(date +%s) - t0 ))
    echo; echo "===== [$i/$total] scenario=$sc lighting=$LT images=$N  (経過 $((el/60))分) ====="
    for attempt in 1 2; do
      bash "$HERE/run_patrol.sh" "$sc" "$LT" "$N" --staff-wait 0 --note "measure_$SET" 2>&1 | tee -a "$LOG" | grep -E "^\| |一致|初動対応|到達できません|カメラ画像|Traceback|rror|号室へ|庭へ"
      rc=${PIPESTATUS[0]}
      [ "$rc" = 0 ] && break
      echo "  （起動に失敗したので30秒おいてやり直します: $attempt/2）"; sleep 30
    done
  done
done
echo; echo "計測終了（$(( ($(date +%s) - t0) / 60 ))分）。集計: python3 ~/ros2_ws/src/care_patrol/care_patrol/report.py"
