
import processing.serial.*;

// ======================================================
// ORBIT RADAR - Processing 4 / Java mode
// Incoming Arduino data:
// angle,distance_cm,motor_state
// Example: 45.0,32.5,ON
// ======================================================

// ---------- SETTINGS ----------
int PORT_INDEX = 5;           // Change after checking Serial.list()
int BAUD_RATE = 9600;

float MAX_RANGE_CM = 250;
float OBSTACLE_LIMIT_CM = 50;
float SWEEP_TIME_MS = 970;

// ---------- SERIAL CONNECTION ----------
Serial arduinoPort;
boolean portOpen = false;
String connectionStatus = "PORT NOT OPEN";
String motorState = "WAITING";
long lastDataMillis = -10000;

// ---------- LIVE DATA ----------
float currentAngle = 0;
float currentDistance = -1;
boolean validDistance = false;

int validReadings = 0;
int closeReadings = 0;

// Latest scan return for each whole degree.
// Angle is estimated by Arduino, not read from an encoder.
float[] storedDistance = new float[181];
boolean[] storedValid = new boolean[181];

// ---------- THEME ----------
int bg = color(4, 12, 20);
int panel = color(10, 24, 36);
int panelDark = color(6, 17, 27);
int green = color(35, 255, 155);
int greenDim = color(20, 100, 75);
int cyan = color(64, 210, 255);
int red = color(255, 75, 91);
int amber = color(255, 190, 75);
int white = color(225, 240, 247);
int muted = color(120, 154, 174);

PFont regularFont;
PFont boldFont;

// Radar geometry
float radarX = 385;
float radarY = 610;
float radarR = 267;

// ---------- STARTUP ----------
void setup() {
  size(1150, 730);
  smooth(4);
  surface.setTitle("ORBIT | Arduino Radar Console");

  regularFont = createFont("Monospaced", 12);
  boldFont = createFont("Monospaced.bold", 15);

  for (int a = 0; a <= 180; a++) {
    storedDistance[a] = -1;
    storedValid[a] = false;
  }

  println("=================================");
  println("ORBIT RADAR - AVAILABLE PORTS");
  printArray(Serial.list());
  println("=================================");

  String[] ports = Serial.list();

  if (ports.length == 0) {
    connectionStatus = "NO SERIAL PORT FOUND";
    return;
  }

  if (PORT_INDEX < 0 || PORT_INDEX >= ports.length) {
    connectionStatus = "INVALID PORT INDEX";
    println("Change PORT_INDEX to a valid list position.");
    return;
  }

  try {
    arduinoPort = new Serial(
      this, ports[PORT_INDEX], BAUD_RATE
    );

    arduinoPort.clear();
    arduinoPort.bufferUntil('\n');

    portOpen = true;
    connectionStatus = "PORT OPEN - WAITING FOR DATA";

  } catch (Exception e) {
    portOpen = false;
    connectionStatus = "COULD NOT OPEN PORT";
    println("Serial error: " + e.getMessage());
  }
}

// ---------- MAIN DISPLAY ----------
void draw() {
  background(bg);

  boolean dataLive = portOpen &&
    lastDataMillis > 0 &&
    millis() - lastDataMillis < 2500;

  drawHeader(dataLive);
  drawRadar(dataLive);
  drawTelemetry(dataLive);
  drawFooter(dataLive);
}

// ---------- HEADER ----------
void drawHeader(boolean dataLive) {
  noStroke();
  fill(panel);
  rect(0, 0, width, 72);

  fill(green);
  textFont(boldFont);
  textSize(23);
  textAlign(LEFT, CENTER);
  text("ORBIT", 24, 25);

  fill(muted);
  textFont(regularFont);
  textSize(10);
  text("ULTRASONIC RADAR  /  ARDUINO UNO R3", 25, 50);

  fill(dataLive ? green : amber);
  circle(688, 27, 9);

  fill(white);
  textSize(11);
  text(dataLive ? "SERIAL DATA LIVE" :
       connectionStatus, 702, 28);

  fill(cyan);
  textAlign(RIGHT, CENTER);
  text("LIVE SCAN  //  180 DEG", width - 24, 26);

  fill(muted);
  text("9600 BAUD  /  HC-SR04 + L298N",
       width - 24, 49);

  stroke(greenDim);
  line(0, 71, width, 71);
}

