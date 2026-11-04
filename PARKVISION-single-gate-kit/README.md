# PARKVISION — Single Shared Entrance Gate

This revision uses **one common entrance barrier** for all three parking bays. The bays are selected and reserved through a public customer webpage. The MacBook runs the Flask application, owns the Arduino USB serial connection, stores the database, and shows the QR code when the entrance sensor detects a waiting vehicle.

## 1. How the system works

```text
                 CUSTOMER'S PHONE
              scans the entrance QR code
                          |
                          v
             Tailscale Funnel HTTPS URL
                          |
                          v
       Flask customer page on the MacBook
          shows A1 / A2 / A3 availability
                          |
        customer selects a free bay + submits
                          |
                          v
                Local SQLite database
                          |
                 Reservation succeeds
                          |
                    Flask sends OPEN
                          |
                          v
MacBook USB serial <----> Arduino UNO R3
                             |       |
                         HC-SR04   SG90 servo
                         D7 / D6    signal D9
                             |       |
                    detects vehicle   shared gate
                       within 8 cm      opens
```

**Sequence:**

1. The vehicle/model approaches the single entrance and stops at the sensor marker, approximately 6–8 cm from the HC-SR04.
2. Arduino needs three consecutive readings at or below 8 cm before it reports `PRESENCE:ON`.
3. Flask receives that event over USB serial. The administrator station page on the MacBook reveals the customer QR code.
4. The customer scans the QR code. Their phone opens the public `/customer` page through Tailscale Funnel and shows the three bays.
5. The customer enters a name and vehicle registration and selects an available bay.
6. Flask checks that the sensor is still detecting a vehicle, checks that the bay is free, records the reservation in SQLite, and sends `OPEN` to Arduino.
7. Arduino opens the SG90 barrier only if its own sensor state still says a vehicle is present.
8. When the object leaves the sensor zone, the gate closes after the clear readings and hold time.
9. An administrator uses the local station page to release a bay after the model vehicle has left it.

The QR is an **entrance QR**, not a separate QR for each bay. It always points to the customer page; Flask only reveals it on the MacBook station display when a vehicle is detected.

## 2. Physical structure

Use one simple entrance lane and one SG90 barrier. Put the three parking bays behind the entrance. The sensor should look across the waiting point at the front face of the model vehicle, not toward the floor or at an angle.

```text
                     PARKING AREA
          +-----------+-----------+-----------+
          |   BAY A1  |   BAY A2  |   BAY A3  |
          |           |           |           |
          +-----------+-----------+-----------+
                       ^
                       | vehicle enters
                 [ ONE SHARED GATE ]  <-- SG90 barrier arm
                       |
                [ HC-SR04 SENSOR ] ---> faces the waiting vehicle
                       |
              vehicle stops 6–8 cm away
                       |
                    APPROACH

        MacBook: Flask server + SQLite + QR display
                       |
                    USB cable
                       |
                   Arduino UNO
```

The gate arm is only a lightweight model barrier. Keep it clear of fingers and do not use this prototype on a real driveway or with real vehicles. If the SG90 turns the wrong way, adjust `GATE_OPEN_ANGLE` and `GATE_CLOSED_ANGLE` in the firmware after testing the servo without its arm attached.

## 3. Wiring — the main connections stay the same

Power everything off before changing wires.

### HC-SR04 ultrasonic sensor

| HC-SR04 pin | Connect to | Purpose |
|---|---|---|
| VCC | Arduino 5V | Sensor power |
| GND | Arduino GND | Ground |
| TRIG | Arduino D7 | Trigger |
| ECHO | Arduino D6 | Echo return |

### SG90 servo

| SG90 wire | Connect to | Purpose |
|---|---|---|
| Signal (orange/yellow) | Arduino D9 | Servo control |
| Red | Regulated external 5V positive | Servo power |
| Brown/black | External 5V negative AND Arduino GND | Common ground |

Important servo-power notes:

- Do not power the SG90 from the UNO's 5V pin for this build.
- Use a regulated 5V supply with the correct polarity. Check the adapter label or verify its output before connecting it.
- Connect the external 5V negative to Arduino GND so the servo and Arduino share a reference.
- Do **not** connect the external adapter's +5V wire to the Arduino 5V pin while the UNO is powered over USB.
- Keep the barrier arm light and free-moving. If the servo jitters, the UNO resets, or the supply becomes hot, disconnect power and check the supply and mechanical load.

### Arduino to MacBook

