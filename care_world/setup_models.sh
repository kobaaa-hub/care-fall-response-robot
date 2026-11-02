#!/usr/bin/env bash
# 人物モデル（person_standing）を ~/.gazebo/models に入れる。最初に1回だけ実行する。
# Gazeboの公式モデル集（GitHubの osrf/gazebo_models）から必要なものだけ取ってくる。
set -e
DEST="$HOME/.gazebo/models"
mkdir -p "$DEST"

if [ -f "$DEST/person_standing/model.sdf" ]; then
  echo "person_standing はもう入っています: $DEST/person_standing"
  exit 0
fi

if ! command -v git >/dev/null 2>&1; then
  echo "git が無いので入れます（パスワードは ubuntu）"
  sudo apt install -y git
fi

TMP="$(mktemp -d)"
echo "人物モデルを取得中..."
git clone --depth 1 --filter=blob:none --sparse https://github.com/osrf/gazebo_models.git "$TMP/gazebo_models"
git -C "$TMP/gazebo_models" sparse-checkout set person_standing
cp -r "$TMP/gazebo_models/person_standing" "$DEST/"
rm -rf "$TMP"
echo "完了: $DEST/person_standing"
