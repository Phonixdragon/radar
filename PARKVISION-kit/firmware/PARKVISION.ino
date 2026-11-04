/*
  PARKVISION - Smart Parking Entrance Controller
  Board: Arduino UNO R3

  Hardware:
    HC-SR04: TRIG D7, ECHO D6
    SG90:    signal D9 (servo power from a separate regulated 5V supply)
    L298N:   ENA D5, IN1 D8, IN2 D4; motor on OUT1/OUT2

  Serial protocol at 9600 baud:
    ARM          Authorise one vehicle arrival (valid web check-in)
    DISARM       Remove authorisation (does not force-close a gate over an object)
    MOTOR_PULSE  Run the optional display motor briefly; auto-stops

  Telemetry lines:
    DIST:<cm> | DIST:OUT
    AUTH:ARMED | AUTH:DISARMED | AUTH:TIMEOUT
    VEHICLE:DETECTED
    GATE:OPEN | GATE:CLOSED | GATE:HELD
    MOTOR:ON | MOTOR:OFF

  Demo controller only. Do not use this as a real vehicle barrier controller.
*/

#include <Servo.h>

const byte TRIG_PIN = 7;
const byte ECHO_PIN = 6;
const byte SERVO_PIN = 9;

const byte MOTOR_ENA = 5;  // Remove the L298N ENA jumper and connect this pin.
const byte MOTOR_IN1 = 8;
const byte MOTOR_IN2 = 4;

// Keep false while the L298N and 12V geared motor are disconnected.
// Change to true only after the optional driver is correctly wired and tested.
const bool MOTOR_DRIVER_ENABLED = false;

const int GATE_CLOSED_ANGLE = 5;
const int GATE_OPEN_ANGLE = 92;

const float DETECT_DISTANCE_CM = 35.0;
const float CLEAR_DISTANCE_CM = 58.0;
const byte REQUIRED_DETECTIONS = 3;

const unsigned long SENSOR_INTERVAL_MS = 100;
const unsigned long TELEMETRY_INTERVAL_MS = 500;
const unsigned long CLEAR_HOLD_MS = 1800;
const unsigned long MIN_GATE_OPEN_MS = 1800;
const unsigned long AUTH_TIMEOUT_MS = 90000;
const unsigned long MOTOR_PULSE_MS = 2200;

const int MOTOR_PWM = 165; // Adjust only after confirming the motor is suitable for the L298N.

Servo barrierServo;

bool authorised = false;
bool gateOpen = false;
bool motorRunning = false;

byte detectionCount = 0;
unsigned long authStartedAt = 0;
unsigned long gateOpenedAt = 0;
unsigned long clearStartedAt = 0;
unsigned long motorStartedAt = 0;
unsigned long lastSensorAt = 0;
unsigned long lastTelemetryAt = 0;
float lastDistanceCm = 0.0;

char commandBuffer[40];
byte commandLength = 0;

void printDistance(float distanceCm) {
  if (distanceCm <= 0.0) {
    Serial.println(F("DIST:OUT"));
  } else {
    Serial.print(F("DIST:"));
    Serial.println(distanceCm, 1);
  }
}

float measureDistanceCm() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(3);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  // 25000 us is approximately the useful range needed for this small model.
  unsigned long duration = pulseIn(ECHO_PIN, HIGH, 25000UL);
  if (duration == 0) {
    return 0.0; // No echo / out of range.
  }

  return (duration * 0.0343f) / 2.0f;
}

void stopDisplayMotor() {
  analogWrite(MOTOR_ENA, 0);
  digitalWrite(MOTOR_IN1, LOW);
  digitalWrite(MOTOR_IN2, LOW);
  if (motorRunning) {
    motorRunning = false;
    Serial.println(F("MOTOR:OFF"));
  }
}

void startDisplayMotorPulse() {
  if (!MOTOR_DRIVER_ENABLED) {
    Serial.println(F("MOTOR:DISABLED"));
    return;
  }
  if (motorRunning) {
    Serial.println(F("MOTOR:BUSY"));
    return;
  }

  // One direction only; this is intended for a light display turntable/sign.
  digitalWrite(MOTOR_IN1, HIGH);
  digitalWrite(MOTOR_IN2, LOW);
  analogWrite(MOTOR_ENA, MOTOR_PWM);
  motorStartedAt = millis();
  motorRunning = true;
  Serial.println(F("MOTOR:ON"));
}

