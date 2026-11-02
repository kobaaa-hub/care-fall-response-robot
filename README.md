# 倒れた人を見つけて、職員を連れてくるロボット

介護施設の居室4部屋＋庭を巡回する TurtleBot3 が、VLM（Claude Sonnet 5.5、推論のみ）で利用者の状態を判定し、
転倒を見つけたら 近づいて撮り直し（二段階確認）→ 声かけ → 通報 → 職員の指示 → 出入口で迎えて現場へ先導 する。
ROS 2 Humble ＋ Gazebo 11（GCP の VM 上の Docker コンテナ `tiryoh/ros2-desktop-vnc:humble`）で実装。

## 構成

| ディレクトリ | 役割 |
| --- | --- |
| `care_world/` | ワールド生成（`care_world/ward_gen.py`：廊下＋居室4部屋＋庭、`world_gen.py`：1部屋版）、起動 launch、シナリオ定義 `config/scenarios.yaml`、人物モデル取得 `setup_models.sh`、停止 `stop_sim.sh` |
| `care_patrol/` | 巡回ノード `patrol_node.py`（移動・撮影・判定・初動対応）、VLM 呼び出し `vlm_client.py`、SQLite `care_db.py`、職員の承認画面 `staff_ui.py`（Flask、:8080）、ターミナル指示 `staff_cli.py`、集計 `report.py`、1コマンド実行 `run_patrol.sh`、計測 `run_measurements.sh` |
| `vlm_kit/` | VLM 単体の確認（カメラ画像を N 枚撮って判定）`snap.py` / `test_vlm.py` / `run_check.sh` |

各ディレクトリの README.md に詳細がある。

## 前提

- Ubuntu 22.04、ROS 2 Humble、Gazebo 11、`turtlebot3_simulations`（`TURTLEBOT3_MODEL=waffle_pi`）
- Python: `anthropic`, `flask`, `opencv-python`, `pyyaml`, `matplotlib`（`pip3 install anthropic flask pyyaml matplotlib "numpy<2"`。ROS の cv_bridge は NumPy 1.x 前提）
- Anthropic API キーは環境変数 `ANTHROPIC_API_KEY` で渡す（コードにも Git にも含めない）

## 使い方（コンテナのデスクトップにある LXTerminal で）

```bash
# 1. 人物モデルを取得（最初に1回）
bash ~/ros2_ws/src/care_world/setup_models.sh

# 2. デモ：フロア起動 → 承認画面起動 → 巡回。通報が出たらブラウザで http://localhost:8080 を開き「向かう」→「到着」
bash ~/ros2_ws/src/care_patrol/run_patrol.sh DEMO_GARDEN day 3 --staff-wait 300

# 3. 計測：7シナリオ×4条件＝30巡回を自動実行（職員の指示は待たず自動で「向かう」）
bash ~/ros2_ws/src/care_patrol/run_measurements.sh all

# 4. 集計：results/report/ に report.md と図（条件別一致率・混同行列・初動対応の時間）
cd ~/ros2_ws/src/care_patrol && python3 -m care_patrol.report
```

`run_patrol.sh SCENARIO LIGHTING N [patrol_node の引数]`
- SCENARIO: `S1`〜`S5`（転倒あり）、`N1`〜`N2`（転倒なし）、`DEMO_ROOM`、`DEMO_GARDEN`
- LIGHTING: `day` / `night` / `night_lit`（夜＋常夜灯）
- N: 1か所あたりの撮影枚数（1 または 3）
- 引数例: `--staff-wait 0`（計測用）、`--no-respond`（通報のみ）、`--no-vlm`（API を使わず動作だけ）

## データ

- `~/ros2_ws/results/care.db`（SQLite）：runs / records / evals / alerts / incidents / speech / corrections
- `~/ros2_ws/results/patrol_YYYYMMDD_HHMMSS_runN/`：巡回ごとの撮影画像

## 結果（30巡回・127判定）

| 条件 | 一致率 | 転倒の見逃し |
| --- | --- | --- |
| 昼・3枚 | 97% | 0/6 |
| 夜・常夜灯・3枚 | 92% | 0/5 |
| 夜・3枚 | 38%（62% が「保留」） | 0/5 |
| 夜・1枚 | 26% | 3/5 |

初動対応：検知 18件、二段階確認で確定 15件、誤報・誤った駆けつけ 0件、検知→通報 中央値 14秒、迎え→先導完了 中央値 63秒。
VLM 呼び出し 149回、費用 約 $0.73。

## 参考

- AIロボティクスに関する関係府省連絡会議「各分野別のAIロボティクス実装ロードマップ」P38–39（介護）
- ROBOTIS TurtleBot3 e-Manual、Open Robotics gazebo_models（person_standing）、Anthropic API（Vision）
