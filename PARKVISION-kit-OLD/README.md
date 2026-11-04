# PARKVISION — Smart Parking Management System

This package contains a working **educational prototype** for an Arduino UNO R3 entrance gate, a responsive parking website, and an optional cloud database.

## Package contents

- `firmware/PARKVISION.ino` — Arduino UNO R3 firmware.
- `web/index.html` — responsive booking/admin website. It starts in browser-local demo mode. Add Supabase settings to enable shared cloud bookings.
- `web/supabase-setup.sql` — database tables, availability view, and row-level security policies for Supabase.

## What the prototype actually senses

The single HC-SR04 is an **entrance approach detector**. It does not monitor all three parking bays independently. The website shows three reservable/display bays, but only the entrance detection and SG90 barrier are physically controlled. To sense occupancy of each individual bay, add a separate sensor for each bay in a later version.

The L298N and 12V geared motor are an optional add-on for a lightweight rotating PARKVISION sign/display. The DC geared motor is not used as the main barrier actuator. Do not connect a high-current or unknown motor to the L298N until its electrical rating has been checked.

## Safety and power notes

1. Switch off and unplug every supply before changing any wiring.
2. Arduino UNO is powered from the laptop USB cable.
3. Use a **regulated 5V DC supply** for the SG90: adapter positive to servo red; adapter negative to servo brown/black and Arduino GND; servo orange/yellow signal to D9. Do not connect the external 5V positive to the Arduino 5V pin.
4. The HC-SR04 is powered from Arduino 5V and GND.
5. The 12V 2A adapter powers only the L298N motor supply terminals (`+12V`/`VS` and `GND`). The 12V 1A adapter is unused in this design.
6. Join the negative/ground references: Arduino GND, 5V servo-supply negative, and L298N GND / 12V-supply negative. Use suitably rated wire and secure connections.
7. On a typical HW-095 board, remove the `ENA` jumper and connect ENA to D5. Keep the `5V-EN` regulator jumper installed only if the specific board has that jumper and its regulator is specified for the 12V input. Never feed an external 5V source into the module's 5V terminal while its regulator is enabled. Board variants exist, so check the exact labels on your module.
8. Do not route motor current or servo supply current through a solderless breadboard. Use it for low-current sensor/signal wiring only.
9. The L298N loses some voltage and can get hot. Use short motor demonstration pulses, keep the mechanism light, and never stall the motor. Stop if the driver heats excessively, resets, smells hot, or behaves unexpectedly.
10. Use only a very light cardboard/straw gate arm. Keep fingers clear of the servo linkage. This is a tabletop science-fair model, not a real vehicle barrier or safety-rated access system.

## Wiring map

| Arduino UNO R3 | Connect to |
|---|---|
| D7 | HC-SR04 TRIG |
| D6 | HC-SR04 ECHO |
| D9 | SG90 signal (orange/yellow) |
| D5 | L298N ENA (remove ENA jumper) |
| D8 | L298N IN1 |
| D4 | L298N IN2 |
| 5V | HC-SR04 VCC |
| GND | HC-SR04 GND, servo-supply negative, L298N GND |

| Other connection | Connect to |
|---|---|
| SG90 red | Regulated external 5V positive |
| SG90 brown/black | External 5V negative and Arduino GND |
| L298N OUT1 / OUT2 | Two DC geared-motor terminals |
| L298N +12V/VS | 12V 2A adapter positive |
| L298N GND | 12V 2A adapter negative and Arduino GND |

Do not connect either 12V adapter to Arduino 5V, the servo, or the HC-SR04.

## Build and test order

### 1. Test the Arduino and ultrasonic sensor first

1. Install/open Arduino IDE and select **Arduino UNO**.
2. Open `firmware/PARKVISION.ino` and upload it.
3. Open Serial Monitor at **9600 baud**. The board should print `PARKVISION:READY` and distance readings.
4. Move a flat object in front of the HC-SR04. Confirm the distance changes.
5. Close Serial Monitor before using the browser; only one program can own the serial port at a time.

### 2. Add the servo barrier

1. Power the UNO from USB and the SG90 from the separate regulated 5V supply.
2. Connect the servo ground to Arduino GND.
3. Keep the barrier arm off the servo horn for the first test.
4. Connect the servo signal to D9 and restart the Arduino. The servo should move to the closed position.
5. Fit a light paper/straw arm only after confirming the servo moves freely. Never force the servo by hand.

