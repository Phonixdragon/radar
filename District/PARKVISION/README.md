# PARKVISION — complete prototype software pack

**Project title:** *An Integrated IoT Prototype for Parking-Space Reservation, Physical Access Control and Live Occupancy Monitoring.*

This pack is designed for a one-bay physical model and a software dashboard. **P-01 is the only physical bay. P-02 and P-03 are software-only demo bays.** Do not describe the extra bays as sensor-monitored.

## What is included

- Flask server on the MacBook, SQLite database, visitor booking and coded check-in.
- Dark/light responsive dashboard with live status polling.
- Admin-only operator console, gate test controls, demo occupancy controls, and CSV exports.
- Arduino UNO firmware for HC-SR04 distance sensing and servo-controlled model barrier.
- Optional manual CSV archiving to the existing private Copyparty server.
- Demo mode, so the complete website can be tested before the servo and breadboard arrive.

## 1. Start the software today — no Arduino required

On the MacBook, unzip the folder and open Terminal. Run:

```bash
cd ~/Downloads/PARKVISION
./run.sh
```

If the folder is somewhere else, drag the PARKVISION folder into Terminal after typing `cd `.

The first launch creates a Python virtual environment and installs Flask and pyserial. It asks you to set an admin password. Use at least 12 characters. Keep it private. Then open:

`http://127.0.0.1:5000`

The default mode is **demo**. You can test booking, check-in, the operator console, and CSV downloads without the Arduino connected. In the Operator console, use **Simulate car entered** and **Simulate bay clear** to test the occupancy card. The demo gate closes 10 seconds after the simulated car enters, or after a 30-second safety timeout.

Keep the Terminal process running while using the dashboard. Press Ctrl+C to stop it.

### Demo test sequence

1. Book P-01 with a name. Save the booking ID and six-digit access code.
2. Submit those values in Arrival Check-in. The dashboard should show the gate open.
3. Open Operator login, enter the admin password, then select **Simulate car entered**.
4. Watch the physical bay change to OCCUPIED and the model gate change to CLOSED after the demo delay.
5. Select **Simulate bay clear**. The bay should return to CLEAR.
6. Download each CSV from the operator console.
7. Repeat once using P-02 or P-03. The site explicitly reports that these are virtual bays and do not control a servo.

## 2. Configure the physical Arduino later

### Pin assignment

| Part | Connection |
|---|---|
| HC-SR04 VCC | Arduino 5V |
| HC-SR04 GND | Arduino GND |
| HC-SR04 TRIG | D10 |
| HC-SR04 ECHO | D11 |
| Servo signal (yellow/orange) | D9 |
| Servo GND (brown/black) | External regulated 5V supply GND |
| Servo +V (usually red) | External regulated supply positive, matching servo label |
| Common ground | External supply GND connected to Arduino GND |