Connect the UNO to the MacBook with USB. Flask uses the USB serial connection at **9600 baud**. Close Arduino IDE's Serial Monitor before starting Flask; only one program can own the serial port at a time.

### L298N module — included in firmware, not connected

The current version does not need the L298N or the 12V geared motor. Leave the L298N, motor, and 12V adapters disconnected. In the firmware, `USE_L298N` is deliberately set to `false`.

For reference only, the optional firmware pin assignments are ENA→D5, IN1→D8, IN2→D4. The optional motor routine is present but returns `MOTOR:DISABLED` while `USE_L298N` is false. Do not change that setting or connect the motor supply for the current build.

## 4. Upload the Arduino firmware

1. Open `firmware/PARKVISION_SingleGate.ino` in Arduino IDE.
2. Select **Arduino Uno** and the correct USB port.
3. Upload the sketch.
4. The servo should move to its closed angle (5 degrees) during startup.
5. The active detection threshold is `DETECT_DISTANCE_CM = 8.0` cm. The sensor stops reporting presence only after readings are 12 cm or farther (or no echo) for five samples. This 8/12 cm hysteresis helps reduce flickering near the threshold. To change the opening angle for your barrier, adjust `GATE_OPEN_ANGLE` near the top of the sketch; test the servo without the barrier arm first so it does not hit its mechanical stop.

### Test the sensor before starting Flask

For a quick test only, open Serial Monitor at **9600 baud** with **Newline** selected. Move a flat target slowly toward the sensor. When it stays within 8 cm, expect:

```text
PARKVISION:SINGLE_GATE_READY
DIST:7.5
PRESENCE:ON
```

Move the target away beyond the clear threshold. After several readings, expect `PRESENCE:OFF`.

While the target is still detected, type `OPEN` and press Enter. Expect `GATE:OPEN`. Remove the target and allow the gate to close. Sending `OPEN` when no vehicle is detected should return `ERR:NO_VEHICLE`.

Close Serial Monitor after testing. Flask must be the only serial reader during the full demo.

## 5. Set up the Flask server on macOS

Open Terminal. This assumes you extracted the kit into `~/Downloads/PARKVISION-single-gate-kit`:

```bash
cd ~/Downloads/PARKVISION-single-gate-kit/server
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

Edit the settings:

```bash
nano .env
```

Set these values:

```dotenv
PARKVISION_PUBLIC_URL=
PARKVISION_ADMIN_PASSWORD=choose-a-private-admin-password
FLASK_SECRET_KEY=paste-a-long-random-secret-here
SERIAL_PORT=
SERIAL_BAUD=9600
```

Generate a random Flask session secret in another Terminal tab with:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Copy the result into `FLASK_SECRET_KEY`. Set your own administrator password. The example `CHANGE-...` placeholder is rejected by the app, so you must replace it. Do not put `.env` or the SQLite database on a public GitHub repository.

### Select the Arduino serial port

With the Arduino connected, run:

```bash
ls /dev/cu.*
```

Look for a port similar to `/dev/cu.usbmodem...` or `/dev/cu.usbserial...`. Paste the exact port into the `SERIAL_PORT` line of `.env`, for example:

```dotenv
SERIAL_PORT=/dev/cu.usbserial-110
```

The actual name on your Mac may be different. Leave it blank only when there is exactly one likely USB serial device and automatic detection can identify it.

Start the application:

```bash
python app.py
```

The terminal should print the station address. On the MacBook, open:

- `http://127.0.0.1:5000/login` — administrator login
- After login, the browser opens `http://127.0.0.1:5000/station` — entrance station and QR display
- `http://127.0.0.1:5000/customer` — local customer page for testing

Keep this Terminal window running during the demonstration.

## 6. Enable Tailscale Funnel for customer phones

Tailscale Funnel makes the Flask app reachable through an HTTPS `*.ts.net` address. People scanning the QR do not need to install Tailscale. Funnel exposes the service to the public internet, so use a private admin password and only demonstration data.

1. Make sure Tailscale is connected on the MacBook and Funnel is enabled for your tailnet. Funnel requires MagicDNS, HTTPS certificates, and permission in the tailnet policy.
2. Keep Flask running on local port 5000.
3. Open a second Terminal window and run:

```bash
tailscale funnel --bg 5000
```

