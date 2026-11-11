import os
from ament_index_python.packages import get_package_share_directory as share
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    ExecuteProcess,
    IncludeLaunchDescription,
    SetEnvironmentVariable,
    TimerAction,
)
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration as C
from launch_ros.actions import Node, SetParametersFromFile, SetRemap
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    own = share("bai08_turtlebot4")
    sim = share("turtlebot4_ignition_bringup")
    return LaunchDescription(
        [
            DeclareLaunchArgument("run_dir", default_value="/tmp/bai08_run"),
            DeclareLaunchArgument("gui", default_value="true"),
            DeclareLaunchArgument("allow_test", default_value="false"),
            SetParametersFromFile(own + "/config/simulation.yaml"),
            SetRemap(src="cmd_vel_bridge:cmd_vel", dst="/bai08/unused_ign_cmd"),
            SetEnvironmentVariable(
                "IGN_GAZEBO_RESOURCE_PATH",
                ":".join(
                    [
                        sim + "/worlds",
                        "/opt/ros/humble/share",
                        os.environ.get("IGN_GAZEBO_RESOURCE_PATH", ""),
                    ]
                ),
            ),
            SetEnvironmentVariable(
                "IGN_GUI_PLUGIN_PATH",
                ":".join(
                    [
                        share("turtlebot4_ignition_gui_plugins") + "/lib",
                        share("irobot_create_ignition_plugins") + "/lib",
                    ]
                ),
            ),
            SetEnvironmentVariable(
                "IGN_GAZEBO_SYSTEM_PLUGIN_PATH",
                ":".join(
                    ["/opt/ros/humble/lib", os.environ.get("LD_LIBRARY_PATH", "")]
                ),
            ),
            ExecuteProcess(
                cmd=[
                    "ign",
                    "gazebo",
                    "-s",
                    own + "/worlds/emotion_arena.sdf",
                    "-r",
                    "-v",
                    "2",
                ],
                output="screen",
            ),
            TimerAction(
                period=5.0,
                actions=[
                    ExecuteProcess(
                        cmd=[
                            "ign",
                            "gazebo",
                            "-g",
                            "--gui-config",
                            own + "/config/gazebo_gui.config",
                            "-v",
                            "2",
                        ],
                        output="screen",
                        condition=IfCondition(C("gui")),
                    )
                ],
            ),
            Node(
                package="ros_gz_bridge",
                executable="parameter_bridge",
                name="bai08_clock",
                arguments=["/clock@rosgraph_msgs/msg/Clock[ignition.msgs.Clock"],
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    sim + "/launch/turtlebot4_spawn.launch.py"
                ),
                launch_arguments={
                    "model": "standard",
                    "world": "emotion_arena",
                    "x": "0.",
                    "y": "0.",
                    "yaw": "0.",
                    "rviz": "false",
                }.items(),
            ),
            Node(package="bai08_turtlebot4", executable="prepare", output="screen"),
            Node(
                package="bai08_turtlebot4",
                executable="controller",
                output="screen",
                parameters=[
                    {
                        "run_dir": C("run_dir"),
                        "allow_test": ParameterValue(C("allow_test"), value_type=bool),
                    }
                ],
            ),
            TimerAction(
                period=8.0,
                actions=[
                    Node(
                        package="rviz2",
                        executable="rviz2",
                        arguments=["-d", own + "/config/emotion.rviz"],
                        parameters=[{"use_sim_time": True}],
                        condition=IfCondition(C("gui")),
                    )
                ],
            ),
        ]
    )
