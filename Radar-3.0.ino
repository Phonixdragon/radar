
/*
  ORBIT RADAR - Arduino UNO R3

  Serial format at 9600 baud:
  angle,distance_cm,motor_state
  Example: 42.5,36.2,ON

  Two-terminal switch:
    D4 --- switch --- GND
    Closed = motor ON
    Open   = motor OFF

  HC-SR04:
    TRIG -> D10
    ECHO -> D11

  L298N:
    ENA -> D5 (remove ENA jumper)
    IN1 -> D7
    IN2 -> D8
    OUT1, OUT2 -> motor
*/

const byte SWITCH_PIN = 4;

const byte ENA_PIN = 5;
const byte IN1_PIN = 7;
const byte IN2_PIN = 8;

const byte TRIG_PIN = 10;
const byte ECHO_PIN = 11;

const int MOTOR_PWM = 160;

// Calibrated time for one estimated 180-degree sweep.
const unsigned long SWEEP_TIME_MS = 970;

const unsigned long SAMPLE_INTERVAL_MS = 60;
const unsigned long ECHO_TIMEOUT_US = 20000UL;

float angleDeg = 0.0;
int direction = 1;

bool motorEnabled = false;
bool previousMotorEnabled = false;

unsigned long lastUpdateMs = 0;
unsigned long lastSampleMs = 0;

void stopMotor() {
  analogWrite(ENA_PIN, 0);
  digitalWrite(IN1_PIN, LOW);
  digitalWrite(IN2_PIN, LOW);
}

void driveMotor(int dir) {
  if (dir > 0) {
    digitalWrite(IN1_PIN, HIGH);
    digitalWrite(IN2_PIN, LOW);
  } else {
    digitalWrite(IN1_PIN, LOW);
    digitalWrite(IN2_PIN, HIGH);
  }

  analogWrite(ENA_PIN, MOTOR_PWM);
}

float measureDistanceCm() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(3);

  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  unsigned long duration =
    pulseIn(ECHO_PIN, HIGH, ECHO_TIMEOUT_US);

  if (duration == 0) {
    return -1.0;
  }

  float distanceCm = duration / 58.0;

  if (distanceCm < 2.0 || distanceCm > 350.0) {
    return -1.0;
  }

  return distanceCm;
}

void setup() {
  pinMode(SWITCH_PIN, INPUT_PULLUP);

  pinMode(ENA_PIN, OUTPUT);
  pinMode(IN1_PIN, OUTPUT);
  pinMode(IN2_PIN, OUTPUT);

  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);

  digitalWrite(TRIG_PIN, LOW);
  stopMotor();

  Serial.begin(9600);

  lastUpdateMs = millis();
  lastSampleMs = millis();
}

void loop() {
  unsigned long now = millis();

  // A closed switch pulls D4 LOW.
  motorEnabled = (digitalRead(SWITCH_PIN) == LOW);

  // Start or stop the motor when the switch changes.
  if (motorEnabled != previousMotorEnabled) {
    lastUpdateMs = now;

    if (motorEnabled) {
      driveMotor(direction);
    } else {
      stopMotor();
    }

    previousMotorEnabled = motorEnabled;
  }

  // Estimate angle only while motor is enabled.
  if (motorEnabled) {
    unsigned long dt = now - lastUpdateMs;
    lastUpdateMs = now;

    float degreesPerMs = 180.0 / SWEEP_TIME_MS;
    angleDeg += direction * degreesPerMs * dt;

    if (angleDeg >= 180.0) {
      angleDeg = 180.0;
      direction = -1;
      driveMotor(direction);
    } else if (angleDeg <= 0.0) {
      angleDeg = 0.0;
      direction = 1;
      driveMotor(direction);
    }
  } else {
    lastUpdateMs = now;
  }

  // Send distance and status continuously, even when motor is OFF.
  if (now - lastSampleMs >= SAMPLE_INTERVAL_MS) {
    lastSampleMs = now;

    float distanceCm = measureDistanceCm();

    Serial.print(angleDeg, 1);
    Serial.print(',');

    Serial.print(distanceCm, 1);
    Serial.print(',');

    Serial.println(motorEnabled ? "ON" : "OFF");
  }
}
