# TrinityGauntlet

Adaptive Rock-Paper-Scissors project with:

- MediaPipe-based hand gesture recognition
- Tkinter game UI and round logic
- Physical Arduino-driven robotic hand control
- ROS 2 simulation backend for Gazebo/RViz

## Architecture

- `gesture_recognition.py`: webcam + MediaPipe hand landmarks + gesture classification
- `game.py`: countdown/capture/result UI loop and score logic
- `rps_serial_controller.py`: serial protocol to Arduino hand (`R/P/S/N` + test commands)
- `rps_sim_controller.py`: ROS 2 `JointTrajectory` publisher for simulation hand
- `rps_robot_hand/rps_robot_hand.ino`: firmware for 2-servo robotic hand

The game uses one gesture API (`send_gesture`) and can switch backend via env vars.

## Backend Selection

Set `RPS_HAND_BACKEND` before running the app:

- `auto` (default): try serial hardware first, then simulation
- `serial`: force Arduino serial backend
- `sim`: force ROS 2 simulation backend
- `off`: disable hand backend (vision + UI only)

## Player Input Mode (Webcam vs Keyboard)

The game already supports webcam gesture input by default.

- Webcam mode (default): do **not** set `RPS_GESTURE_INPUT`, or set it to `webcam`
- Keyboard mode (fallback): set `RPS_GESTURE_INPUT=keyboard`

Examples:

Windows PowerShell (webcam mode):

```powershell
Remove-Item Env:RPS_GESTURE_INPUT -ErrorAction SilentlyContinue
python .\main.py
```

Windows PowerShell (keyboard mode):

```powershell
$env:RPS_GESTURE_INPUT = "keyboard"
python .\main.py
```

## Python Setup

```bash
pip install -r requirements.txt
```

Run:

```bash
python main.py
```

## Hardware Mode (Arduino)

```bash
RPS_HAND_BACKEND=serial python main.py
```

On Windows PowerShell:

```powershell
$env:RPS_HAND_BACKEND = "serial"
python .\main.py
```

## Simulation Mode (ROS 2 + Gazebo/RViz on WSL2)

Use `sim` backend to publish hand gestures as joint trajectory targets.

### 1. Launch your ROS 2 simulation stack

This repo now includes a simulation workspace at:

- `ros2_sim_ws/`

Build and launch in WSL2:

```bash
cd /path/to/TrinityGauntlet/ros2_sim_ws
source /opt/ros/humble/setup.bash
colcon build --symlink-install
source install/setup.bash
ros2 launch rps_hand_sim bringup.launch.py use_gazebo:=true
```

Your simulated hand must expose a `JointTrajectory` controller topic, e.g.:

- `/rps_hand_controller/joint_trajectory`

with two joints (default names):

- `servo_a_joint`
- `servo_b_joint`

### 2. Configure environment for the game process

In the shell where you run `main.py`:

```bash
export RPS_HAND_BACKEND=sim
export RPS_SIM_TOPIC=/rps_hand_controller/joint_trajectory
export RPS_SIM_JOINT_A=servo_a_joint
export RPS_SIM_JOINT_B=servo_b_joint
export RPS_SIM_ENGAGED=0.20
export RPS_SIM_RELAXED=2.80
export RPS_SIM_MOVE_TIME=0.25
python main.py
```

### 3. Gesture mapping used in both hardware and sim

- Rock: A engaged, B engaged
- Paper: A relaxed, B relaxed
- Scissors: A relaxed, B engaged
- Neutral: same as Rock

### 4. Calibrate to match your mechanical model

Adjust:

- `RPS_SIM_ENGAGED`
- `RPS_SIM_RELAXED`

to match the real finger pull/release behavior in your URDF limits.

## Notes

- The UI sends bot reveal exactly at `SHOOT` and returns to neutral after reveal.
- Servo test panel commands (`a_engage`, `a_relax`, `b_engage`, `b_relax`) also work with simulation backend.