// ---------- RADAR FIELD ----------
void drawRadar(boolean dataLive) {
  noStroke();
  fill(panel);
  rect(18, 88, 740, 605, 12);

  fill(muted);
  textAlign(LEFT, CENTER);
  textFont(boldFont);
  textSize(12);
  text("01  /  SCANNING FIELD", 38, 111);

  textFont(regularFont);
  textSize(10);
  text("RANGE  " + int(MAX_RANGE_CM) + " CM",
       38, 132);

  // Range arcs
  noFill();
  strokeWeight(1);

  for (int i = 1; i <= 5; i++) {
    float r = radarR * i / 5.0;

    stroke(20, 100, 76, 180);
    arc(
      radarX - r, radarY - r,
      2 * r, 2 * r,
      PI, TWO_PI
    );

    fill(muted);
    noStroke();
    textAlign(CENTER, CENTER);
    textSize(10);
    text(
      int(MAX_RANGE_CM * i / 5.0) + " cm",
      radarX - r + 22, radarY - 15
    );
    noFill();
  }

  // 0 degree = left; 90 degree = straight up;
  // 180 degree = right.
  for (int a = 0; a <= 180; a += 30) {
    float rad = radians(a);

    float x = radarX - cos(rad) * radarR;
    float y = radarY - sin(rad) * radarR;

    stroke(20, 100, 76, 180);
    line(radarX, radarY, x, y);

    fill(muted);
    noStroke();
    textAlign(CENTER, CENTER);
    textSize(11);
    text(a + "°", x, y - 14);
  }

  // Draw stored obstacle returns.
  // C clears all stored points.
  for (int a = 0; a <= 180; a++) {
    if (!storedValid[a]) continue;

    float r = map(
      storedDistance[a],
      0, MAX_RANGE_CM, 0, radarR
    );

    r = constrain(r, 0, radarR);

    float rad = radians(a);
    float x = radarX - cos(rad) * r;
    float y = radarY - sin(rad) * r;

    boolean closeObject =
      storedDistance[a] <= OBSTACLE_LIMIT_CM;

    noStroke();
    fill(closeObject ? red : cyan);
    circle(x, y, closeObject ? 9 : 6);

    if (closeObject) {
      noFill();
      stroke(red, 130);
      circle(x, y, 16);
    }
  }

  // Current scan beam
  float beamAngle = radians(currentAngle);

  float beamX = radarX - cos(beamAngle) * radarR;
  float beamY = radarY - sin(beamAngle) * radarR;

  stroke(35, 255, 155, 40);
  strokeWeight(14);
  line(radarX, radarY, beamX, beamY);

  stroke(green, 100);
  strokeWeight(6);
  line(radarX, radarY, beamX, beamY);

  stroke(green);
  strokeWeight(2);
  line(radarX, radarY, beamX, beamY);

  noStroke();
  fill(green);
  circle(radarX, radarY, 11);

  fill(muted);
  textAlign(CENTER, CENTER);
  textSize(10);
  text("SENSOR", radarX, radarY + 20);

  // Live values
  fill(white);
  textAlign(LEFT, CENTER);
  textFont(boldFont);
  textSize(13);
  text("ANGLE  " + nf(currentAngle, 0, 1) + "°",
       38, 164);

  if (dataLive && validDistance) {
    fill(currentDistance <= OBSTACLE_LIMIT_CM ?
         red : green);

    text("LIVE RETURN  " + nf(currentDistance, 0, 1) +
         " CM", 38, 187);
  } else {
    fill(amber);
    text("LIVE RETURN  NO VALID ECHO", 38, 187);
  }

  // Alert bar
  boolean alert = dataLive &&
    validDistance &&
    currentDistance <= OBSTACLE_LIMIT_CM;

  noStroke();
  fill(alert ? color(78, 18, 31) : color(7, 43, 32));
  rect(36, 653, 704, 25, 5);

  fill(alert ? red : green);
  textFont(boldFont);
  textSize(11);
  textAlign(LEFT, CENTER);

  if (!dataLive) {
    text("WAITING FOR ARDUINO DATA", 48, 666);
  } else if (alert) {
    text("! OBSTACLE DETECTED WITHIN WARNING RANGE", 48, 666);
  } else {
    text("NO CLOSE OBSTACLE IN CURRENT RETURN", 48, 666);
  }
}

