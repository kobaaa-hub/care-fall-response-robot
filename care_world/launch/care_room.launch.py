"""居室1部屋のワールドを開き、TurtleBot3 waffle_pi を入口に置く。

使い方（コンテナ側）:
    ros2 launch ~/ros2_ws/src/care_world/launch/care_room.launch.py scenario:=in_bed
引数:
    scenario:=in_bed | fall_suspected | standing | absent   （既定 in_bed）
    lighting:=day | night                                  （既定 day）
    gui:=true | false   false にするとGazeboの画面を出さず軽くなる（既定 true）
"""
import os
import sys
import tempfile

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, LogInfo, OpaqueFunction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "care_world"))
import world_gen  # noqa: E402


def launch_setup(context, *args, **kwargs):
    scenario = LaunchConfiguration("scenario").perform(context)
    lighting = LaunchConfiguration("lighting").perform(context)
    gui = LaunchConfiguration("gui").perform(context).lower() in ("true", "1", "yes")

    # TURTLEBOT3_MODEL が空だと起動に失敗するので、無ければ waffle_pi にする
    os.environ.setdefault("TURTLEBOT3_MODEL", "waffle_pi")
    if os.environ["TURTLEBOT3_MODEL"] != "waffle_pi":
        print(f"[care_room] 注意: TURTLEBOT3_MODEL={os.environ['TURTLEBOT3_MODEL']}（カメラ付きは waffle_pi だけ）")

    world_path = os.path.join(tempfile.gettempdir(), f"care_room_{scenario}_{lighting}.world")
    with open(world_path, "w", encoding="utf-8") as f:
        f.write(world_gen.build_world(scenario, lighting))

    gazebo_ros = get_package_share_directory("gazebo_ros")
    tb3 = get_package_share_directory("turtlebot3_gazebo")
    x, y = world_gen.ROBOT_POSE

    actions = [
        LogInfo(msg=f"[care_room] scenario={scenario} lighting={lighting} world={world_path}"),
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
        DeclareLaunchArgument("scenario", default_value="in_bed",
                              description="in_bed | fall_suspected | standing | absent"),
        DeclareLaunchArgument("lighting", default_value="day", description="day | night"),
        DeclareLaunchArgument("gui", default_value="true", description="Gazeboの画面を出すか"),
        OpaqueFunction(function=launch_setup),
    ])
