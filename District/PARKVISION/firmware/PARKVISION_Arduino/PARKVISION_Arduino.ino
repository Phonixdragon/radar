#include <Servo.h>

// PARKVISION single physical bay controller
// HC-SR04: TRIG D10, ECHO D11; servo signal D9.
// Servo power must come from a separate regulated supply (check its label).

const byte TRIG_PIN = 10;
const byte ECHO_PIN = 11;
const byte SERVO_PIN = 9;

// CALIBRATE THIS after testing the empty bay and toy car.
// Example only: change this value to suit your ceiling height and car model.
const float OCCUPIED_THRESHOLD_CM = 18.0;
const float CLEAR_THRESHOLD_CM = 21.0; // hysteresis prevents rapid toggling

const int GATE_CLOSED_ANGLE = 8;  // adjust gently after testing the linkage
const int GATE_OPEN_ANGLE = 92;   // adjust gently after testing the linkage
const unsigned long SENSOR_INTERVAL_MS = 250;
const unsigned long OCCUPANCY_CONFIRM_MS = 900;
const unsigned long CLOSE_AFTER_OCCUPANCY_MS = 10000;
const unsigned long GATE_FAILSAFE_MS = 30000;

Servo gateServo;
bool occupied = false;
bool gateOpen = false;
unsigned long lastSensorMs = 0;
unsigned long occupiedSince = 0;
unsigned long gateOpenedAt = 0;
unsigned long candidateSince = 0;
bool candidateOccupied = false;
String commandBuffer;

float readDistanceCm() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(3);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);
  unsigned long duration = pulseIn(ECHO_PIN, HIGH, 30000UL);
  if (duration == 0) return -1.0;
  return duration / 58.0;
}

void setGate(bool openGate) {
  // Mechanical limits vary. Keep the barrier lightweight and clear of the toy car.
  gateServo.write(openGate ? GATE_OPEN_ANGLE : GATE_CLOSED_ANGLE);
  gateOpen = openGate;
  if (openGate) gateOpenedAt = millis();
  Serial.print("GATE,");
  Serial.println(openGate ? "OPEN" : "CLOSED");
}

void acceptCommand(String command) {
  command.trim();
  command.toUpperCase();
  if (command == "OPEN_GATE") {
    if (!occupied) setGate(true);
    else Serial.println("WARN,BAY_ALREADY_OCCUPIED");
  } else if (command == "CLOSE_GATE") {
    setGate(false);
  }
}

void readCommands() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      if (commandBuffer.length() > 0) {
        acceptCommand(commandBuffer);
        commandBuffer = "";
      }
    } else if (commandBuffer.length() < 40) {
      commandBuffer += c;
    }
  }
}

void updateOccupancy(float distanceCm) {
  if (distanceCm < 0) return;
  bool desired = occupied;
  if (!occupied && distanceCm <= OCCUPIED_THRESHOLD_CM) desired = true;
  if (occupied && distanceCm >= CLEAR_THRESHOLD_CM) desired = false;

  if (desired != occupied) {
    if (desired != candidateOccupied) {
      candidateOccupied = desired;
      candidateSince = millis();
    } else if (millis() - candidateSince >= OCCUPANCY_CONFIRM_MS) {
      occupied = desired;
      Serial.print("OCCUPANCY,");
      Serial.println(occupied ? "1" : "0");
      if (occupied) occupiedSince = millis();
    }
  } else {
    candidateOccupied = occupied;
  }
}

void setup() {
  Serial.begin(9600);
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  digitalWrite(TRIG_PIN, LOW);
  gateServo.attach(SERVO_PIN);
  gateServo.write(GATE_CLOSED_ANGLE);
  delay(400);
  Serial.println("PARKVISION,READY");
  Serial.println("GATE,CLOSED");
}

void loop() {
  readCommands();

  unsigned long now = millis();
  if (now - lastSensorMs >= SENSOR_INTERVAL_MS) {
    lastSensorMs = now;
    float distanceCm = readDistanceCm();
    if (distanceCm > 0) {
      Serial.print("DIST,");
      Serial.println(distanceCm, 1);
      updateOccupancy(distanceCm);
    }
  }

  if (gateOpen) {
    bool confirmedCar = occupied && occupiedSince > gateOpenedAt;
    bool occupancyWaitFinished = confirmedCar && (now - occupiedSince >= CLOSE_AFTER_OCCUPANCY_MS);
    bool failsafe = (now - gateOpenedAt >= GATE_FAILSAFE_MS);
    if (occupancyWaitFinished || failsafe) {
      setGate(false);
    }
  }
}
