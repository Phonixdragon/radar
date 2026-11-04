/*
  PARKVISION - Single Shared Entrance Gate
  Board: Arduino UNO R3

  MAIN HARDWARE (same pins as the earlier PARKVISION build):
    HC-SR04 TRIG -> D7
    HC-SR04 ECHO -> D6
    SG90 signal -> D9
    Servo power -> separate regulated 5V supply; common GND with Arduino

  OPTIONAL L298N (NOT USED in the current build):
    ENA -> D5, IN1 -> D8, IN2 -> D4
    Set USE_L298N to true only after the motor driver and motor are wired safely.
    Leave USE_L298N false and leave the L298N/motor disconnected for this build.

  Serial protocol, 9600 baud, newline terminated:
    OPEN         Open the barrier only while a vehicle is detected within 8 cm
    CLOSE        Request closure; it will wait until the sensor area is clear
    ARM          Legacy/test mode: open on the next stable vehicle detection
    DISARM       Cancel ARM mode
    MOTOR_PULSE  Optional L298N demo pulse (disabled by default)
    MOTOR_STOP   Stop optional motor

  Serial events:
    DIST:<cm> or DIST:OUT
    PRESENCE:ON / PRESENCE:OFF
    GATE:OPEN / GATE:CLOSED / GATE:HELD
    AUTH:ARMED / AUTH:DISARMED
    MOTOR:ON / MOTOR:OFF / MOTOR:DISABLED

  IMPORTANT: This is a small science-fair model controller, not a certified
  real-world vehicle barrier or safety system. Use a lightweight model arm only.
*/

#include <Servo.h>
#include <string.h>

// -------------------- MAIN PIN CONNECTIONS --------------------
const byte TRIG_PIN  = 7;
const byte ECHO_PIN  = 6;
const byte SERVO_PIN = 9;

// -------------------- OPTIONAL L298N PINS ---------------------
const byte MOTOR_ENA = 5;
const byte MOTOR_IN1 = 8;
const byte MOTOR_IN2 = 4;
const bool USE_L298N = false;       // KEEP FALSE: L298N is not being used.
const int MOTOR_PWM = 160;
const unsigned long MOTOR_PULSE_MS = 1800UL;

// -------------------- SENSOR SETTINGS -------------------------
// The vehicle should stop close to the sensor. A stable reading at or below
// 8 cm triggers presence. Once present, it remains present until readings
// are at least 12 cm away (or no echo) for several consecutive samples.
const float DETECT_DISTANCE_CM = 8.0;
const float CLEAR_DISTANCE_CM  = 12.0;
const float MIN_VALID_DISTANCE_CM = 2.0;
const byte DETECT_SAMPLES = 3;
const byte CLEAR_SAMPLES  = 5;
const unsigned long SENSOR_INTERVAL_MS = 100UL;
const unsigned long TELEMETRY_INTERVAL_MS = 350UL;

// -------------------- BARRIER SETTINGS ------------------------
const int GATE_CLOSED_ANGLE = 5;
const int GATE_OPEN_ANGLE   = 92;
const unsigned long MIN_GATE_OPEN_MS = 1800UL;
const unsigned long CLEAR_HOLD_MS = 1300UL;

Servo barrierServo;
bool vehiclePresent = false;
bool gateOpen = false;
bool legacyArmed = false;
bool closeRequested = false;
bool motorRunning = false;

byte nearCount = 0;
byte clearCount = 0;
float lastDistanceCm = -1.0;
unsigned long gateOpenedAt = 0;
unsigned long clearStartedAt = 0;
unsigned long lastSensorAt = 0;
unsigned long lastTelemetryAt = 0;
unsigned long motorStartedAt = 0;

char commandBuffer[40];
byte commandLength = 0;

float measureDistanceCm() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(3);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  // 5000 microseconds is ample for this short-range entrance sensor.
  const unsigned long duration = pulseIn(ECHO_PIN, HIGH, 5000UL);
  if (duration == 0) return -1.0;
  return (duration * 0.0343f) / 2.0f;
}

void printDistance(float cm) {
  if (cm < 0.0) {
    Serial.println(F("DIST:OUT"));
  } else {
    Serial.print(F("DIST:"));
    Serial.println(cm, 1);
  }
}

void stopOptionalMotor() {
  if (!USE_L298N) return;
  analogWrite(MOTOR_ENA, 0);
  digitalWrite(MOTOR_IN1, LOW);
  digitalWrite(MOTOR_IN2, LOW);
  if (motorRunning) {
    motorRunning = false;
    Serial.println(F("MOTOR:OFF"));
  }
}

void startOptionalMotor() {
  if (!USE_L298N) {
    Serial.println(F("MOTOR:DISABLED"));
    return;
  }
  if (motorRunning) return;
  digitalWrite(MOTOR_IN1, HIGH);
  digitalWrite(MOTOR_IN2, LOW);
  analogWrite(MOTOR_ENA, MOTOR_PWM);
  motorStartedAt = millis();
  motorRunning = true;
  Serial.println(F("MOTOR:ON"));
}

