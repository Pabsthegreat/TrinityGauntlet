"""
Rock-Paper-Scissors Simulation Controller (ROS 2)

Publishes gesture commands as JointTrajectory goals so a Gazebo/RViz hand model
can mirror the same R/P/S/Neutral behavior as the Arduino hand.

Environment variables:
  RPS_SIM_TOPIC=/rps_hand_controller/joint_trajectory
  RPS_SIM_JOINT_A=servo_a_joint
  RPS_SIM_JOINT_B=servo_b_joint
  RPS_SIM_ENGAGED=0.20
  RPS_SIM_RELAXED=2.80
  RPS_SIM_MOVE_TIME=0.25
"""

from __future__ import annotations

import os
import threading
import time


class RPSSimController:
    """Controls a simulated two-channel hand via ROS 2 JointTrajectory."""

    def __init__(
        self,
        topic: str = "/rps_hand_controller/joint_trajectory",
        joint_a: str = "servo_a_joint",
        joint_b: str = "servo_b_joint",
        engaged: float = 0.20,
        relaxed: float = 2.80,
        move_time_sec: float = 0.25,
        node_name: str = "rps_sim_controller",
    ):
        try:
            import rclpy
            from builtin_interfaces.msg import Duration
            from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint
        except ImportError as exc:
            raise ImportError(
                "ROS 2 Python packages are required for sim backend. "
                "Install/overlay your ROS 2 environment before running."
            ) from exc

        self._rclpy = rclpy
        self._Duration = Duration
        self._JointTrajectory = JointTrajectory
        self._JointTrajectoryPoint = JointTrajectoryPoint

        self.topic = topic
        self.joint_names = [joint_a, joint_b]
        self.engaged = float(engaged)
        self.relaxed = float(relaxed)
        self.move_time_sec = float(move_time_sec)

        self._owns_context = False
        if not self._rclpy.ok():
            self._rclpy.init(args=None)
            self._owns_context = True

        self._node = self._rclpy.create_node(node_name)
        self._publisher = self._node.create_publisher(self._JointTrajectory, self.topic, 10)
        self._stop_event = threading.Event()
        self._spin_thread = threading.Thread(target=self._spin_loop, daemon=True, name="RPSSimSpin")
        self._spin_thread.start()

        # Neutral in this project is same pose as rock (both engaged).
        self._pos_a = self.engaged
        self._pos_b = self.engaged

    @classmethod
    def from_env(cls, env_prefix: str = "RPS_SIM") -> "RPSSimController":
        prefix = env_prefix.strip().upper()
        default_topic = "/player/rps_hand_controller/joint_trajectory" if "PLAYER" in prefix else "/rps_hand_controller/joint_trajectory"

        def env(name: str, default: str) -> str:
            return os.getenv(f"{prefix}_{name}", default)

        return cls(
            topic=env("TOPIC", default_topic),
            joint_a=env("JOINT_A", "servo_a_joint"),
            joint_b=env("JOINT_B", "servo_b_joint"),
            engaged=float(env("ENGAGED", "0.20")),
            relaxed=float(env("RELAXED", "2.80")),
            move_time_sec=float(env("MOVE_TIME", "0.25")),
            node_name=env("NODE_NAME", f"{prefix.lower()}_controller"),
        )

    def _spin_loop(self):
        while not self._stop_event.is_set() and self._rclpy.ok():
            self._rclpy.spin_once(self._node, timeout_sec=0.1)

    def _publish_positions(self, a: float, b: float) -> float:
        msg = self._JointTrajectory()
        msg.joint_names = self.joint_names

        point = self._JointTrajectoryPoint()
        point.positions = [float(a), float(b)]
        point.time_from_start = self._Duration(sec=0, nanosec=int(self.move_time_sec * 1e9))
        msg.points = [point]

        t0 = time.perf_counter()
        self._publisher.publish(msg)
        return (time.perf_counter() - t0) * 1000.0

    def send_gesture(self, gesture: str) -> float:
        """Send a gesture command matching the serial controller command names."""
        key = gesture.lower().strip()

        if key in {"rock", "neutral"}:
            self._pos_a = self.engaged
            self._pos_b = self.engaged
        elif key == "paper":
            self._pos_a = self.relaxed
            self._pos_b = self.relaxed
        elif key == "scissors":
            self._pos_a = self.relaxed
            self._pos_b = self.engaged
        elif key == "a_engage":
            self._pos_a = self.engaged
        elif key == "a_relax":
            self._pos_a = self.relaxed
        elif key == "b_engage":
            self._pos_b = self.engaged
        elif key == "b_relax":
            self._pos_b = self.relaxed
        else:
            raise ValueError(
                "Unknown gesture '{0}'. Valid: rock, paper, scissors, neutral, "
                "a_engage, a_relax, b_engage, b_relax".format(gesture)
            )

        return self._publish_positions(self._pos_a, self._pos_b)

    def ping(self) -> bool:
        return self._rclpy.ok() and not self._stop_event.is_set()

    def close(self):
        self._stop_event.set()
        if self._spin_thread.is_alive():
            self._spin_thread.join(timeout=2.0)

        try:
            self._node.destroy_node()
        except Exception:
            pass

        if self._owns_context and self._rclpy.ok():
            try:
                self._rclpy.shutdown()
            except Exception:
                pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class RPSSimVizController:
    """RViz-only hand controller that publishes JointState directly."""

    def __init__(
        self,
        topic: str = "/player/joint_states",
        joint_a: str = "servo_a_joint",
        joint_b: str = "servo_b_joint",
        engaged: float = 0.20,
        relaxed: float = 2.80,
        node_name: str = "rps_player_viz_controller",
    ):
        try:
            import rclpy
            from sensor_msgs.msg import JointState
        except ImportError as exc:
            raise ImportError(
                "ROS 2 Python packages are required for sim visualization backend."
            ) from exc

        self._rclpy = rclpy
        self._JointState = JointState

        self.topic = topic
        self.joint_names = [joint_a, joint_b]
        self.engaged = float(engaged)
        self.relaxed = float(relaxed)

        self._owns_context = False
        if not self._rclpy.ok():
            self._rclpy.init(args=None)
            self._owns_context = True

        self._node = self._rclpy.create_node(node_name)
        self._publisher = self._node.create_publisher(self._JointState, self.topic, 10)

        self._pos_a = self.engaged
        self._pos_b = self.engaged

    @classmethod
    def from_env(cls, env_prefix: str = "RPS_PLAYER_SIM") -> "RPSSimVizController":
        prefix = env_prefix.strip().upper()

        def env(name: str, default: str) -> str:
            return os.getenv(f"{prefix}_{name}", default)

        return cls(
            topic=env("TOPIC", "/player/joint_states"),
            joint_a=env("JOINT_A", "servo_a_joint"),
            joint_b=env("JOINT_B", "servo_b_joint"),
            engaged=float(env("ENGAGED", "0.20")),
            relaxed=float(env("RELAXED", "2.80")),
            node_name=env("NODE_NAME", "rps_player_viz_controller"),
        )

    def _publish(self):
        msg = self._JointState()
        msg.header.stamp = self._node.get_clock().now().to_msg()
        msg.name = self.joint_names
        msg.position = [float(self._pos_a), float(self._pos_b)]
        self._publisher.publish(msg)
        self._rclpy.spin_once(self._node, timeout_sec=0.0)

    def send_gesture(self, gesture: str) -> float:
        key = gesture.lower().strip()
        if key in {"rock", "neutral"}:
            self._pos_a = self.engaged
            self._pos_b = self.engaged
        elif key == "paper":
            self._pos_a = self.relaxed
            self._pos_b = self.relaxed
        elif key == "scissors":
            self._pos_a = self.relaxed
            self._pos_b = self.engaged
        elif key == "a_engage":
            self._pos_a = self.engaged
        elif key == "a_relax":
            self._pos_a = self.relaxed
        elif key == "b_engage":
            self._pos_b = self.engaged
        elif key == "b_relax":
            self._pos_b = self.relaxed
        else:
            raise ValueError(
                "Unknown gesture '{0}'. Valid: rock, paper, scissors, neutral, "
                "a_engage, a_relax, b_engage, b_relax".format(gesture)
            )

        t0 = time.perf_counter()
        self._publish()
        return (time.perf_counter() - t0) * 1000.0

    def close(self):
        try:
            self._node.destroy_node()
        except Exception:
            pass
        if self._owns_context and self._rclpy.ok():
            try:
                self._rclpy.shutdown()
            except Exception:
                pass
