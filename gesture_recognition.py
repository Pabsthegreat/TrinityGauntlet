"""
Rock Paper Scissors Hand Gesture Recognition using MediaPipe Hands Tasks API.

Gesture rules (based on finger states):
  - Rock:     All fingers closed (fist)
  - Paper:    All fingers open
  - Scissors: Index + Middle open, others closed
"""

import os
import urllib.request
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

# Landmark indices
WRIST = 0
THUMB_CMC, THUMB_MCP, THUMB_IP, THUMB_TIP = 1, 2, 3, 4
INDEX_MCP, INDEX_PIP, INDEX_DIP, INDEX_TIP = 5, 6, 7, 8
MIDDLE_MCP, MIDDLE_PIP, MIDDLE_DIP, MIDDLE_TIP = 9, 10, 11, 12
RING_MCP, RING_PIP, RING_DIP, RING_TIP = 13, 14, 15, 16
PINKY_MCP, PINKY_PIP, PINKY_DIP, PINKY_TIP = 17, 18, 19, 20


def download_model():
    if not os.path.exists(MODEL_PATH):
        print(f"Downloading hand landmarker model to {MODEL_PATH} ...")
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
        print("Model downloaded.")


def is_finger_open(lm, tip_idx, pip_idx, mcp_idx):
    tip = lm[tip_idx]
    pip = lm[pip_idx]
    mcp = lm[mcp_idx]
    tip_dist = np.hypot(tip.x - mcp.x, tip.y - mcp.y)
    pip_dist = np.hypot(pip.x - mcp.x, pip.y - mcp.y)
    return tip_dist > pip_dist


def is_thumb_open(lm):
    tip = lm[THUMB_TIP]
    ip  = lm[THUMB_IP]
    mcp = lm[THUMB_MCP]
    tip_dist = np.hypot(tip.x - mcp.x, tip.y - mcp.y)
    ip_dist  = np.hypot(ip.x  - mcp.x, ip.y  - mcp.y)
    return tip_dist > ip_dist * 1.2


def get_finger_states(lm):
    return {
        "thumb":  is_thumb_open(lm),
        "index":  is_finger_open(lm, INDEX_TIP,  INDEX_PIP,  INDEX_MCP),
        "middle": is_finger_open(lm, MIDDLE_TIP, MIDDLE_PIP, MIDDLE_MCP),
        "ring":   is_finger_open(lm, RING_TIP,   RING_PIP,   RING_MCP),
        "pinky":  is_finger_open(lm, PINKY_TIP,  PINKY_PIP,  PINKY_MCP),
    }


def classify_gesture(fs):
    idx, mid, rng, pnk = fs["index"], fs["middle"], fs["ring"], fs["pinky"]
    if not idx and not mid and not rng and not pnk:
        return "Rock",     (0, 0, 255)
    elif idx and mid and rng and pnk:
        return "Paper",    (0, 255, 0)
    elif idx and mid and not rng and not pnk:
        return "Scissors", (255, 165, 0)
    else:
        return "Unknown",  (200, 200, 200)


def draw_finger_status(frame, fs, x=10, y=20):
    for i, (name, icon) in enumerate([
        ("thumb", "T"), ("index", "I"), ("middle", "M"), ("ring", "R"), ("pinky", "P")
    ]):
        color = (0, 255, 0) if fs[name] else (0, 0, 255)
        cv2.putText(frame, f"{icon}: {'open' if fs[name] else 'closed'}",
                    (x, y + i * 25), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 1, cv2.LINE_AA)


HAND_CONNECTIONS = [
    (0,1),(1,2),(2,3),(3,4),           # thumb
    (0,5),(5,6),(6,7),(7,8),           # index
    (0,9),(9,10),(10,11),(11,12),      # middle
    (0,13),(13,14),(14,15),(15,16),    # ring
    (0,17),(17,18),(18,19),(19,20),    # pinky
    (5,9),(9,13),(13,17),(0,17),       # palm
]

def draw_landmarks_on_frame(frame, hand_landmarks):
    h, w = frame.shape[:2]
    pts = [(int(lm.x * w), int(lm.y * h)) for lm in hand_landmarks]
    for a, b in HAND_CONNECTIONS:
        cv2.line(frame, pts[a], pts[b], (0, 200, 200), 2, cv2.LINE_AA)
    for x, y in pts:
        cv2.circle(frame, (x, y), 5, (255, 255, 255), -1, cv2.LINE_AA)
        cv2.circle(frame, (x, y), 5, (0, 150, 255),   1, cv2.LINE_AA)


def run():
    download_model()

    options = mp_vision.HandLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=MODEL_PATH),
        num_hands=1,
        min_hand_detection_confidence=0.7,
        min_hand_presence_confidence=0.6,
        min_tracking_confidence=0.6,
        running_mode=mp_vision.RunningMode.VIDEO,
    )

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        raise RuntimeError("Cannot open webcam.")

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    print("Press 'q' to quit.")

    with mp_vision.HandLandmarker.create_from_options(options) as landmarker:
        timestamp_ms = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            frame = cv2.flip(frame, 1)
            h, w = frame.shape[:2]

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

            timestamp_ms += 33  # ~30 fps
            result = landmarker.detect_for_video(mp_image, timestamp_ms)

            gesture, color = "No hand detected", (150, 150, 150)

            if result.hand_landmarks:
                lm = result.hand_landmarks[0]
                draw_landmarks_on_frame(frame, lm)
                fs = get_finger_states(lm)
                gesture, color = classify_gesture(fs)
                draw_finger_status(frame, fs)

            # Gesture label at bottom
            (lw, lh), _ = cv2.getTextSize(gesture, cv2.FONT_HERSHEY_DUPLEX, 2.5, 3)
            cv2.rectangle(frame, (w // 2 - lw // 2 - 15, h - 80),
                          (w // 2 + lw // 2 + 15, h - 20), (0, 0, 0), -1)
            cv2.putText(frame, gesture, (w // 2 - lw // 2, h - 30),
                        cv2.FONT_HERSHEY_DUPLEX, 2.5, color, 3, cv2.LINE_AA)

            cv2.imshow("Rock Paper Scissors - Gesture Recognition", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    run()