void openGate() {
  if (gateOpen) {
    Serial.println(F("GATE:OPEN"));
    return;
  }
  if (!vehiclePresent) {
    Serial.println(F("ERR:NO_VEHICLE"));
    return;
  }
  barrierServo.write(GATE_OPEN_ANGLE);
  gateOpen = true;
  closeRequested = false;
  gateOpenedAt = millis();
  clearStartedAt = 0;
  Serial.println(F("GATE:OPEN"));
}

void requestGateClose() {
  closeRequested = true;
  if (vehiclePresent) {
    Serial.println(F("GATE:HELD"));
  } else {
    Serial.println(F("GATE:CLOSE_REQUESTED"));
  }
}

void handleCommand(const char *command) {
  if (strcmp(command, "OPEN") == 0) {
    openGate();
  } else if (strcmp(command, "CLOSE") == 0) {
    requestGateClose();
  } else if (strcmp(command, "ARM") == 0) {
    legacyArmed = true;
    Serial.println(F("AUTH:ARMED"));
    if (vehiclePresent) {
      legacyArmed = false;
      openGate();
    }
  } else if (strcmp(command, "DISARM") == 0) {
    legacyArmed = false;
    Serial.println(F("AUTH:DISARMED"));
  } else if (strcmp(command, "MOTOR_PULSE") == 0) {
    startOptionalMotor();
  } else if (strcmp(command, "MOTOR_STOP") == 0) {
    stopOptionalMotor();
  } else {
    Serial.println(F("ERR:UNKNOWN_COMMAND"));
  }
}

void readSerialCommands() {
  while (Serial.available() > 0) {
    const char c = (char)Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      commandBuffer[commandLength] = '\0';
      if (commandLength > 0) handleCommand(commandBuffer);
      commandLength = 0;
    } else if (commandLength < sizeof(commandBuffer) - 1) {
      commandBuffer[commandLength++] = c;
    } else {
      commandLength = 0;
    }
  }
}

void updatePresence(float cm) {
  if (!vehiclePresent) {
    if (cm >= MIN_VALID_DISTANCE_CM && cm <= DETECT_DISTANCE_CM) {
      if (nearCount < DETECT_SAMPLES) nearCount++;
    } else {
      nearCount = 0;
    }

    if (nearCount >= DETECT_SAMPLES) {
      vehiclePresent = true;
      nearCount = 0;
      clearCount = 0;
      Serial.println(F("PRESENCE:ON"));
      if (legacyArmed) {
        legacyArmed = false;
        openGate();
      }
    }
  } else {
    // Hysteresis avoids flickering when the reading sits around 8 cm.
    if (cm < 0.0 || cm >= CLEAR_DISTANCE_CM) {
      if (clearCount < CLEAR_SAMPLES) clearCount++;
    } else {
      clearCount = 0;
    }

    if (clearCount >= CLEAR_SAMPLES) {
      vehiclePresent = false;
      clearCount = 0;
      nearCount = 0;
      Serial.println(F("PRESENCE:OFF"));
      clearStartedAt = millis();
    }
  }
}

void updateGate() {
  if (!gateOpen) return;

  const unsigned long now = millis();
  if (vehiclePresent) {
    clearStartedAt = 0;
    return;
  }
  if (clearStartedAt == 0) clearStartedAt = now;

  const bool minimumTimePassed = (now - gateOpenedAt) >= MIN_GATE_OPEN_MS;
  const bool areaClearLongEnough = (now - clearStartedAt) >= CLEAR_HOLD_MS;
  if (minimumTimePassed && areaClearLongEnough) {
    barrierServo.write(GATE_CLOSED_ANGLE);
    gateOpen = false;
    closeRequested = false;
    clearStartedAt = 0;
    Serial.println(F("GATE:CLOSED"));
  }
}

void setup() {
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  digitalWrite(TRIG_PIN, LOW);

  if (USE_L298N) {
    pinMode(MOTOR_ENA, OUTPUT);
    pinMode(MOTOR_IN1, OUTPUT);
    pinMode(MOTOR_IN2, OUTPUT);
    stopOptionalMotor();
  }

  Serial.begin(9600);
  barrierServo.attach(SERVO_PIN);
  barrierServo.write(GATE_CLOSED_ANGLE);
  delay(300);
  Serial.println(F("PARKVISION:SINGLE_GATE_READY"));
  Serial.println(F("GATE:CLOSED"));
}

void loop() {
  readSerialCommands();

  const unsigned long now = millis();
  if (now - lastSensorAt >= SENSOR_INTERVAL_MS) {
    lastSensorAt = now;
    lastDistanceCm = measureDistanceCm();
    updatePresence(lastDistanceCm);
    updateGate();
  }

  if (now - lastTelemetryAt >= TELEMETRY_INTERVAL_MS) {
    lastTelemetryAt = now;
    printDistance(lastDistanceCm);
  }

  if (USE_L298N && motorRunning && (now - motorStartedAt >= MOTOR_PULSE_MS)) {
    stopOptionalMotor();
  }
}
