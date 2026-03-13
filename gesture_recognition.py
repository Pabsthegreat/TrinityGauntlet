"""
Gesture recognition backend for the Rock Paper Scissors game.
"""

from __future__ import annotations

import copy
import json
import math
import os
import threading
import time
import urllib.request
from collections import deque

os.environ.setdefault("MPLCONFIGDIR", os.path.join(os.getcwd(), ".mpl-cache"))

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision

MODEL_PATH = "hand_landmarker.task"
MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
)
DEBUG_DIR = "debug_logs"
DEBUG_IMAGES_DIR = os.path.join(DEBUG_DIR, "frames")
DEBUG_DETECTIONS_LOG_PATH = os.path.join(DEBUG_DIR, "detections.jsonl")
DEBUG_ROUNDS_LOG_PATH = os.path.join(DEBUG_DIR, "rounds.jsonl")

VALID_GESTURES = {"Rock", "Paper", "Scissors"}

# Landmark indices
WRIST = 0
THUMB_MCP, THUMB_IP, THUMB_TIP = 2, 3, 4
INDEX_MCP, INDEX_PIP, INDEX_DIP, INDEX_TIP = 5, 6, 7, 8
MIDDLE_MCP, MIDDLE_PIP, MIDDLE_DIP, MIDDLE_TIP = 9, 10, 11, 12
RING_MCP, RING_PIP, RING_DIP, RING_TIP = 13, 14, 15, 16
PINKY_MCP, PINKY_PIP, PINKY_DIP, PINKY_TIP = 17, 18, 19, 20


def download_model():
    if not os.path.exists(MODEL_PATH):
        print(f"Downloading hand landmarker model to {MODEL_PATH} ...")
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
        print("Model downloaded.")


def ensure_debug_dirs():
    os.makedirs(DEBUG_IMAGES_DIR, exist_ok=True)


def joint_angle(a, b, c):
    ab = np.array([a.x - b.x, a.y - b.y, a.z - b.z], dtype=float)
    cb = np.array([c.x - b.x, c.y - b.y, c.z - b.z], dtype=float)
    mag_ab = np.linalg.norm(ab)
    mag_cb = np.linalg.norm(cb)

    if mag_ab == 0 or mag_cb == 0:
        return 0.0

    cos_theta = np.dot(ab, cb) / (mag_ab * mag_cb)
    cos_theta = np.clip(cos_theta, -1.0, 1.0)
    return math.degrees(math.acos(cos_theta))


def landmark_distance(a, b):
    return np.linalg.norm(np.array([a.x - b.x, a.y - b.y, a.z - b.z], dtype=float))


def get_finger_metrics(lm, mcp_idx, pip_idx, dip_idx, tip_idx):
    pip_angle = joint_angle(lm[mcp_idx], lm[pip_idx], lm[dip_idx])
    dip_angle = joint_angle(lm[pip_idx], lm[dip_idx], lm[tip_idx])
    tip_wrist_dist = landmark_distance(lm[tip_idx], lm[WRIST])
    pip_wrist_dist = landmark_distance(lm[pip_idx], lm[WRIST])
    is_open = bool(pip_angle > 160 and dip_angle > 150 and tip_wrist_dist > pip_wrist_dist)

    return {
        "pip_angle": round(float(pip_angle), 3),
        "dip_angle": round(float(dip_angle), 3),
        "tip_wrist_dist": round(float(tip_wrist_dist), 6),
        "pip_wrist_dist": round(float(pip_wrist_dist), 6),
        "open": is_open,
    }


def is_thumb_open(lm):
    tip = lm[THUMB_TIP]
    ip = lm[THUMB_IP]
    mcp = lm[THUMB_MCP]
    tip_dist = np.hypot(tip.x - mcp.x, tip.y - mcp.y)
    ip_dist = np.hypot(ip.x - mcp.x, ip.y - mcp.y)
    return bool(tip_dist > ip_dist * 1.2)