**Power warning:** Do not power an unknown servo from the Arduino 5V pin or Mac USB. Do not connect the 12V adapter directly to the servo. Check the exact servo label/specification. Use a suitable regulated supply (many small hobby servos use a 5V supply, but follow the model's rating). If using a buck converter, an adult should help and its output must be checked with a multimeter before the servo is connected. Never connect the external servo positive rail to the UNO 5V pin while the UNO is USB-powered. Only the grounds are common. Keep the mechanism lightweight and ensure it cannot pinch or hit anyone.

Disconnect the old ORBIT motor and L298N from this PARKVISION build. Keep ORBIT's old wiring and sketch separately. PARKVISION uses a servo, not the old DC motor driver.

### Upload the sketch

1. Open `firmware/PARKVISION_Arduino.ino` in Arduino IDE.
2. Select **Arduino Uno** and the correct USB port.
3. Confirm wiring and the servo's power supply before connecting power.
4. Upload. The Serial Monitor should show `PARKVISION,READY` and `GATE,CLOSED` at 9600 baud. Close Serial Monitor before starting the Flask hardware server.
5. Start with the barrier arm disconnected or unobstructed. Adjust the two servo angles gradually so the mechanism moves freely and does not force the servo against a hard stop.
6. Test the empty bay and toy car repeatedly. The example threshold `18.0 cm` is only a starting placeholder. Set `OCCUPIED_THRESHOLD_CM` between your measured empty-bay and car-present readings. Keep `CLEAR_THRESHOLD_CM` a little larger to prevent rapid switching. Do not use the sample value without measuring your model.

### Find the Mac serial port

With the UNO connected, run:

```bash
ls /dev/cu.*
```

Common names include `/dev/cu.usbmodem...` or `/dev/cu.usbserial...`. Use the port that appears when the board is connected. Do not copy an old port name if it is not present.

Stop the demo server with Ctrl+C. Then start hardware mode (replace the example port):

```bash
cd ~/Downloads/PARKVISION
PARKVISION_MODE=hardware PARKVISION_SERIAL_PORT=/dev/cu.usbmodem1101 ./run.sh
```

The app uses 9600 baud. The Arduino is the only component that communicates with the servo; the browser never connects to the serial port. In hardware mode, if the controller is not connected, the site reports it as offline and refuses check-in for physical bay P-01.

## 3. Gate and occupancy behaviour

- A visitor reserves a bay. The reservation does not open the gate.
- The visitor enters the booking ID and one-time access code at check-in.
- A valid P-01 check-in asks the backend to send `OPEN_GATE` to the Arduino.
- The Arduino reads the overhead sensor and confirms occupancy across several readings.
- After confirmed occupancy, the Arduino waits 10 seconds and closes the model gate. A 30-second failsafe closes it if no car is detected.
- The bay remains shown as occupied until the sensor reports clear.
- A P-02 or P-03 check-in is simulation-only and never commands the servo.

For the physical layout, put the barrier at the entrance edge so it closes behind the toy car after the car has fully entered the bay. The arm must not swing into the car. This is a tabletop demonstration only, not a real parking barrier.

## 4. Optional public link with Tailscale Funnel

First get the local site working. Public sharing is optional and should be attempted only after changing the admin password and testing the app. Funnel makes the local web service reachable from the public internet, so treat the visitor site as publicly accessible.

With the Flask app running in Terminal, open a second Terminal window and run:

```bash
tailscale funnel --bg 5000
```

Then inspect the public URL with:

```bash
tailscale funnel status
```

Share only the visitor website URL / QR code. Keep the admin password private. The MacBook must remain powered on, connected to the internet, and running the Flask app for the public site to work. To stop sharing, use:

```bash
tailscale funnel 5000 off
```

Funnel setup may require enabling HTTPS/MagicDNS and approving Funnel for your tailnet. Some macOS Tailscale app variants have different port-sharing limitations; follow the Tailscale prompts if the command says Funnel is not enabled. Official docs: https://tailscale.com/docs/features/tailscale-funnel and https://tailscale.com/docs/reference/tailscale-cli/funnel

**Important:** this is a school prototype, not a production reservation service. Do not collect phone numbers, addresses, payment data, or other personal information. The six-digit check-in code is a demo credential. Do not use this for real parking, real gate control, or unattended public access.

## 5. Optional archive to your existing Copyparty CloudVault

Keep Copyparty running on the Android phone as it is now. Do not replace its current config or change its existing users. Create a writable folder named `PARKVISION` in Copyparty and ensure the account used below has permission to upload into it.

Run this from the PARKVISION folder on the Mac. Use the Android phone's **private Tailscale address** and Copyparty's configured port (commonly 3923, but use the port in your config):

```bash
export COPYPARTY_URL='http://100.x.y.z:3923/PARKVISION/'
export COPYPARTY_PASSWORD='your-copyparty-upload-password'
# Only if usernames are enabled in your Copyparty configuration:
export COPYPARTY_USERNAME='your-upload-user'
python3 archive_to_copyparty.py
```

The script sends three timestamped CSV files (bookings, sensor readings, events) to the configured folder using Copyparty's HTTP upload interface. Credentials remain in the Mac Terminal environment; they are not sent to the browser or included in the website source. Do not put a Copyparty password in `app.js`, HTML, or a public webpage.

Copyparty's documented upload methods include HTTP PUT with a `PW` header. Documentation/client examples: https://github.com/9001/copyparty

If your phone is not reachable over Tailscale, skip archiving during the live demonstration. CSV export still works locally from the Operator console.

## 6. Troubleshooting

- **`python3: command not found`:** install Python 3 for macOS, reopen Terminal, and rerun `./run.sh`.
- **`Address already in use`:** close the previous PARKVISION server or stop it with Ctrl+C before starting another.
- **Dashboard says server connection lost:** check the Terminal window for a Python traceback; reload `http://127.0.0.1:5000`.
- **Admin login unavailable:** make sure you entered a password of at least 12 characters when starting the server. Do not open Funnel before setting it.
- **Hardware mode says offline:** close Arduino Serial Monitor, confirm the serial port with `ls /dev/cu.*`, and restart using the correct port.
- **Distance readings are missing:** check common ground, TRIG/ECHO pins, and that the HC-SR04 is not aimed at an angled surface.
- **Occupancy flickers:** remeasure the empty and occupied distances; increase the gap between the two threshold values; keep the sensor fixed directly above the bay.
- **Servo jitters or UNO resets:** stop the system and check the servo's supply rating/current capability and common ground. Do not move the servo power rail to the UNO 5V pin.

## 7. Suggested work order for the remaining days

**Today:** run the software in demo mode, test booking/check-in/admin/CSV, assemble the bay frame, choose a fixed overhead sensor mount, and mark the entry direction and servo barrier position.

**When the sensor/breadboard are ready:** verify HC-SR04 distances with the servo still disconnected. Write down at least 10 empty-bay readings and 10 car-present readings. Select the threshold from those measurements.

**When the servo arrives:** identify its exact model and rated voltage first. Confirm the regulated supply and common ground. Test the servo unloaded, then attach the lightweight barrier arm and adjust angles.

**Final integration:** switch to hardware mode, verify serial data, reserve P-01, check in, move the toy car fully inside, observe occupancy confirmation, gate closing and CSV records. Keep a local demo fallback ready in case public internet or Tailscale is unavailable.

## 8. Honest project limitations for your presentation

This prototype demonstrates a reservation workflow, a single-bay occupancy sensor, a model access barrier, a browser dashboard and structured logging. It does not control or monitor multiple real parking bays, guarantee that a booking corresponds to a real vehicle, or prove reduced traffic or emissions. A real installation would need a separate sensor/controller per bay, safety-rated barrier hardware, stronger identity and abuse prevention, weather protection, network reliability and extensive testing.
