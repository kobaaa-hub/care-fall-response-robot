# care_patrol：巡回・判定・初動対応（層②③）

廊下＋居室4部屋＋庭のフロア（care_world/care_ward.launch.py）を TurtleBot3 が巡回し、各場所で撮影→VLM判定→SQLiteに記録する。
転倒の疑いがあれば、近づいて撮り直し（二段階確認）→ 声かけ → 通報 → 職員の指示（承認画面）→ 出入口で職員を迎えて現場まで先導 → 引き継ぎ。

## 構成

| ファイル | 役割 |
| --- | --- |
| `care_patrol/patrol_node.py` | 巡回ノード。移動・撮影・判定・記録・初動対応 |
| `care_patrol/vlm_client.py` | VLM呼び出し（ここだけ差し替えれば別社のAPIにできる） |
| `care_patrol/care_db.py` | SQLite（runs / records / evals / alerts / corrections / incidents / speech） |
| `care_patrol/staff_ui.py` | 職員の承認画面（http://localhost:8080）。通報への指示、到着、記録の承認・修正 |
| `care_patrol/staff_cli.py` | 承認画面の代わりにターミナルから指示する |
| `run_patrol.sh` | フロア起動→承認画面起動→巡回→停止を1コマンドで |

## 使い方（ブラウザのLXTerminal）

    bash ~/ros2_ws/src/care_patrol/run_patrol.sh S1 day 3                  通常（転倒があれば初動対応。職員の指示を45秒待つ）
    bash ~/ros2_ws/src/care_patrol/run_patrol.sh S1 day 3 --staff-wait 0   職員を待たず自動で進む（計測用）
    bash ~/ros2_ws/src/care_patrol/run_patrol.sh S1 day 3 --no-respond     通報だけで駆けつけない（層②の動き）
    bash ~/ros2_ws/src/care_patrol/run_patrol.sh DEMO_GARDEN day 3 --staff-wait 300   デモ撮影（画面で指示する）
    bash ~/ros2_ws/src/care_patrol/run_patrol.sh S1 day 3 --no-vlm          APIを使わず動きだけ

シナリオは `care_world/config/scenarios.yaml`（S1〜S5: 転倒あり、N1〜N2: 転倒なし、DEMO_*: 動画用）。

## 職員の指示

承認画面は `run_patrol.sh` が自動で起動する。コンテナのデスクトップ（ブラウザの http://localhost:6080 の中）でブラウザを開き、
http://localhost:8080 を表示する。通報が出たら「向かう」→ ロボットが出入口へ迎えに来るので「出入口に到着した」を押す → 先導が始まる。

ブラウザが開けないときは別のターミナル（コンテナ側）で:

    python3 ~/ros2_ws/src/care_patrol/care_patrol/staff_cli.py go
    python3 ~/ros2_ws/src/care_patrol/care_patrol/staff_cli.py arrived

## 時間の記録（H3）

`incidents` テーブルに、検知→確定→通報→職員の指示→人のそばに到着→職員到着→先導完了 の時刻が残る。巡回の最後にも表示される。