def get_all_finger_metrics(lm):
    return {
        "index": get_finger_metrics(lm, INDEX_MCP, INDEX_PIP, INDEX_DIP, INDEX_TIP),
        "middle": get_finger_metrics(lm, MIDDLE_MCP, MIDDLE_PIP, MIDDLE_DIP, MIDDLE_TIP),
        "ring": get_finger_metrics(lm, RING_MCP, RING_PIP, RING_DIP, RING_TIP),
        "pinky": get_finger_metrics(lm, PINKY_MCP, PINKY_PIP, PINKY_DIP, PINKY_TIP),
        "thumb": {
            "open": is_thumb_open(lm),
        },
    }


def raw_states_from_metrics(finger_metrics):
    return {
        "index": bool(finger_metrics["index"]["open"]),
        "middle": bool(finger_metrics["middle"]["open"]),
        "ring": bool(finger_metrics["ring"]["open"]),
        "pinky": bool(finger_metrics["pinky"]["open"]),
    }


def smooth_states(state_history):
    latest = state_history[-1]
    return {
        name: sum(state[name] for state in state_history) > len(state_history) // 2
        for name in latest
    }


def classify_gesture(finger_states):
    idx = finger_states["index"]
    mid = finger_states["middle"]
    rng = finger_states["ring"]
    pnk = finger_states["pinky"]

    if not idx and not mid and not rng and not pnk:
        return "Rock"
    if idx and mid and rng and pnk:
        return "Paper"
    if idx and mid and not rng and not pnk:
        return "Scissors"
    return "Unknown"


def serialize_landmarks(lm):
    return [
        {
            "x": round(float(point.x), 6),
            "y": round(float(point.y), 6),
            "z": round(float(point.z), 6),
        }
        for point in lm
    ]


