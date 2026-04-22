import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, RegisterEventHandler
from launch.conditions import IfCondition
from launch.event_handlers import OnProcessExit
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    use_gazebo = LaunchConfiguration("use_gazebo")

    pkg_share = FindPackageShare("rps_hand_sim")
    controllers_path = PathJoinSubstitution([pkg_share, "config", "controllers.yaml"])
    rviz_config = PathJoinSubstitution([pkg_share, "rviz", "rps_hand_clean.rviz"])

    pkg_share_path = get_package_share_directory("rps_hand_sim")
    urdf_file = os.path.join(pkg_share_path, "urdf", "rps_hand.urdf")
    controllers_file = os.path.join(pkg_share_path, "config", "controllers.yaml")
    with open(urdf_file, "r", encoding="utf-8") as f:
        robot_description_content = f.read()
    # gazebo_ros2_control is more reliable with an absolute filesystem path
    # in the <parameters> tag than with package:// indirection.
    robot_description_content = robot_description_content.replace(
        "package://rps_hand_sim/config/controllers.yaml",
        controllers_file,
    )
    robot_description = {"robot_description": robot_description_content}

    state_publisher = Node(
        package="robot_state_publisher",
        executable="robot_state_publisher",
        output="screen",
        parameters=[robot_description],
    )

    player_state_publisher = Node(
        package="robot_state_publisher",
        executable="robot_state_publisher",
        namespace="player",
        output="screen",
        parameters=[robot_description, {"frame_prefix": "player/"}],
        remappings=[("joint_states", "joint_states")],
    )

    player_offset_tf = Node(
        package="tf2_ros",
        executable="static_transform_publisher",
        arguments=["0.0", "0.35", "0.0", "0", "0", "0", "base_link", "player/base_link"],
        output="screen",
    )

    spawn_jsb = Node(
        package="controller_manager",
        executable="spawner",
        arguments=["joint_state_broadcaster", "--controller-manager", "/controller_manager"],
        output="screen",
        condition=IfCondition(use_gazebo),
    )

    spawn_traj = Node(
        package="controller_manager",
        executable="spawner",
        arguments=["rps_hand_controller", "--controller-manager", "/controller_manager"],
        output="screen",
        condition=IfCondition(use_gazebo),
    )


    rviz = Node(
        package="rviz2",
        executable="rviz2",
        arguments=["-d", rviz_config],
        output="screen",
    )

    gazebo = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution([FindPackageShare("gazebo_ros"), "launch", "gazebo.launch.py"])
        ),
        condition=IfCondition(use_gazebo),
    )

    spawn_entity = Node(
        package="gazebo_ros",
        executable="spawn_entity.py",
        arguments=["-entity", "rps_hand", "-topic", "robot_description"],
        output="screen",
        condition=IfCondition(use_gazebo),
    )

    start_traj_after_jsb = RegisterEventHandler(
        OnProcessExit(
            target_action=spawn_jsb,
            on_exit=[spawn_traj],
        )
    )

    return LaunchDescription([
        DeclareLaunchArgument("use_gazebo", default_value="true"),
        state_publisher,
        player_state_publisher,
        player_offset_tf,
        spawn_jsb,
        start_traj_after_jsb,
        rviz,
        gazebo,
        spawn_entity,
    ])