4. Approve the setup in the browser if Tailscale asks. The command should show an HTTPS address similar in format to `https://your-mac.your-tailnet.ts.net`. Use the exact address it prints; do not copy the example. The `--bg` option leaves the Funnel configuration running in the background.
5. Put the exact address into `PARKVISION_PUBLIC_URL` in `server/.env`, without a trailing slash. Example format:

```dotenv
PARKVISION_PUBLIC_URL=https://your-mac.your-tailnet.ts.net
```

7. Stop Flask with Ctrl+C and start it again using `python app.py`. Refresh `/station`.
8. Scan the QR shown on the station page with another phone. It should open `https://your-mac.your-tailnet.ts.net/customer`.

For a current Funnel status check:

```bash
tailscale funnel status
```

To disable the public Funnel later:

```bash
tailscale funnel reset
```

If `tailscale funnel 5000` reports that Funnel is not enabled or not permitted, check the Funnel and DNS settings in the Tailscale admin console and the installed macOS Tailscale app variant. Current Tailscale documentation lists the Funnel prerequisites and supported public HTTPS ports; the command maps the local service to an HTTPS Funnel URL.

## 7. Full demo procedure

1. Power the Arduino and sensor. Keep the servo supply correctly connected and share ground as described above.
2. Start Flask on the MacBook. Make sure its serial status says connected.
3. Start/confirm Tailscale Funnel and open the local administrator station at `http://127.0.0.1:5000/station`.
4. Move a model vehicle to the entrance waiting point, about 6–8 cm from the sensor. The status should change to **VEHICLE DETECTED**, and the QR code should appear on the MacBook.
5. Scan the QR code from a phone. Confirm the customer page shows A1, A2, and A3 availability.
6. Select a free bay, enter demo name/registration details, and submit.
7. Flask writes a reservation into `server/instance/parkvision.sqlite3` and sends `OPEN`. The servo should open only if the Arduino still detects the vehicle.
8. Move the model vehicle through the entrance. When it clears the sensor zone, the barrier should close automatically.
9. When you want to make the bay available again for the next demo, use the administrator station and select **Release bay** for that reservation.

## 8. Database

The application creates the SQLite database automatically on first launch:

```text
server/instance/parkvision.sqlite3
```

The schema is also provided in `server/schema.sql`. It stores three bay records and reservation records. There is no separate Supabase project or SQL console required for this revision. The database stays on the MacBook; if you delete it, reservation history and current bay reservations are lost. Back up this file separately, and never upload it if it contains visitor details.

## 9. Important limitations

- **Only the entrance is physically sensed.** No individual bay sensor exists. A1/A2/A3 availability is based on reservations and manual release by the administrator.
- The MacBook must remain on, connected to the internet, running Flask, and connected to the Arduino by USB. Funnel cannot reach the service if the MacBook or Flask is off.
- The QR appears on the MacBook's administrator station page only while the entrance sensor reports `PRESENCE:ON`.
- Reservations are accepted only while the sensor detects a vehicle and the Arduino serial connection is active.
- This is a science-fair demonstration, not a certified parking gate, payment system, or real-world vehicle safety controller.

## 10. Troubleshooting

| Symptom | Check |
|---|---|
| QR does not appear | Check the station page is logged in, Flask is connected to Arduino, the object is within 8 cm, and `PARKVISION_PUBLIC_URL` is set. |
| Sensor never says `PRESENCE:ON` | Recheck TRIG D7, ECHO D6, VCC 5V, GND; aim at a flat target; test around 6–8 cm. |
| Sensor flickers around the threshold | Make sure the sensor and target are steady. Increase `DETECT_DISTANCE_CM` slightly only if the physical mounting needs it. |
| Servo does not move | Check signal D9, external regulated 5V polarity, common ground, servo wiring, and that the barrier arm can move freely. |
| Website says Arduino is offline | Close Serial Monitor, check `SERIAL_PORT` in `.env`, reconnect the USB cable, restart Flask, or press Connect / retry Arduino. |
| Customer can see bays but cannot reserve | Reservation requires `PRESENCE:ON` and a live serial connection. Bring the model vehicle to the sensor waiting point. |
| Customer phone cannot open QR URL | Check `tailscale funnel status`, verify the exact public URL in `.env`, and confirm the MacBook and Flask remain online. |
| Gate does not open after reservation | Check the Arduino still detects presence at the moment the form is submitted, and watch the Flask terminal and station event message. |

---

**Current configuration summary:** UNO R3 + HC-SR04 + SG90 + MacBook Flask server + SQLite + Tailscale Funnel. L298N support is present in firmware but disabled and disconnected.
