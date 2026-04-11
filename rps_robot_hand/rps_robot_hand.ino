/*
 * Rock-Paper-Scissors Robot Hand Controller (2-servo version)
 *
 * Receives a single character over serial from Python:
 *   'R' = Rock     (both servos clench — all fingers closed)
 *   'P' = Paper    (both servos relax — all fingers open)
 *   'S' = Scissors (servo 1 relax, servo 2 clench — index+middle out, rest folded)
 *   'N' = Neutral  (both clenched, same as Rock — rest position)
 *
 * Responds with 'OK\n' after reaching position.
 *
 * Wiring:
 *   Servo 1 (index + middle fingers)       -> D3
 *   Servo 2 (ring + pinky + thumb)         -> D5
 */

#include <Servo.h>

// ─── Pin assignments ───────────────────────────────────────
#define SERVO_A_PIN  3   // Index + middle fingers
#define SERVO_B_PIN  5   // Ring + pinky + thumb

// ─── Servo angle calibration ──────────────────────────────
// ENGAGED = the servo is pulling / clenching
// RELAXED = the servo is released / not pulling
// Adjust these to match your hand's actual range of motion.

#define SERVO_A_ENGAGED   10
#define SERVO_A_RELAXED  170

#define SERVO_B_ENGAGED   10
#define SERVO_B_RELAXED  170

// ─── Servo objects ─────────────────────────────────────────
Servo servoA;  // index + middle
Servo servoB;  // ring + pinky + thumb

// ─── Gesture definitions ──────────────────────────────────

void gestureRock() {
  // Both servos clench — full fist
  servoA.write(SERVO_A_ENGAGED);
  servoB.write(SERVO_B_ENGAGED);
}

void gesturePaper() {
  // Both servos relax — all fingers open
  servoA.write(SERVO_A_RELAXED);
  servoB.write(SERVO_B_RELAXED);
}

void gestureScissors() {
  // Servo A relaxed (index+middle extended), Servo B engaged (other 3 folded)
  servoA.write(SERVO_A_RELAXED);
  servoB.write(SERVO_B_ENGAGED);
}

void gestureNeutral() {
  // Rest position — both clenched (same as Rock).
  gestureRock();
}

// ─── Setup ─────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);

  servoA.attach(SERVO_A_PIN);
  servoB.attach(SERVO_B_PIN);

  gestureNeutral();

  Serial.println("READY");
}

// ─── Main loop ─────────────────────────────────────────────
void loop() {
  if (Serial.available() > 0) {
    char cmd = Serial.read();

    // Flush any extra bytes (e.g. newline characters)
    while (Serial.available() > 0) {
      Serial.read();
    }

    switch (cmd) {
      case 'R':
      case 'r':
        gestureRock();
        Serial.println("OK");
        break;

      case 'P':
      case 'p':
        gesturePaper();
        Serial.println("OK");
        break;

      case 'S':
      case 's':
        gestureScissors();
        Serial.println("OK");
        break;

      case 'N':
      case 'n':
        gestureNeutral();
        Serial.println("OK");
        break;

      case '?':
        Serial.println("READY");
        break;

      // Individual servo test commands — move ONE servo without touching
      // the other. Useful for wiring checks and calibration.
      case '1':  // Servo A engaged
        servoA.write(SERVO_A_ENGAGED);
        Serial.println("OK");
        break;
      case '2':  // Servo A relaxed
        servoA.write(SERVO_A_RELAXED);
        Serial.println("OK");
        break;
      case '3':  // Servo B engaged
        servoB.write(SERVO_B_ENGAGED);
        Serial.println("OK");
        break;
      case '4':  // Servo B relaxed
        servoB.write(SERVO_B_RELAXED);
        Serial.println("OK");
        break;

      default:
        Serial.println("ERR");
        break;
    }
  }
}