class GestureRecognizer:
    def __init__(
        self,
        camera_index=0,
        smoothing_window=5,
        min_hand_detection_confidence=0.7,
        min_hand_presence_confidence=0.6,
        min_tracking_confidence=0.6,
    ):
        self.camera_index = camera_index
        self.smoothing_window = smoothing_window
        self.min_hand_detection_confidence = min_hand_detection_confidence
        self.min_hand_presence_confidence = min_hand_presence_confidence
        self.min_tracking_confidence = min_tracking_confidence

        self._state_history = deque(maxlen=smoothing_window)
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        self._thread = None
        self._startup_error = None

        self._capture_logging_active = False
        self._round_context = None
        self._latest_observation = self._default_observation()

    def _default_observation(self):
        return {
            "frame_idx": 0,
            "timestamp_ms": 0,
            "gesture": "No hand detected",
            "valid": False,
            "detection_present": False,
            "raw_finger_states": {},
            "smoothed_finger_states": {},
            "finger_metrics": {},
            "landmarks": [],
        }

    def start(self):
        if self._thread and self._thread.is_alive():
            return

        download_model()
        ensure_debug_dirs()
        self._stop_event.clear()
        self._ready_event.clear()
        self._startup_error = None
        self._thread = threading.Thread(target=self._run_loop, name="gesture-recognizer", daemon=True)
        self._thread.start()
        self._ready_event.wait(timeout=5.0)

        if self._startup_error:
            raise RuntimeError(self._startup_error)
        if not self._ready_event.is_set():
            raise RuntimeError("Gesture recognizer did not start in time.")

    def stop(self):
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)

    def get_latest_observation(self):
        with self._lock:
            return copy.deepcopy(self._latest_observation)

    def set_round_context(self, mode, round_number, bot_move):
        with self._lock:
            self._round_context = {
                "mode": mode,
                "round_number": int(round_number),
                "bot_move": bot_move,
            }

    def clear_round_context(self):
        with self._lock:
            self._round_context = None

    def set_capture_logging(self, active):
        with self._lock:
            self._capture_logging_active = bool(active)

    def log_round_summary(self, *, mode, round_number, bot_move, player_move, outcome, capture_invalid):
        entry = {
            "timestamp_ms": int(time.time() * 1000),
            "mode": mode,
            "round_number": int(round_number),
            "bot_move": bot_move,
            "player_move": player_move,
            "outcome": outcome,
            "capture_invalid": bool(capture_invalid),
        }
        with open(DEBUG_ROUNDS_LOG_PATH, "a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(entry) + "\n")

    def _run_loop(self):
        cap = None
        try:
            options = mp_vision.HandLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=MODEL_PATH),
                num_hands=1,
                min_hand_detection_confidence=self.min_hand_detection_confidence,
                min_hand_presence_confidence=self.min_hand_presence_confidence,
                min_tracking_confidence=self.min_tracking_confidence,
                running_mode=mp_vision.RunningMode.VIDEO,
            )

            cap = cv2.VideoCapture(self.camera_index)
            if not cap.isOpened():
                raise RuntimeError("Cannot open webcam.")

            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

            with open(DEBUG_DETECTIONS_LOG_PATH, "a", encoding="utf-8") as detection_log, \
                 mp_vision.HandLandmarker.create_from_options(options) as landmarker:
                self._ready_event.set()
                frame_idx = 0

                while not self._stop_event.is_set():
                    ret, frame = cap.read()
                    if not ret:
                        time.sleep(0.01)
                        continue

                    frame = cv2.flip(frame, 1)
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

                    frame_idx += 1
                    timestamp_ms = int(time.monotonic() * 1000)
                    result = landmarker.detect_for_video(mp_image, timestamp_ms)

                    if result.hand_landmarks:
                        lm = result.hand_landmarks[0]
                        finger_metrics = get_all_finger_metrics(lm)
                        raw_states = raw_states_from_metrics(finger_metrics)
                        self._state_history.append(raw_states)
                        smoothed_states = smooth_states(self._state_history)
                        gesture = classify_gesture(smoothed_states)

                        observation = {
                            "frame_idx": frame_idx,
                            "timestamp_ms": timestamp_ms,
                            "gesture": gesture,
                            "valid": gesture in VALID_GESTURES,
                            "detection_present": True,
                            "raw_finger_states": raw_states,
                            "smoothed_finger_states": smoothed_states,
                            "finger_metrics": finger_metrics,
                            "landmarks": serialize_landmarks(lm),
                        }
                    else:
                        self._state_history.clear()
                        observation = {
                            "frame_idx": frame_idx,
                            "timestamp_ms": timestamp_ms,
                            "gesture": "No hand detected",
                            "valid": False,
                            "detection_present": False,
                            "raw_finger_states": {},
                            "smoothed_finger_states": {},
                            "finger_metrics": {},
                            "landmarks": [],
                        }

                    with self._lock:
                        self._latest_observation = observation
                        should_log = self._capture_logging_active and observation["detection_present"]
                        round_context = copy.deepcopy(self._round_context)

                    if should_log:
                        self._log_detection(
                            detection_log,
                            frame,
                            observation,
                            round_context,
                        )
        except Exception as exc:
            self._startup_error = str(exc)
            self._ready_event.set()
        finally:
            if cap is not None:
                cap.release()

    def _log_detection(self, log_file, frame, observation, round_context):
        image_name = f"frame_{observation['frame_idx']:06d}.jpg"
        image_path = os.path.join(DEBUG_IMAGES_DIR, image_name)
        cv2.imwrite(image_path, frame)

        entry = {
            "frame_idx": observation["frame_idx"],
            "timestamp_ms": observation["timestamp_ms"],
            "gesture": observation["gesture"],
            "image_path": image_path,
            "raw_finger_states": observation["raw_finger_states"],
            "smoothed_finger_states": observation["smoothed_finger_states"],
            "finger_metrics": observation["finger_metrics"],
            "landmarks": observation["landmarks"],
            "round_context": round_context,
        }
        log_file.write(json.dumps(entry) + "\n")
        log_file.flush()
