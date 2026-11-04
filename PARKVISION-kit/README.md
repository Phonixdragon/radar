# PARKVISION — Smart Parking Management System

This package contains the Arduino UNO R3 entrance controller, a responsive booking/admin website, and a Supabase cloud database setup.

## Important: today's build does NOT need the L298N or 12V geared motor

For the first working version, connect only:
- Arduino UNO R3 (powered by laptop USB)
- HC-SR04 ultrasonic entrance sensor
- SG90 servo barrier (powered from the regulated 5V 1A adapter)
- Breadboard for sensor/signal wiring

Leave the L298N, 12V geared motor, 12V 2A adapter and 12V 1A adapter completely disconnected today. The firmware has `MOTOR_DRIVER_ENABLED = false` by default. The website motor control is also disabled.

## Today's power and wiring plan

### Use your one DC barrel-jack breakout for the 5V adapter

Use the single barrel-jack-to-positive/negative adapter with your **regulated 5V 1A supply** for the SG90. Do not use the 12V adapter for the servo.

1. Plug the 5V adapter into the barrel-jack breakout.
2. Verify the adapter's output voltage and polarity from its label (ideally with a multimeter). Many barrel supplies are centre-positive, but do not assume it.
3. Connect breakout `+` to SG90 red.
4. Connect breakout `-` to SG90 brown/black AND to Arduino GND.
5. Connect SG90 orange/yellow signal to Arduino D9.
6. Do not connect the external 5V positive to Arduino 5V while Arduino is powered from USB.

### Arduino and sensor wiring

| Arduino UNO R3 | Connect to |
|---|---|
| D7 | HC-SR04 TRIG |
| D6 | HC-SR04 ECHO |
| D9 | SG90 signal (orange/yellow) |
| 5V | HC-SR04 VCC |
| GND | HC-SR04 GND and external 5V adapter negative |

| HC-SR04 | Connection |
|---|---|
| VCC | Arduino 5V |
| TRIG | Arduino D7 |
| ECHO | Arduino D6 |
| GND | Arduino GND |

| SG90 | Connection |
|---|---|
| Red | External regulated 5V positive |
| Brown/Black | External 5V negative and Arduino GND |
| Orange/Yellow | Arduino D9 |

**Common ground is required:** Arduino GND and the 5V servo supply negative must connect together. This is the shared reference for the servo signal. Keep the external positive separate from the Arduino 5V pin.

Use the breadboard only for low-current sensor/signal connections. Do not route servo power through a thin breadboard jumper or loose contacts; use secure wire/terminal connections. Keep the barrier arm very light and do not stall the servo.

### Leave these components disconnected today

- L298N HW-095: no wires connected, no power.
- 12V geared DC motor: no wires connected.
- 12V 2A adapter: unplugged.
- 12V 1A adapter: unplugged.

When adding the motor later, obtain a second correctly rated DC barrel-jack-to-screw-terminal breakout (or a suitable pigtail/terminal connector) for the 12V 2A supply. Do not try to share one barrel jack between two adapters. Recheck the motor's rated current before using the L298N.

## Firmware

File: `firmware/PARKVISION.ino`

- HC-SR04: TRIG D7, ECHO D6.
- SG90 signal: D9.
- Gate requires an `ARM` command from the web gate station and three consecutive distance readings within 35 cm.
- Barrier remains open while an object is detected and closes after the sensor zone appears clear.
- One authorisation permits one gate cycle and expires after 90 seconds.
- Optional motor code is retained but disabled by default (`MOTOR_DRIVER_ENABLED = false`). Keep it false until the L298N/motor are wired and tested. If adding the motor later, set it true in the Arduino sketch and enable the corresponding website constant/button only after the motor wiring has been checked.

Upload with Arduino IDE, select **Arduino UNO**, and use 9600 baud. Close Serial Monitor before connecting the browser; only one app can use the serial port at a time.

## Website and local demo mode

From the `web` folder run:

```bash
python3 -m http.server 8000
```

Open `http://localhost:8000` in desktop Chrome. The gate station must stay open on the computer connected to the UNO. Choose **Connect Arduino (USB)** and select the UNO serial port.

Local demo mode stores bookings in that browser's local storage. QR codes in local mode can only be redeemed where that same browser's local booking data exists; local demo mode does not sync phones.

## Shared online bookings, live availability and QR check-in

The online configuration uses GitHub Pages (website hosting/source backup) and Supabase (shared bookings/authentication). GitHub is not the live reservation database.

1. Create a Supabase project.
2. Run all of `web/supabase-setup.sql` in Supabase SQL Editor. It creates the bay status view, row-level security, and QR functions. It also adds the QR columns safely to an earlier version of the PARKVISION table.
3. Copy the Supabase Project URL and the publishable/anon public key into `SUPABASE_URL` and `SUPABASE_ANON_KEY` in `web/index.html`. Never put a `service_role` or secret key in public website code.
4. Create an account in PARKVISION for the administrator. In Supabase SQL Editor, assign its admin role (replace the email):

```sql
update auth.users
set raw_app_meta_data = coalesce(raw_app_meta_data, '{}'::jsonb) || '{"role":"admin"}'::jsonb
where email = 'YOUR_ADMIN_EMAIL';
```

5. Sign out and back in as the admin on the gate-station MacBook.
6. Host the website over HTTPS using GitHub Pages. Open it in desktop Chrome on the MacBook, sign in as admin, and connect the Arduino over USB.
7. Visitors open the same HTTPS website on their phones, create an account, and reserve a bay. They can generate a QR code from **My reservations**.
8. Scan the QR using the gate-station computer or another internet-connected device. A valid, unused code changes the booking to `checked_in`; the MacBook gate station sees the check-in and arms the Arduino. The HC-SR04 must still detect an approaching object before the SG90 opens.

### QR security behaviour

- QR token is randomly generated by a Supabase database function and only its SHA-256 hash is stored.
- QR token expires after two hours.
- A successful scan consumes the token, so it cannot be reused.
- The QR is a bearer check-in pass: show it only at arrival and do not post/share its screenshot.
- The scan device does not need to sign in as the visitor; possession of the high-entropy, unexpired one-time QR is required.
- Direct visitor updates cannot set a booking to `checked_in`; check-in must pass through the QR RPC.

### Live availability behaviour

The dashboard refreshes bay reservation states through the shared Supabase `parking_status` view, listens for database changes where available, and polls as a fallback approximately every five seconds. Everyone using cloud mode sees shared reservation status.

**Sensor limitation:** There is only one HC-SR04, positioned at the entrance. It detects an approaching object; it does not measure whether A1, A2 or A3 is physically occupied. The three bay indicators are live reservation/check-in states, not independent physical occupancy readings. Add one sensor per bay (or another sensing arrangement) in a later hardware version for true per-bay occupancy.

## Hardware safety and demo limitations

- Disconnect supplies before changing wiring.
- Never connect 12V directly to the UNO 5V pin, SG90, or HC-SR04.
- Never connect the 12V 2A and 12V 1A adapters together.
- The 5V adapter must be regulated 5V DC and have correct polarity.
- A single HC-SR04 cannot identify a car; a person or other object may also trigger it.
- Use a lightweight cardboard/straw barrier arm. This is an educational tabletop prototype, not a real-vehicle safety-rated gate.
- The MacBook must remain on, online, connected to the UNO, and keep the gate-station browser tab open for automatic operation from remote phone check-ins.
