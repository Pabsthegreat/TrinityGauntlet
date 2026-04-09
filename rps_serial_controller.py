"""
Rock-Paper-Scissors Robot — Python Serial Controller

Sends gesture commands to the Arduino over serial.
Drop-in integration: call send_gesture() from your vision code.

Usage:
    from rps_serial_controller import RPSController

    bot = RPSController(port="/dev/ttyUSB0")  # or "COM3" on Windows
    bot.send_gesture("rock")
    bot.send_gesture("paper")
    bot.send_gesture("scissors")
    bot.close()

Requirements:
    pip install pyserial
"""

import serial
import serial.tools.list_ports
import time
import sys


class RPSController:
    """Manages serial communication with the Arduino hand."""

    GESTURE_MAP = {
        "rock":     b"R",
        "paper":    b"P",
        "scissors": b"S",
        "neutral":  b"N",
    }

    def __init__(self, port: str = "/dev/ttyUSB0", baud: int = 115200, timeout: float = 2.0):
        """
        Open the serial connection and wait for the Arduino to be ready.

        Args:
            port: Serial port (e.g. "/dev/ttyUSB0", "/dev/ttyACM0", "COM3").
            baud: Must match the Arduino sketch (default 115200).
            timeout: Read timeout in seconds.
        """
        self.ser = serial.Serial(port, baud, timeout=timeout)

        # Arduino resets on serial open — wait for the "READY" signal
        print(f"[RPS] Connecting to {port}...")
        self._wait_for_ready()
        print("[RPS] Arduino ready.")

    def _wait_for_ready(self, max_wait: float = 5.0):
        """Block until the Arduino sends 'READY'."""
        start = time.time()
        while time.time() - start < max_wait:
            if self.ser.in_waiting:
                line = self.ser.readline().decode("utf-8", errors="ignore").strip()
                if line == "READY":
                    return
        raise TimeoutError("Arduino did not send READY within timeout.")

    def send_gesture(self, gesture: str) -> float:
        """
        Send a gesture command and wait for acknowledgement.

        Args:
            gesture: One of "rock", "paper", "scissors", "neutral".

        Returns:
            Round-trip time in milliseconds (serial send + Arduino ACK).

        Raises:
            ValueError: If the gesture name is invalid.
            TimeoutError: If the Arduino doesn't respond.
        """
        gesture = gesture.lower().strip()
        if gesture not in self.GESTURE_MAP:
            raise ValueError(
                f"Unknown gesture '{gesture}'. "
                f"Valid: {list(self.GESTURE_MAP.keys())}"
            )

        cmd = self.GESTURE_MAP[gesture]
        t0 = time.perf_counter()

        self.ser.write(cmd)
        self.ser.flush()

        # Wait for "OK" acknowledgement
        response = self.ser.readline().decode("utf-8", errors="ignore").strip()
        elapsed_ms = (time.perf_counter() - t0) * 1000

        if response == "OK":
            return elapsed_ms
        elif response == "ERR":
            raise RuntimeError(f"Arduino returned ERR for gesture '{gesture}'")
        else:
            raise TimeoutError(
                f"Unexpected response: '{response}' (expected 'OK')"
            )

    def ping(self) -> bool:
        """Check if the Arduino is responsive."""
        self.ser.write(b"?")
        self.ser.flush()
        response = self.ser.readline().decode("utf-8", errors="ignore").strip()
        return response == "READY"

    def close(self):
        """Close the serial connection. Safe to call multiple times; never raises."""
        try:
            if self.ser and self.ser.is_open:
                try:
                    self.send_gesture("neutral")  # Park the hand
                except Exception:
                    pass
                self.ser.close()
                print("[RPS] Connection closed.")
        except Exception:
            pass

    @staticmethod
    def autodetect_port():
        """
        Scan serial ports and return the first one that looks like an Arduino.

        Matches common USB-serial chips used on Unos and clones:
          - FTDI FT232R  (VID 0403:6001)  — classic Uno clones
          - WCH CH340/CH341 (VID 1a86)    — cheaper clones
          - SiLabs CP210x                 — some ESP/clones
          - Arduino native USB (VID 2341) — genuine R3
        Also falls back to matching macOS device-name hints (usbmodem/usbserial).

        Returns:
            str or None: Device path (e.g. "/dev/cu.usbserial-A5069RR4"), or
            None if no candidate is found.
        """
        for p in serial.tools.list_ports.comports():
            desc = (p.description or "").lower()
            dev = (p.device or "").lower()
            hwid = (p.hwid or "").lower()
            if ("ft232" in desc or "ch340" in desc or "ch341" in desc
                    or "cp210" in desc or "arduino" in desc
                    or "usbmodem" in dev or "usbserial" in dev
                    or "0403:6001" in hwid or "1a86:" in hwid
                    or "2341:" in hwid or "10c4:" in hwid):
                return p.device
        return None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


# ─── Quick test ─────────────────────────────────────────────
if __name__ == "__main__":
    port = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyUSB0"

    with RPSController(port=port) as bot:
        for gesture in ["rock", "paper", "scissors", "neutral"]:
            ms = bot.send_gesture(gesture)
            print(f"  {gesture:>10s}  ->  {ms:.1f} ms round-trip")
            time.sleep(1)

    print("Done.")
