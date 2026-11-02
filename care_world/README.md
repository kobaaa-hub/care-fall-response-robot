# care_world：介護施設の居室ワールド（層①）

4m四方の居室に、ベッド・サイドテーブル・ナースコール・窓・手すり・椅子と、利用者の人物モデルを置いたGazeboワールド。
TurtleBot3 waffle_pi は入口の内側に東向きで置かれ、カメラからベッドを横から見る。

## 最初に1回だけ（コンテナ側）

    bash ~/ros2_ws/src/care_world/setup_models.sh

人物モデル（person_standing）を ~/.gazebo/models に入れる。

## 起動（ブラウザのデスクトップのLXTerminal）

    bash ~/ros2_ws/src/care_world/stop_sim.sh
    ros2 launch ~/ros2_ws/src/care_world/launch/care_room.launch.py scenario:=in_bed

| scenario | 状態（正解ラベル） |
| --- | --- |
| in_bed | ベッドで横になっている |
| fall_suspected | ベッドの横の床に倒れている（歩行器が転がっている） |
| standing | ベッドの横に立っている |
| absent | 不在 |

夜にするときは `lighting:=night`。画面を出さずに軽く動かすときは `gui:=false`。

## 判定（Macのターミナルから入ったコンテナ側）

    bash ~/ros2_ws/vlm_kit/run_check.sh 3

## シナリオを切り替えるとき

起動したLXTerminalで Ctrl + C → `bash ~/ros2_ws/src/care_world/stop_sim.sh` → scenario を変えて起動し直す。

## 見た目の調整

人物が沈む・浮く・ベッドからはみ出す場合は `care_world/world_gen.py` 先頭の寸法（MATTRESS_TOP、PERSON_HALF_WIDTH、BED_X など）を変える。