### 3. Add the L298N and DC geared motor (optional)

1. Confirm the motor's rated voltage and current from its label or seller documentation. The motor must be suitable for the L298N module; do not guess its current rating.
2. With all supplies unplugged, connect the motor to OUT1/OUT2 and the Arduino control pins as shown above.
3. Connect the 12V 2A adapter only to the L298N motor supply input.
4. Check the module's `ENA` and `5V-EN` jumper labels before powering it.
5. Use the website's **Run display motor** control. The firmware automatically stops the motor after about 2.2 seconds. Mount the motor securely and use it only for a small, light display mechanism.
6. Leave the 12V 1A adapter unused. Do not connect two adapters together.

### 4. Run the website in local demo mode

For a simple same-computer demo, open the website on a secure local origin. From the `web` directory, run:

```bash
python3 -m http.server 8000
```

Then open `http://localhost:8000` in desktop Chrome. Select the Arduino from **Connect Arduino (USB)**. The first time, Chrome will ask you to choose the Arduino serial device. Keep this browser tab open at the gate station.

In local demo mode, bookings are stored only in this browser's local storage. They do not sync to other phones or computers. The demo admin area is intentionally not password-protected; it is for a science-fair prototype only.

## Enable shared online bookings (optional cloud mode)

The cloud mode uses GitHub Pages for the website and Supabase for shared booking data and authentication. GitHub is the source-code backup/hosting location; it is not the live reservation database.

1. Create a Supabase project.
2. Open the Supabase SQL Editor and run the complete contents of `web/supabase-setup.sql`.
3. In Supabase project settings, copy the Project URL and the **publishable/anon public key**. Never use the `service_role` or any secret key in website code.
4. Open `web/index.html` and set `SUPABASE_URL` and `SUPABASE_ANON_KEY` near the top of the final script section.
5. Create your administrator account using the website.
6. In the Supabase SQL Editor, run the following statement with your administrator email substituted:

```sql
update auth.users
set raw_app_meta_data = coalesce(raw_app_meta_data, '{}'::jsonb) || '{"role":"admin"}'::jsonb
where email = 'YOUR_ADMIN_EMAIL';
```

7. Sign out and sign back in on the gate-station MacBook. The Admin section should identify the account as a cloud administrator.
8. Host the contents of `web/` on GitHub Pages using HTTPS. For a simple GitHub Pages setup, put `index.html` at the repository root (or in a `docs` folder selected in Pages settings). Keep the firmware and SQL file in the repository as source backups.
9. Open the hosted HTTPS site in desktop Chrome on the MacBook, sign in as administrator, and choose **Connect Arduino (USB)**. Leave that tab running.
10. Visitors can open the same HTTPS site on their phones, create accounts, reserve bays, and press **Check in**. The MacBook gate station receives checked-in bookings and sends the one-time `ARM` command to the Arduino.

Supabase row-level security is enabled by the SQL script. The website's public key is not a secret; database policies are what protect the booking records. Do not publish private visitor details, database exports, passwords, or secret keys in GitHub.

## Browser and network requirements

- The gate station needs a desktop browser that supports Web Serial (this package is designed for desktop Chrome) and a secure origin such as `https://` or `http://localhost`.
- A phone can use the cloud booking website, but it cannot directly access the USB-connected Arduino.
- The gate-station computer must remain on, connected to the Arduino, connected to the internet in cloud mode, and keep the station page open.
- If the MacBook is off or the station page is closed, online reservations may still work, but automatic gate operation will not.

## Gate-control logic

- A visitor's booking starts as `reserved`.
- Pressing **Check in** changes it to `checked_in`.
- The gate station sends `ARM` only for a checked-in booking.
- The Arduino requires three consecutive sensor readings at or below 35 cm before opening the SG90 barrier.
- The gate remains open while the sensor sees a nearby object, then closes after a clear interval.
- Each check-in authorises one gate cycle. An unused authorisation expires after 90 seconds.

The 35 cm threshold, 58 cm clear threshold, servo angles, motor pulse duration, and other settings are constants near the top of the Arduino sketch. Tune the distance values for the physical dimensions of your model. Do not use the prototype to control a full-size gate or real vehicle traffic.
