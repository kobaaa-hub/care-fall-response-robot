"""フロア（廊下＋居室4部屋）のワールドを開き、TurtleBot3 waffle_pi を待機ステーションに置く。

使い方（ブラウザのLXTerminal）:
    ros2 launch ~/ros2_ws/src/care_world/launch/care_ward.launch.py scenario:=S1
引数:
    scenario:=S1 | S2 | ... | DEMO   config/scenarios.yaml の名前（既定 S1）
    rooms:='{"101":"in_bed","104":"fall_suspected"}'  YAMLを使わず直接指定（scenario より優先）
    lighting:=day | night             （既定 day）
    gui:=true | false                 （既定 true。この環境ではカメラの描画に画面が必要）
"""
import json
import os
import sys
import tempfile

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, LogInfo, OpaqueFunction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration

HERE = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "care_world"))
import ward_gen  # noqa: E402


def launch_setup(context, *args, **kwargs):
    scenario = LaunchConfiguration("scenario").perform(context)
    rooms_arg = LaunchConfiguration("rooms").perform(context)
    lighting = LaunchConfiguration("lighting").perform(context)
    gui = LaunchConfiguration("gui").perform(context).lower() in ("true", "1", "yes")

    os.environ.setdefault("TURTLEBOT3_MODEL", "waffle_pi")

    if rooms_arg:
        states = json.loads(rooms_arg)
    else:
        with open(os.path.join(ROOT, "config", "scenarios.yaml"), encoding="utf-8") as f:
            table = yaml.safe_load(f)["scenarios"]
        if scenario not in table:
            raise RuntimeError(f"scenario '{scenario}' は scenarios.yaml にありません: {list(table)}")
        states = {str(k): v for k, v in table[scenario].items()}

    world_path = os.path.join(tempfile.gettempdir(), f"care_ward_{scenario}_{lighting}.world")
    with open(world_path, "w", encoding="utf-8") as f:
        f.write(ward_gen.build_world(states, lighting))
    # 巡回ノードが正解を照合できるように、使った状態も書き出す
    with open(os.path.join(tempfile.gettempdir(), "care_ward_current.json"), "w", encoding="utf-8") as f:
        json.dump({"scenario": scenario, "lighting": lighting, "states": states}, f, ensure_ascii=False)

    gazebo_ros = get_package_share_directory("gazebo_ros")
    tb3 = get_package_share_directory("turtlebot3_gazebo")
    x, y = ward_gen.STATION

    actions = [
        LogInfo(msg=f"[care_ward] scenario={scenario} lighting={lighting} states={states}"),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(gazebo_ros, "launch", "gzserver.launch.py")),
            launch_arguments={"world": world_path}.items()),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(tb3, "launch", "robot_state_publisher.launch.py")),
            launch_arguments={"use_sim_time": "true"}.items()),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(tb3, "launch", "spawn_turtlebot3.launch.py")),
            launch_arguments={"x_pose": str(x), "y_pose": str(y)}.items()),
    ]
    if gui:
        actions.append(IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(gazebo_ros, "launch", "gzclient.launch.py"))))
    return actions


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument("scenario", default_value="S1"),
        DeclareLaunchArgument("rooms", default_value=""),
        DeclareLaunchArgument("lighting", default_value="day"),
        DeclareLaunchArgument("gui", default_value="true"),
        OpaqueFunction(function=launch_setup),
    ])
