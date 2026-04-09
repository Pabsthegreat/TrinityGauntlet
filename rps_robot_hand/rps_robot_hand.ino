/*
 * Rock-Paper-Scissors Robot Hand Controller
 * 
 * Receives a single character over serial from Python:
 *   'R' = Rock   (all fingers closed)
 *   'P' = Paper  (all fingers open)
 *   'S' = Scissors (index + middle open, rest closed)
 *   'N' = Neutral / rest position
 * 
 * Responds with 'OK\n' after reaching position.
 * 
 * Wiring:
 *   Servo 1 (Thumb)  -> D3
 *   Servo 2 (Index)  -> D5
 *   Servo 3 (Middle) -> D6
 *   Servo 4 (Ring)   -> D9
 *   Servo 5 (Pinky)  -> D10
 *   All servo power  -> External 5V PSU (NOT Arduino 5V)
 *   All grounds       -> Common (PSU GND + Arduino GND tied together)
 */

#include <Servo.h>

// ─── Pin assignments ───────────────────────────────────────
#define THUMB_PIN   3
#define INDEX_PIN   5
#define MIDDLE_PIN  6
#define RING_PIN    9
#define PINKY_PIN  10

// ─── Servo angle calibration ──────────────────────────────
// Adjust these to match YOUR 3D-printed hand's range of motion.
// OPEN  = finger fully extended
// CLOSED = finger fully curled (fist)
// Tip: move each servo by hand to find the exact angles, then update here.

#define THUMB_OPEN    10
#define THUMB_CLOSED  170

#define INDEX_OPEN    10
#define INDEX_CLOSED  170

#define MIDDLE_OPEN   10
#define MIDDLE_CLOSED 170

#define RING_OPEN     10
#define RING_CLOSED   170

#define PINKY_OPEN    10
#define PINKY_CLOSED  170

// ─── Servo objects ─────────────────────────────────────────
Servo thumbServo;
Servo indexServo;
Servo middleServo;
Servo ringServo;
Servo pinkyServo;

// ─── Gesture definitions ──────────────────────────────────
// Each gesture is an array of 5 target angles:
// {thumb, index, middle, ring, pinky}

void setGesture(int thumb, int index, int middle, int ring, int pinky) {
  // Write all servos as fast as possible — no sequential delays.
  // Servos move simultaneously since write() is non-blocking.
  thumbServo.write(thumb);
  indexServo.write(index);
  middleServo.write(middle);
  ringServo.write(ring);
  pinkyServo.write(pinky);
}

void gestureRock() {
  setGesture(THUMB_CLOSED, INDEX_CLOSED, MIDDLE_CLOSED, RING_CLOSED, PINKY_CLOSED);
}

void gesturePaper() {
  setGesture(THUMB_OPEN, INDEX_OPEN, MIDDLE_OPEN, RING_OPEN, PINKY_OPEN);
}

void gestureScissors() {
  // Index and middle open, thumb/ring/pinky closed
  setGesture(THUMB_CLOSED, INDEX_OPEN, MIDDLE_OPEN, RING_CLOSED, PINKY_CLOSED);
}

void gestureNeutral() {
  // Half-open resting position (reduces servo strain when idle)
  int thumbMid  = (THUMB_OPEN  + THUMB_CLOSED)  / 2;
  int indexMid  = (INDEX_OPEN  + INDEX_CLOSED)  / 2;
  int middleMid = (MIDDLE_OPEN + MIDDLE_CLOSED) / 2;
  int ringMid   = (RING_OPEN   + RING_CLOSED)   / 2;
  int pinkyMid  = (PINKY_OPEN  + PINKY_CLOSED)  / 2;
  setGesture(thumbMid, indexMid, middleMid, ringMid, pinkyMid);
}

// ─── Setup ─────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);  // High baud rate to minimize serial latency
  
  // Attach all servos
  thumbServo.attach(THUMB_PIN);
  indexServo.attach(INDEX_PIN);
  middleServo.attach(MIDDLE_PIN);
  ringServo.attach(RING_PIN);
  pinkyServo.attach(PINKY_PIN);
  
  // Start in neutral position
  gestureNeutral();
  
  // Signal ready
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
        // Health check / ping
        Serial.println("READY");
        break;
        
      default:
        Serial.println("ERR");
        break;
    }
  }
}