void handleCommand(const char *command) {
  if (strcmp(command, "ARM") == 0) {
    if (gateOpen) {
      Serial.println(F("AUTH:WAIT_GATE"));
      return;
    }
    authorised = true;
    detectionCount = 0;
    authStartedAt = millis();
    Serial.println(F("AUTH:ARMED"));
  } else if (strcmp(command, "DISARM") == 0) {
    authorised = false;
    detectionCount = 0;
    Serial.println(F("AUTH:DISARMED"));
    if (gateOpen) {
      Serial.println(F("GATE:HELD"));
    }
  } else if (strcmp(command, "MOTOR_PULSE") == 0) {
    startDisplayMotorPulse();
  } else {
    Serial.println(F("ERR:UNKNOWN_COMMAND"));
  }
}

void readSerialCommands() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\r') continue;

    if (c == '\n') {
      commandBuffer[commandLength] = '\0';
      if (commandLength > 0) handleCommand(commandBuffer);
      commandLength = 0;
    } else if (commandLength < sizeof(commandBuffer) - 1) {
      commandBuffer[commandLength++] = c;
    } else {
      commandLength = 0; // Discard an overlong command.
    }
  }
}

void updateGate(float distanceCm) {
  unsigned long now = millis();

  if (authorised && !gateOpen && (now - authStartedAt >= AUTH_TIMEOUT_MS)) {
    authorised = false;
    detectionCount = 0;
    Serial.println(F("AUTH:TIMEOUT"));
  }

  if (authorised && !gateOpen) {
    if (distanceCm > 0.0 && distanceCm <= DETECT_DISTANCE_CM) {
      if (detectionCount < REQUIRED_DETECTIONS) detectionCount++;
    } else {
      detectionCount = 0;
    }

    if (detectionCount >= REQUIRED_DETECTIONS) {
      authorised = false; // One valid check-in permits one gate cycle only.
      detectionCount = 0;
      barrierServo.write(GATE_OPEN_ANGLE);
      gateOpen = true;
      gateOpenedAt = now;
      clearStartedAt = 0;
      Serial.println(F("VEHICLE:DETECTED"));
      Serial.println(F("GATE:OPEN"));
    }
  }

  if (gateOpen) {
    // The barrier remains open while an object is still in the detection zone.
    // A no-echo reading is treated as clear for this small tabletop model.
    bool pathLooksClear = (distanceCm <= 0.0 || distanceCm > CLEAR_DISTANCE_CM);

    if (pathLooksClear) {
      if (clearStartedAt == 0) clearStartedAt = now;
    } else {
      clearStartedAt = 0;
    }

    if ((now - gateOpenedAt >= MIN_GATE_OPEN_MS) &&
        (clearStartedAt != 0) &&
        (now - clearStartedAt >= CLEAR_HOLD_MS)) {
      barrierServo.write(GATE_CLOSED_ANGLE);
      gateOpen = false;
      clearStartedAt = 0;
      Serial.println(F("GATE:CLOSED"));
    }
  }
}

void setup() {
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  if (MOTOR_DRIVER_ENABLED) {
    pinMode(MOTOR_ENA, OUTPUT);
    pinMode(MOTOR_IN1, OUTPUT);
    pinMode(MOTOR_IN2, OUTPUT);
    stopDisplayMotor();
  }

  digitalWrite(TRIG_PIN, LOW);

  barrierServo.attach(SERVO_PIN);
  barrierServo.write(GATE_CLOSED_ANGLE);

  Serial.begin(9600);
  delay(300);
  Serial.println(F("PARKVISION:READY"));
  Serial.println(F("GATE:CLOSED"));
}

void loop() {
  readSerialCommands();

  unsigned long now = millis();
  if (now - lastSensorAt >= SENSOR_INTERVAL_MS) {
    lastSensorAt = now;
    lastDistanceCm = measureDistanceCm();
    updateGate(lastDistanceCm);
  }

  if (now - lastTelemetryAt >= TELEMETRY_INTERVAL_MS) {
    lastTelemetryAt = now;
    printDistance(lastDistanceCm);
  }

  if (MOTOR_DRIVER_ENABLED && motorRunning && (now - motorStartedAt >= MOTOR_PULSE_MS)) {
    stopDisplayMotor();
  }
}
