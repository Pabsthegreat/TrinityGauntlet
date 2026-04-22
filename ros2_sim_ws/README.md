# ROS2 Simulation Workspace

This workspace contains the `rps_hand_sim` package, a minimal two-joint
simulation model that matches the real hardware mapping:

- `servo_a_joint`: index + middle group
- `servo_b_joint`: ring + pinky + thumb group

## Build (WSL2)

```bash
cd ~/path/to/TrinityGauntlet/ros2_sim_ws
source /opt/ros/humble/setup.bash
colcon build --symlink-install
source install/setup.bash
```

## Launch

Launch with Gazebo + RViz:

```bash
ros2 launch rps_hand_sim bringup.launch.py use_gazebo:=true
```

Launch only controllers + RViz (no Gazebo):

```bash
ros2 launch rps_hand_sim bringup.launch.py use_gazebo:=false
```

## Verify Controller Topic

The game's simulation backend publishes to:

- `/rps_hand_controller/joint_trajectory`

Confirm controller is active:

```bash
ros2 control list_controllers
```

## Quick Manual Test

Publish a scissors pose manually:

```bash
ros2 topic pub --once /rps_hand_controller/joint_trajectory trajectory_msgs/msg/JointTrajectory "{
  joint_names: [servo_a_joint, servo_b_joint],
  points: [{positions: [2.8, 0.2], time_from_start: {sec: 0, nanosec: 250000000}}]
}"
```
