"""
Tkinter game UI for the adaptive Rock Paper Scissors bot.
"""

from __future__ import annotations

import queue
import random
import shutil
import subprocess
import threading
import time
import tkinter as tk
from dataclasses import dataclass

from gesture_recognition import GestureRecognizer

try:
    from rps_serial_controller import RPSController
    _SERIAL_AVAILABLE = True
except ImportError:
    RPSController = None  # type: ignore[assignment]
    _SERIAL_AVAILABLE = False

try:
    import cv2
    from PIL import Image, ImageTk
    _CAMERA_PREVIEW_AVAILABLE = True
except ImportError:
    _CAMERA_PREVIEW_AVAILABLE = False

CAMERA_POLL_MS = 33  # ~30 fps preview refresh

GESTURE_ORDER = ["Rock", "Paper", "Scissors"]
COUNTDOWN_WORDS = ["Rock", "Paper", "Scissors", "Shoot"]
AUDIO_WORDS = {
    "Rock": "Rock",
    "Paper": "Paper",
    "Scissors": "Scissors",
    "Shoot": "Shoot!",
}
COUNTDOWN_INTERVAL_MS = 700
CAPTURE_WINDOW_MS = 450
CAPTURE_POLL_MS = 35

WIN_MAP = {
    "Rock": "Scissors",
    "Paper": "Rock",
    "Scissors": "Paper",
}


@dataclass
class RoundResult:
    bot_move: str
    player_move: str
    outcome: str
    result_text: str
    capture_invalid: bool


class BotStrategy:
    def __init__(self):
        self._index = 0

    def reset(self):
        self._index = random.randrange(len(GESTURE_ORDER))

    @property
    def current_move(self):
        return GESTURE_ORDER[self._index]

    def update(self, outcome):
        if outcome == "bot_win":
            self._index = (self._index + 1) % len(GESTURE_ORDER)
        elif outcome == "player_win":
            self._index = (self._index - 1) % len(GESTURE_ORDER)


def evaluate_round(player_move, bot_move):
    if player_move == bot_move:
        return "tie"
    if WIN_MAP[bot_move] == player_move:
        return "bot_win"
    return "player_win"


class RPSGameApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Adaptive Rock Paper Scissors")
        self.root.geometry("960x860")
        self.root.minsize(900, 820)
        self.root.configure(bg="#0e1a2b")
        self.root.protocol("WM_DELETE_WINDOW", self.shutdown)

        self.recognizer = GestureRecognizer()
        self.recognizer.start()

        # Robot hand (serial). Initialised lazily in a background thread so a
        # missing or slow Arduino never blocks UI startup.
        self.hand: RPSController | None = None
        self.hand_queue: queue.Queue | None = None
        self.hand_thread: threading.Thread | None = None

        self.bot_strategy = BotStrategy()
        self.mode = "best_of_3"
        self.mode_label = "Best of 3"
        self.state = "menu"

        self.player_score = 0
        self.bot_score = 0
        self.tie_count = 0
        self.round_number = 0

        self.pending_job = None
        self.camera_job = None
        self.camera_photo = None  # kept as attribute so Tk doesn't GC the image
        self.capture_started_at = 0.0
        self.capture_start_frame_idx = 0
        self.last_sampled_frame_idx = 0
        self.streak_gesture = None
        self.streak_count = 0
        self.audio_process = None
        self.speech_command = self._detect_speech_command()

        self._build_ui()
        self.show_menu()
        self._start_camera_preview()

        if _SERIAL_AVAILABLE:
            threading.Thread(
                target=self._init_robot_hand, daemon=True, name="HandConnect"
            ).start()

    # ── Robot hand (serial) ───────────────────────────────────────────

    def _init_robot_hand(self):
        """Connect to the Arduino and spin up the worker thread. Runs in a
        background thread so a missing/slow board never blocks UI startup."""
        if RPSController is None:
            return
        port = RPSController.autodetect_port()
        if port is None:
            print("[Hand] No Arduino detected; game runs without physical hand.")
            return
        try:
            controller = RPSController(port=port)
        except Exception as e:
            print(f"[Hand] Failed to open {port}: {e}")
            return

        # Order matters: set `hand` before `hand_queue` is exposed, so the
        # worker always sees a valid controller when it pulls its first item.
        self.hand = controller
        self.hand_queue = queue.Queue()
        self.hand_thread = threading.Thread(
            target=self._hand_worker, daemon=True, name="HandWorker"
        )
        self.hand_thread.start()
        print(f"[Hand] Robot hand ready on {port}.")
        # Park at neutral now, in case the game is already mid-menu.
        self._send_hand_gesture("neutral")

    def _hand_worker(self):
        """Consume gesture commands from the queue. A single worker serialises
        all serial writes so no two threads ever touch the port at once."""
        while True:
            cmd = self.hand_queue.get()
            if cmd is None:
                return
            try:
                self.hand.send_gesture(cmd)
            except Exception as e:
                print(f"[Hand] send '{cmd}' failed: {e}")

    def _send_hand_gesture(self, gesture: str):
        """Queue a non-blocking gesture command. Safe to call when the hand
        isn't connected — it simply becomes a no-op."""
        if self.hand_queue is None:
            return
        self.hand_queue.put(gesture.lower())

    # ── Camera preview ────────────────────────────────────────────────

    def _start_camera_preview(self):
        if not _CAMERA_PREVIEW_AVAILABLE:
            return
        self._poll_camera_frame()

    def _poll_camera_frame(self):
        frame = self.recognizer.get_latest_frame()
        if frame is not None:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image = Image.fromarray(rgb)
            self.camera_photo = ImageTk.PhotoImage(image=image)
            # Switching from text placeholder to image — clear the width/height
            # char-cell sizing so Tk sizes the label to the image instead.
            self.camera_label.configure(
                image=self.camera_photo,
                text="",
                width=0,
                height=0,
            )
        self.camera_job = self.root.after(CAMERA_POLL_MS, self._poll_camera_frame)

    SERVO_LABELS = {
        "A": "Servo 1 (index+middle)",
        "B": "Servo 2 (ring+pinky+thumb)",
    }

    def _test_servo(self, gesture):
        """Send a gesture to the servo from the test panel. Also resets the
        per-servo toggle state since the gesture affects both servos."""
        self._send_hand_gesture(gesture)
        self._servo_states = {"A": False, "B": False}
        for key, btn in self._servo_buttons.items():
            btn.config(text=f"{self.SERVO_LABELS[key]}\n[relaxed]")
        self.test_status.config(text=f"Sent: {gesture}")

    def _toggle_single_servo(self, key):
        """Toggle a single servo between engaged and relaxed without touching
        the other. Uses the per-servo test commands on the Arduino."""
        engaged_now = not self._servo_states[key]
        self._servo_states[key] = engaged_now
        suffix = "engage" if engaged_now else "relax"
        self._send_hand_gesture(f"{key.lower()}_{suffix}")

        state_text = "[engaged]" if engaged_now else "[relaxed]"
        self._servo_buttons[key].config(
            text=f"{self.SERVO_LABELS[key]}\n{state_text}"
        )
        self.test_status.config(
            text=f"{self.SERVO_LABELS[key]} -> {'engaged' if engaged_now else 'relaxed'}"
        )

    def _toggle_test_panel(self):
        """Show or hide the servo test panel."""
        if self.test_frame.winfo_viewable():
            self.test_frame.grid_remove()
        else:
            self.test_frame.grid()

    def _stop_camera_preview(self):
        if self.camera_job is not None:
            try:
                self.root.after_cancel(self.camera_job)
            except tk.TclError:
                pass
            self.camera_job = None

    def _build_ui(self):
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

        self.container = tk.Frame(self.root, bg="#0e1a2b", padx=40, pady=32)
        self.container.grid(sticky="nsew")
        self.container.grid_columnconfigure(0, weight=1)

        self.title_label = tk.Label(
            self.container,
            text="Adaptive RPS",
            font=("Helvetica", 28, "bold"),
            fg="#f3efe0",
            bg="#0e1a2b",
        )
        self.title_label.grid(row=0, column=0, sticky="ew")

        self.subtitle_label = tk.Label(
            self.container,
            text="Select a mode and start the countdown.",
            font=("Helvetica", 14),
            fg="#b1c6de",
            bg="#0e1a2b",
        )
        self.subtitle_label.grid(row=1, column=0, pady=(8, 24), sticky="ew")

        self.hero_label = tk.Label(
            self.container,
            text="START",
            font=("Helvetica", 54, "bold"),
            fg="#ffd166",
            bg="#0e1a2b",
        )
        self.hero_label.grid(row=2, column=0, pady=(10, 12), sticky="ew")

        self.camera_frame = tk.Frame(
            self.container,
            bg="#16263b",
            highlightthickness=2,
            highlightbackground="#2b3a55",
            padx=6,
            pady=6,
        )
        self.camera_frame.grid(row=3, column=0, pady=(0, 14))
        self.camera_label = tk.Label(
            self.camera_frame,
            text=(
                "Live camera preview\nConnecting to webcam…"
                if _CAMERA_PREVIEW_AVAILABLE
                else "Live preview unavailable\n(install pillow + opencv)"
            ),
            font=("Helvetica", 12),
            fg="#b1c6de",
            bg="#16263b",
            width=56,   # in character cells until the first image replaces it
            height=12,
        )
        self.camera_label.grid()

        self.status_label = tk.Label(
            self.container,
            text="Camera is running in the background.",
            font=("Helvetica", 16),
            fg="#eff6ff",
            bg="#0e1a2b",
        )
        self.status_label.grid(row=4, column=0, pady=(0, 22), sticky="ew")

        self.score_frame = tk.Frame(self.container, bg="#16263b", padx=24, pady=18)
        self.score_frame.grid(row=5, column=0, sticky="ew")
        for column in range(3):
            self.score_frame.grid_columnconfigure(column, weight=1)

        self.mode_value = tk.Label(
            self.score_frame,
            text="Mode: Best of 3",
            font=("Helvetica", 14, "bold"),
            fg="#ffd166",
            bg="#16263b",
        )
        self.mode_value.grid(row=0, column=0, sticky="w")

        self.score_value = tk.Label(
            self.score_frame,
            text="You 0  |  Bot 0  |  Ties 0",
            font=("Helvetica", 14),
            fg="#eff6ff",
            bg="#16263b",
        )
        self.score_value.grid(row=0, column=1)

        self.round_value = tk.Label(
            self.score_frame,
            text="Round 0",
            font=("Helvetica", 14),
            fg="#b1c6de",
            bg="#16263b",
        )
        self.round_value.grid(row=0, column=2, sticky="e")

        self.detail_frame = tk.Frame(self.container, bg="#0e1a2b")
        self.detail_frame.grid(row=6, column=0, pady=(28, 18), sticky="ew")
        for column in range(3):
            self.detail_frame.grid_columnconfigure(column, weight=1)

        self.bot_move_label = tk.Label(
            self.detail_frame,
            text="Bot move: -",
            font=("Helvetica", 18, "bold"),
            fg="#7bdff2",
            bg="#0e1a2b",
        )
        self.bot_move_label.grid(row=0, column=0, sticky="w")

        self.player_move_label = tk.Label(
            self.detail_frame,
            text="Your move: -",
            font=("Helvetica", 18, "bold"),
            fg="#f7a072",
            bg="#0e1a2b",
        )
        self.player_move_label.grid(row=0, column=1)

        self.result_label = tk.Label(
            self.detail_frame,
            text="Result: -",
            font=("Helvetica", 18, "bold"),
            fg="#f3efe0",
            bg="#0e1a2b",
        )
        self.result_label.grid(row=0, column=2, sticky="e")

        self.button_frame = tk.Frame(self.container, bg="#0e1a2b")
        self.button_frame.grid(row=7, column=0, pady=(24, 0), sticky="ew")

        self.primary_button = tk.Button(
            self.button_frame,
            text="Start Game",
            font=("Helvetica", 16, "bold"),
            command=self.start_game,
            bg="#ffd166",
            fg="#182235",
            activebackground="#ffe29a",
            activeforeground="#182235",
            bd=0,
            padx=28,
            pady=12,
        )
        self.primary_button.grid(row=0, column=0, padx=8, pady=8)

        self.secondary_button = tk.Button(
            self.button_frame,
            text="Best of 3",
            font=("Helvetica", 14, "bold"),
            command=lambda: self.set_mode("best_of_3"),
            bg="#dce6f2",
            fg="#182235",
            activebackground="#c8d8ea",
            activeforeground="#182235",
            bd=0,
            padx=20,
            pady=10,
        )
        self.secondary_button.grid(row=0, column=1, padx=8, pady=8)

        self.tertiary_button = tk.Button(
            self.button_frame,
            text="Unlimited",
            font=("Helvetica", 14, "bold"),
            command=lambda: self.set_mode("unlimited"),
            bg="#dce6f2",
            fg="#182235",
            activebackground="#c8d8ea",
            activeforeground="#182235",
            bd=0,
            padx=20,
            pady=10,
        )
        self.tertiary_button.grid(row=0, column=2, padx=8, pady=8)

        self.menu_button = tk.Button(
            self.button_frame,
            text="Back to Menu",
            font=("Helvetica", 14, "bold"),
            command=self.show_menu,
            bg="#dce6f2",
            fg="#182235",
            activebackground="#c8d8ea",
            activeforeground="#182235",
            bd=0,
            padx=20,
            pady=10,
        )
        self.menu_button.grid(row=0, column=3, padx=8, pady=8)

        # ── Servo test panel (hidden by default) ─────────────────────
        self.test_frame = tk.Frame(self.container, bg="#0e1a2b")
        self.test_frame.grid(row=8, column=0, pady=(18, 0), sticky="ew")
        self.test_frame.grid_remove()  # hidden until "Test Servos" is clicked

        tk.Label(
            self.test_frame,
            text="Servo Test Panel",
            font=("Helvetica", 14, "bold"),
            fg="#7bdff2",
            bg="#0e1a2b",
        ).grid(row=0, column=0, columnspan=5, pady=(0, 8))

        test_gestures = [("Rock", "#ef476f"), ("Paper", "#06d6a0"),
                         ("Scissors", "#ffd166"), ("Neutral", "#b1c6de")]
        for col, (gesture, color) in enumerate(test_gestures):
            btn = tk.Button(
                self.test_frame,
                text=gesture,
                font=("Helvetica", 13, "bold"),
                command=lambda g=gesture: self._test_servo(g),
                bg=color,
                fg="#182235",
                activebackground=color,
                activeforeground="#182235",
                bd=0,
                padx=18,
                pady=8,
            )
            btn.grid(row=1, column=col, padx=6, pady=4)

        # Per-servo toggle row (test each servo in isolation).
        self._servo_states = {"A": False, "B": False}
        self._servo_buttons = {}
        servo_labels = [
            ("A", "Servo 1 (index+middle)"),
            ("B", "Servo 2 (ring+pinky+thumb)"),
        ]
        for col, (key, label) in enumerate(servo_labels):
            btn = tk.Button(
                self.test_frame,
                text=f"{label}\n[relaxed]",
                font=("Helvetica", 11, "bold"),
                command=lambda k=key: self._toggle_single_servo(k),
                bg="#dce6f2",
                fg="#182235",
                activebackground="#c8d8ea",
                activeforeground="#182235",
                bd=0,
                padx=14,
                pady=6,
            )
            btn.grid(row=2, column=col, padx=6, pady=(8, 4))
            self._servo_buttons[key] = btn

        self.test_status = tk.Label(
            self.test_frame,
            text="Press a button to move the servo.",
            font=("Helvetica", 12),
            fg="#b1c6de",
            bg="#0e1a2b",
        )
        self.test_status.grid(row=3, column=0, columnspan=5, pady=(6, 0))

    def schedule(self, delay_ms, callback):
        self.cancel_pending_job()
        self.pending_job = self.root.after(delay_ms, callback)

    def cancel_pending_job(self):
        if self.pending_job is not None:
            try:
                self.root.after_cancel(self.pending_job)
            except tk.TclError:
                pass
            self.pending_job = None

    def set_mode(self, mode):
        self.mode = mode
        self.mode_label = "Best of 3" if mode == "best_of_3" else "Unlimited"
        self.mode_value.config(text=f"Mode: {self.mode_label}")
        self.secondary_button.config(
            relief=tk.SUNKEN if mode == "best_of_3" else tk.RAISED,
            bg="#ffd166" if mode == "best_of_3" else "#dce6f2",
            fg="#182235",
        )
        self.tertiary_button.config(
            relief=tk.SUNKEN if mode == "unlimited" else tk.RAISED,
            bg="#ffd166" if mode == "unlimited" else "#dce6f2",
            fg="#182235",
        )

    def _detect_speech_command(self):
        if shutil.which("say"):
            return ["say", "-r", "260"]
        if shutil.which("espeak"):
            return ["espeak", "-s", "190"]
        return None

    def _stop_audio(self):
        if self.audio_process is not None and self.audio_process.poll() is None:
            self.audio_process.terminate()
        self.audio_process = None

    def _play_countdown_audio(self, word):
        self._stop_audio()
        spoken_word = AUDIO_WORDS.get(word, word)
        if self.speech_command is None:
            self.root.bell()
            return

        try:
            self.audio_process = subprocess.Popen(
                [*self.speech_command, spoken_word],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            self.audio_process = None
            self.root.bell()

    def reset_session(self):
        self.player_score = 0
        self.bot_score = 0
        self.tie_count = 0
        self.round_number = 0
        self.capture_started_at = 0.0
        self.capture_start_frame_idx = 0
        self.last_sampled_frame_idx = 0
        self.streak_gesture = None
        self.streak_count = 0
        self.bot_strategy.reset()
        self.recognizer.clear_round_context()
        self.recognizer.set_capture_logging(False)
        self.refresh_scoreboard()

    def refresh_scoreboard(self):
        self.mode_value.config(text=f"Mode: {self.mode_label}")
        self.score_value.config(
            text=f"You {self.player_score}  |  Bot {self.bot_score}  |  Ties {self.tie_count}"
        )
        self.round_value.config(text=f"Round {self.round_number}")

    def show_menu(self):
        self.cancel_pending_job()
        self._stop_audio()
        self.state = "menu"
        self.reset_session()
        self.title_label.config(text="Adaptive RPS")
        self.subtitle_label.config(text="Choose a mode, then start the game.")
        self.hero_label.config(text="START", fg="#ffd166")
        self.status_label.config(text="The webcam runs in the background. Show your hand only on SHOOT.")
        self.bot_move_label.config(text="Bot move: -")
        self.player_move_label.config(text="Your move: -")
        self.result_label.config(text="Result: -")
        self.primary_button.config(text="Start Game", command=self.start_game, state=tk.NORMAL)
        self.secondary_button.config(state=tk.NORMAL, text="Best of 3")
        self.tertiary_button.config(state=tk.NORMAL, text="Unlimited")
        self.menu_button.config(text="Quit", command=self.shutdown)
        self.test_frame.grid()  # show test panel on menu
        self.set_mode(self.mode)

    def start_game(self):
        self.cancel_pending_job()
        self.reset_session()
        self.test_frame.grid_remove()  # hide test panel during game
        self.state = "countdown"
        self.title_label.config(text="Adaptive RPS")
        self.subtitle_label.config(text="Follow the countdown and lock your hand on SHOOT.")
        self.menu_button.config(text="Back to Menu", command=self.show_menu)
        self.secondary_button.config(state=tk.DISABLED, text="Mode Locked")
        self.tertiary_button.config(state=tk.DISABLED, text=self.mode_label)
        self.primary_button.config(text="Round In Progress", state=tk.DISABLED)
        self.start_round()

    def start_round(self):
        self.cancel_pending_job()
        self.state = "countdown"
        self.round_number += 1
        self.refresh_scoreboard()
        self.bot_move_label.config(text="Bot move: hidden")
        self.player_move_label.config(text="Your move: waiting")
        self.result_label.config(text="Result: pending")
        self.status_label.config(text="Hold your hand ready. Only the SHOOT window counts.")
        # Park the robot hand at neutral so the bot's move is hidden during the countdown.
        self._send_hand_gesture("neutral")
        self._show_countdown_step(0)

    def _show_countdown_step(self, index):
        if index >= len(COUNTDOWN_WORDS):
            self.begin_capture_window()
            return

        word = COUNTDOWN_WORDS[index]
        color = "#ffd166" if word != "Shoot" else "#ef476f"
        self.hero_label.config(text=word.upper(), fg=color)
        self._play_countdown_audio(word)

        if word == "Shoot":
            self.status_label.config(text="Capture window open. Hold one gesture steady.")
            # Fire the physical hand at the exact moment of "Shoot" so the
            # servos start travelling to the bot's gesture as the player reveals.
            self._send_hand_gesture(self.bot_strategy.current_move)
            self.schedule(60, self.begin_capture_window)
        else:
            self.status_label.config(text=f"Countdown: {word}")
            self.schedule(COUNTDOWN_INTERVAL_MS, lambda: self._show_countdown_step(index + 1))

    def begin_capture_window(self):
        self.cancel_pending_job()
        self.state = "capture"
        latest = self.recognizer.get_latest_observation()
        self.capture_started_at = time.monotonic()
        self.capture_start_frame_idx = latest["frame_idx"]
        self.last_sampled_frame_idx = self.capture_start_frame_idx
        self.streak_gesture = None
        self.streak_count = 0
        self.recognizer.set_round_context(self.mode_label, self.round_number, self.bot_strategy.current_move)
        self.recognizer.set_capture_logging(True)
        self.bot_move_label.config(text="Bot move: hidden")
        self.player_move_label.config(text="Your move: capturing...")
        self.result_label.config(text="Result: evaluating...")
        self._poll_capture_window()

    def _poll_capture_window(self):
        latest = self.recognizer.get_latest_observation()

        if latest["frame_idx"] > self.last_sampled_frame_idx:
            self.last_sampled_frame_idx = latest["frame_idx"]

            if latest["frame_idx"] > self.capture_start_frame_idx and latest["valid"]:
                gesture = latest["gesture"]
                if gesture == self.streak_gesture:
                    self.streak_count += 1
                else:
                    self.streak_gesture = gesture
                    self.streak_count = 1

                if self.streak_count >= 2:
                    self.finish_round(gesture, capture_invalid=False)
                    return
            else:
                self.streak_gesture = None
                self.streak_count = 0

        if (time.monotonic() - self.capture_started_at) * 1000 >= CAPTURE_WINDOW_MS:
            self.finish_round(None, capture_invalid=True)
            return

        self.schedule(CAPTURE_POLL_MS, self._poll_capture_window)

    def finish_round(self, player_move, capture_invalid):
        self.cancel_pending_job()
        self.state = "result"
        self.recognizer.set_capture_logging(False)
        bot_move = self.bot_strategy.current_move

        if capture_invalid:
            self.tie_count += 1
            round_result = RoundResult(
                bot_move=bot_move,
                player_move="Invalid",
                outcome="tie",
                result_text="Tie / Invalid Capture",
                capture_invalid=True,
            )
        else:
            outcome = evaluate_round(player_move, bot_move)
            if outcome == "player_win":
                self.player_score += 1
                result_text = "You Win"
            elif outcome == "bot_win":
                self.bot_score += 1
                result_text = "Bot Wins"
            else:
                self.tie_count += 1
                result_text = "Tie"

            round_result = RoundResult(
                bot_move=bot_move,
                player_move=player_move,
                outcome=outcome,
                result_text=result_text,
                capture_invalid=False,
            )

        self.bot_strategy.update(round_result.outcome)
        self.refresh_scoreboard()
        self.hero_label.config(text=round_result.bot_move.upper(), fg="#7bdff2")
        self.status_label.config(
            text=f"Bot revealed {round_result.bot_move}. Show 'Next Round' when you are ready."
        )
        self.bot_move_label.config(text=f"Bot move: {round_result.bot_move}")
        self.player_move_label.config(text=f"Your move: {round_result.player_move}")
        self.result_label.config(text=f"Result: {round_result.result_text}")
        self.recognizer.log_round_summary(
            mode=self.mode_label,
            round_number=self.round_number,
            bot_move=round_result.bot_move,
            player_move=round_result.player_move,
            outcome=round_result.outcome,
            capture_invalid=round_result.capture_invalid,
        )

        # Return the robot hand to neutral after the player has had a moment
        # to see the reveal, so it isn't stuck holding the gesture.
        self.root.after(1500, lambda: self._send_hand_gesture("neutral"))

        if self.mode == "best_of_3" and (self.player_score >= 2 or self.bot_score >= 2):
            self.show_game_over()
            return

        self.primary_button.config(text="Next Round", command=self.start_round, state=tk.NORMAL)
        self.secondary_button.config(state=tk.DISABLED, text="Mode Locked")
        self.tertiary_button.config(state=tk.DISABLED, text=self.mode_label)
        self.menu_button.config(text="Back to Menu", command=self.show_menu)

    def show_game_over(self):
        self.state = "game_over"
        if self.player_score > self.bot_score:
            headline = "MATCH WON"
            status = "You took the Best of 3."
            color = "#06d6a0"
        else:
            headline = "MATCH LOST"
            status = "The bot took the Best of 3."
            color = "#ef476f"

        self.hero_label.config(text=headline, fg=color)
        self.status_label.config(text=status)
        self.primary_button.config(text="Play Again", command=self.start_game, state=tk.NORMAL)
        self.secondary_button.config(text="Best of 3", command=lambda: self.set_mode("best_of_3"), state=tk.NORMAL)
        self.tertiary_button.config(text="Unlimited", command=lambda: self.set_mode("unlimited"), state=tk.NORMAL)
        self.menu_button.config(text="Back to Menu", command=self.show_menu)

    def shutdown(self):
        self.cancel_pending_job()
        self._stop_camera_preview()
        self._stop_audio()
        self.recognizer.set_capture_logging(False)
        self.recognizer.stop()
        # Park the robot hand, then tell the worker to exit and wait briefly
        # for it so the final neutral reaches the Arduino before we close.
        if self.hand_queue is not None:
            self.hand_queue.put("neutral")
            self.hand_queue.put(None)
        if self.hand_thread is not None:
            self.hand_thread.join(timeout=3.0)
        if self.hand is not None:
            try:
                if self.hand.ser and self.hand.ser.is_open:
                    self.hand.ser.close()
            except Exception:
                pass
        self.root.destroy()


def launch_app():
    root = tk.Tk()
    try:
        RPSGameApp(root)
    except Exception:
        root.destroy()
        raise
    root.mainloop()
