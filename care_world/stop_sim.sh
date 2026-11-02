#!/usr/bin/env bash
# 裏に残ったGazeboとロボット関連のプロセスを全部止める。起動し直す前に使う。
pkill -f "ros2 launch" 2>/dev/null || true
pkill -f gzserver 2>/dev/null || true
pkill -f gzclient 2>/dev/null || true
pkill -f robot_state_publisher 2>/dev/null || true
sleep 2
if ps aux | grep -E "gzserver|gzclient" | grep -v grep >/dev/null; then
  echo "まだ残っているので強制終了します"
  pkill -9 -f gzserver 2>/dev/null || true
  pkill -9 -f gzclient 2>/dev/null || true
  sleep 1
fi
ros2 daemon stop >/dev/null 2>&1 || true
echo "停止しました"