// ---------- RIGHT TELEMETRY PANEL ----------
void drawTelemetry(boolean dataLive) {
  int x = 777;
  int w = 355;

  noStroke();
  fill(panel);
  rect(x, 88, w, 605, 12);

  fill(muted);
  textFont(boldFont);
  textSize(12);
  textAlign(LEFT, CENTER);
  text("02  /  SYSTEM TELEMETRY", x + 18, 111);

  boolean alert = dataLive &&
    validDistance &&
    currentDistance <= OBSTACLE_LIMIT_CM;

  // Alert card
  fill(alert ? color(76, 18, 31) : color(5, 48, 35));
  rect(x + 16, 132, w - 32, 106, 9);

  fill(alert ? red : green);
  textFont(boldFont);
  textSize(11);
  text(alert ? "OBSTACLE WARNING" : "PATH STATUS",
       x + 30, 154);

  fill(white);
  textSize(23);

  if (!dataLive) {
    text("NO DATA", x + 30, 183);
  } else if (alert) {
    text("OBJECT NEARBY", x + 30, 183);
  } else {
    text("CLEAR", x + 30, 183);
  }

  fill(muted);
  textFont(regularFont);
  textSize(10);
  text("Warning threshold: " +
       int(OBSTACLE_LIMIT_CM) + " cm",
       x + 30, 216);

  // Angle card
  drawMetric(
    x + 16, 253, 153, 92,
    "SCAN ANGLE",
    nf(currentAngle, 0, 1) + "°",
    cyan
  );

  String distText = (dataLive && validDistance) ?
    nf(currentDistance, 0, 1) + " cm" : "--";

  drawMetric(
    x + 184, 253, 153, 92,
    "DISTANCE",
    distText,
    alert ? red : green
  );

  // Motor state card
  fill(panelDark);
  rect(x + 16, 359, w - 32, 77, 8);

  fill(muted);
  textSize(10);
  text("PHYSICAL SWITCH  /  ARDUINO D4",
       x + 29, 379);

  boolean motorOn = motorState.equals("ON");

  fill(dataLive && motorOn ? green : amber);
  circle(x + 34, 408, 9);

  fill(white);
  textFont(boldFont);
  textSize(16);

  if (!dataLive) {
    text("WAITING FOR DATA", x + 49, 408);
  } else {
    text(motorState, x + 49, 408);
  }

  // Session data
  fill(muted);
  textFont(boldFont);
  textSize(11);
  text("03  /  SESSION STATISTICS", x + 18, 462);

  drawStat(x + 20, 489, "Valid readings",
           str(validReadings));

  drawStat(x + 20, 517, "Close-range readings",
           str(closeReadings));

  drawStat(x + 20, 545, "Sweep estimate",
           str(int(1000.0 / SWEEP_TIME_MS)) + " sweeps/s max*");

  fill(muted);
  textFont(regularFont);
  textSize(9);
  text("*Approximate theoretical rate, not measured speed.",
       x + 20, 566);

  // Legend
  fill(muted);
  textFont(boldFont);
  textSize(11);
  text("04  /  RADAR LEGEND", x + 18, 599);

  fill(cyan);
  circle(x + 27, 624, 7);
  fill(white);
  textFont(regularFont);
  textSize(10);
  text("Return", x + 40, 624);

  fill(red);
  circle(x + 146, 624, 7);
  fill(white);
  text("Close obstacle", x + 159, 624);

  fill(green);
  circle(x + 27, 651, 7);
  fill(white);
  text("Scan beam", x + 40, 651);

  fill(amber);
  circle(x + 146, 651, 7);
  fill(white);
  text("No echo / waiting", x + 159, 651);

  fill(muted);
  textSize(9);
  text("Press C to clear stored returns", x + 18, 678);
}

void drawMetric(
  int x, int y, int w, int h,
  String label, String value, int valueColor
) {
  noStroke();
  fill(panelDark);
  rect(x, y, w, h, 8);

  fill(muted);
  textFont(regularFont);
  textSize(10);
  textAlign(LEFT, CENTER);
  text(label, x + 12, y + 22);

  fill(valueColor);
  textFont(boldFont);
  textSize(19);
  text(value, x + 12, y + 56);
}

void drawStat(int x, int y, String label, String value) {
  fill(muted);
  textFont(regularFont);
  textSize(10);
  textAlign(LEFT, CENTER);
  text(label, x, y);

  fill(white);
  textAlign(RIGHT, CENTER);
  text(value, 1114, y);
}

// ---------- FOOTER ----------
void drawFooter(boolean dataLive) {
  stroke(greenDim);
  line(18, 705, width - 18, 705);

  fill(muted);
  textFont(regularFont);
  textSize(9);
  textAlign(LEFT, CENTER);
  text("ORBIT // HC-SR04 ECHO RADAR", 24, 718);

  textAlign(RIGHT, CENTER);
  text(dataLive ? "SERIAL: LIVE" : "SERIAL: WAITING",
       width - 24, 718);
}

// ---------- SERIAL READER ----------
void serialEvent(Serial p) {
  String line = p.readStringUntil('\n');

  if (line == null) return;

  line = trim(line);

  // Expected: angle,distance_cm,motor_state
  String[] fields = split(line, ',');

  if (fields.length < 3) {
    println("Ignored incomplete line: " + line);
    return;
  }

  try {
    float a = Float.parseFloat(trim(fields[0]));
    float d = Float.parseFloat(trim(fields[1]));
    String state = trim(fields[2]).toUpperCase();

    if (Float.isNaN(a) || Float.isInfinite(a)) return;
    if (Float.isNaN(d) || Float.isInfinite(d)) return;

    currentAngle = constrain(a, 0, 180);
    currentDistance = d;
    motorState = state;

    validDistance = d >= 2 && d <= 350;

    int index = constrain(round(currentAngle), 0, 180);

    // Replace this angle's most recent return.
    // A no-echo/out-of-range reading clears the old marker
    // at that angle instead of leaving it forever.
    storedValid[index] =
      validDistance && d <= MAX_RANGE_CM;

    if (storedValid[index]) {
      storedDistance[index] = d;
      validReadings++;

      if (d <= OBSTACLE_LIMIT_CM) {
        closeReadings++;
      }
    }

    lastDataMillis = millis();
    connectionStatus = "SERIAL DATA LIVE";

  } catch (Exception e) {
    println("Ignored invalid data line: " + line);
  }
}

// ---------- KEYBOARD ----------
void keyPressed() {
  if (key == 'c' || key == 'C') {
    for (int a = 0; a <= 180; a++) {
      storedDistance[a] = -1;
      storedValid[a] = false;
    }

    validReadings = 0;
    closeReadings = 0;

    println("Radar history cleared.");
  }
}
