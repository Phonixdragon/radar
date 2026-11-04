from __future__ import annotations

import hmac
import io
import os
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timezone
from contextlib import closing
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, session, url_for, abort, send_file
from werkzeug.middleware.proxy_fix import ProxyFix

try:
    import serial
    from serial.tools import list_ports
except ImportError:  # The web app can still start, but the Arduino will be unavailable.
    serial = None
    list_ports = None

try:
    import qrcode
except ImportError:
    qrcode = None

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
DB_PATH = INSTANCE_DIR / "parkvision.sqlite3"
load_dotenv(BASE_DIR / ".env")

PUBLIC_URL = os.getenv("PARKVISION_PUBLIC_URL", "").strip().rstrip("/")
ADMIN_PASSWORD = os.getenv("PARKVISION_ADMIN_PASSWORD", "")
ADMIN_PASSWORD_CONFIGURED = bool(ADMIN_PASSWORD and not ADMIN_PASSWORD.startswith("CHANGE-"))
SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "")
if not SECRET_KEY or SECRET_KEY.startswith("CHANGE-"):
    SECRET_KEY = secrets.token_urlsafe(32)
SERIAL_PORT_SETTING = os.getenv("SERIAL_PORT", "").strip()
BAUD_RATE = int(os.getenv("SERIAL_BAUD", "9600"))

app = Flask(__name__)
app.secret_key = SECRET_KEY or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    # Funnel serves HTTPS publicly, while the Mac's local station uses localhost HTTP.
    SESSION_COOKIE_SECURE=False,
    MAX_CONTENT_LENGTH=16 * 1024,
)
# Funnel terminates TLS before proxying to the local Flask service.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

state_lock = threading.RLock()
station_state: dict[str, Any] = {
    "serial_connected": False,
    "serial_port": None,
    "sensor_present": False,
    "distance_cm": None,
    "gate": "UNKNOWN",
    "last_event": "Waiting for Arduino",
    "last_update": None,
}


class ArduinoSerial:
    """One serial owner for the Flask app; the browser never opens the USB port."""

    def __init__(self) -> None:
        self.connection = None
        self.lock = threading.Lock()
        self.reader_thread: threading.Thread | None = None

    def candidate_ports(self) -> list[str]:
        if list_ports is None:
            return []
        ports = list(list_ports.comports())
        if SERIAL_PORT_SETTING and SERIAL_PORT_SETTING.lower() != "auto":
            return [SERIAL_PORT_SETTING]
        preferred = []
        for item in ports:
            text = " ".join(str(x or "") for x in (item.device, item.description, item.manufacturer)).lower()
            if any(tag in text for tag in ("usb", "wch", "ch340", "arduino", "serial")):
                preferred.append(item.device)
        if len(preferred) == 1:
            return preferred
        if len(ports) == 1:
            return [ports[0].device]
        return []

    def connect(self) -> tuple[bool, str]:
        if serial is None:
            return False, "pyserial is not installed. Run: python -m pip install -r requirements.txt"
        with self.lock:
            if self.connection and self.connection.is_open:
                return True, f"Already connected: {self.connection.port}"
            candidates = self.candidate_ports()
            if not candidates:
                found = [] if list_ports is None else [p.device for p in list_ports.comports()]
                return False, "Could not choose one Arduino serial port. Set SERIAL_PORT in server/.env. Detected: " + (", ".join(found) or "none")
            port = candidates[0]
            try:
                self.connection = serial.Serial(port, BAUD_RATE, timeout=0.35, write_timeout=1)
                # UNO boards commonly reset when a serial connection is opened.
                time.sleep(2.0)
                self.reader_thread = threading.Thread(target=self._reader, daemon=True, name="parkvision-serial")
                self.reader_thread.start()
                with state_lock:
                    station_state["serial_connected"] = True
                    station_state["serial_port"] = port
                    station_state["last_event"] = f"Connected to {port}"
                return True, f"Connected to {port} at {BAUD_RATE} baud"
            except Exception as exc:
                self.connection = None
                with state_lock:
                    station_state["serial_connected"] = False
                    station_state["serial_port"] = None
                    station_state["last_event"] = f"Serial connection failed: {exc}"
                return False, f"Could not open {port}: {exc}"

    def _reader(self) -> None:
        while True:
            conn = self.connection
            if conn is None or not conn.is_open:
                time.sleep(0.3)
                continue
            try:
                raw = conn.readline()
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="replace").strip()
                if line:
                    self._handle_line(line)
            except Exception as exc:
                with state_lock:
                    station_state["serial_connected"] = False
                    station_state["last_event"] = f"Serial reader stopped: {exc}"
                try:
                    conn.close()
                except Exception:
                    pass
                return

    @staticmethod
    def _handle_line(line: str) -> None:
        with state_lock:
            station_state["last_event"] = line
            station_state["last_update"] = datetime.now(timezone.utc).isoformat()
            if line == "PRESENCE:ON":
                station_state["sensor_present"] = True
            elif line == "PRESENCE:OFF":
                station_state["sensor_present"] = False
            elif line == "GATE:OPEN":
                station_state["gate"] = "OPEN"
            elif line == "GATE:CLOSED":
                station_state["gate"] = "CLOSED"
            elif line == "GATE:HELD":
                station_state["gate"] = "HELD"
            elif line.startswith("DIST:"):
                value = line.partition(":")[2]
                try:
                    station_state["distance_cm"] = float(value) if value != "OUT" else None
                except ValueError:
                    station_state["distance_cm"] = None

    def send(self, command: str) -> tuple[bool, str]:
        if command not in {"OPEN", "CLOSE", "ARM", "DISARM", "MOTOR_PULSE", "MOTOR_STOP"}:
            return False, "Command not allowed"
        with self.lock:
            if self.connection is None or not self.connection.is_open:
                return False, "Arduino is not connected"
            try:
                self.connection.write((command + "\n").encode("ascii"))
                self.connection.flush()
                return True, f"Sent {command}"
            except Exception as exc:
                return False, f"Serial write failed: {exc}"


arduino = ArduinoSerial()


def db_connect() -> sqlite3.Connection:
    INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=8, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def initialize_database() -> None:
    with closing(db_connect()) as conn:
        schema = (BASE_DIR / "schema.sql").read_text(encoding="utf-8")
        conn.executescript(schema)
        for bay_id in ("A1", "A2", "A3"):
            conn.execute(
                "INSERT OR IGNORE INTO bays(id, label, status) VALUES (?, ?, 'available')",
                (bay_id, f"Parking Bay {bay_id}"),
            )


def admin_required() -> bool:
    return session.get("is_admin") is True


def current_sensor_present() -> bool:
    with state_lock:
        return bool(station_state["sensor_present"])


def public_bays() -> list[dict[str, str]]:
    with closing(db_connect()) as conn:
        rows = conn.execute("SELECT id, label, status FROM bays ORDER BY id").fetchall()
        return [dict(row) for row in rows]


@app.get("/")
@app.get("/customer")
def customer_page():
    return render_template("customer.html")


@app.get("/login")
def login_page():
    if admin_required():
        return redirect(url_for("station_page"))
    return render_template("login.html", error=None)


@app.post("/login")
def login_submit():
    password = request.form.get("password", "")
    if not ADMIN_PASSWORD_CONFIGURED:
        return render_template("login.html", error="Set a private PARKVISION_ADMIN_PASSWORD in server/.env first. The example placeholder is not accepted."), 503
    if hmac.compare_digest(password, ADMIN_PASSWORD):
        session.clear()
        session["is_admin"] = True
        return redirect(url_for("station_page"))
    return render_template("login.html", error="Incorrect password. Try again."), 401


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login_page"))


@app.get("/station")
def station_page():
    if not admin_required():
        return redirect(url_for("login_page"))
    return render_template("station.html", public_url=PUBLIC_URL)


@app.get("/api/public/state")
def api_public_state():
    bays = public_bays()
    return jsonify({
        "bays": bays,
        "available_count": sum(1 for bay in bays if bay["status"] == "available"),
        "presence_required": True,
    })


@app.post("/api/reserve")
def api_reserve():
    payload = request.get_json(silent=True) or {}
    bay_id = str(payload.get("bay_id", "")).strip().upper()
    display_name = str(payload.get("display_name", "")).strip()
    vehicle_number = str(payload.get("vehicle_number", "")).strip().upper()
    if bay_id not in {"A1", "A2", "A3"}:
        return jsonify(error="Choose one of the listed bays."), 400
    if not display_name or len(display_name) > 60:
        return jsonify(error="Enter a name (up to 60 characters)."), 400
    if not vehicle_number or len(vehicle_number) > 20:
        return jsonify(error="Enter a vehicle number (up to 20 characters)."), 400
    if not current_sensor_present():
        return jsonify(error="The entrance sensor has not detected a vehicle. Please move to the marked waiting point."), 409
    with state_lock:
        if not station_state["serial_connected"]:
            return jsonify(error="The entrance controller is offline. Please contact the project operator."), 503

    booking_id = "PV-" + secrets.token_hex(3).upper()
    now = datetime.now(timezone.utc).isoformat()
    conn = db_connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        bay = conn.execute("SELECT status FROM bays WHERE id = ?", (bay_id,)).fetchone()
        if bay is None or bay["status"] != "available":
            conn.rollback()
            return jsonify(error="That bay was just reserved. Refresh and choose another bay."), 409
        conn.execute(
            "INSERT INTO bookings(id, bay_id, display_name, vehicle_number, status, created_at) VALUES (?, ?, ?, ?, 'reserved', ?)",
            (booking_id, bay_id, display_name, vehicle_number, now),
        )
        conn.execute(
            "UPDATE bays SET status='reserved', current_booking_id=? WHERE id=? AND status='available'",
            (booking_id, bay_id),
        )
        # OPEN is accepted by the Arduino only while its 8 cm presence detector is active.
        sent, message = arduino.send("OPEN")
        if not sent:
            conn.rollback()
            return jsonify(error=message), 503
        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        return jsonify(error=f"Database error: {exc}"), 500
    finally:
        conn.close()
    return jsonify(
        ok=True,
        booking_id=booking_id,
        bay_id=bay_id,
        message=f"Bay {bay_id} reserved. The entrance gate has been told to open.",
    ), 201


@app.get("/api/station/state")
def api_station_state():
    if not admin_required():
        abort(401)
    with state_lock:
        snapshot = dict(station_state)
    return jsonify({"station": snapshot, "bays": public_bays(), "public_url": PUBLIC_URL})


@app.get("/api/station/bookings")
def api_station_bookings():
    if not admin_required():
        abort(401)
    with closing(db_connect()) as conn:
        rows = conn.execute(
            "SELECT id, bay_id, display_name, vehicle_number, status, created_at FROM bookings ORDER BY created_at DESC LIMIT 20"
        ).fetchall()
    return jsonify(bookings=[dict(row) for row in rows])


@app.post("/api/station/connect")
def api_station_connect():
    if not admin_required():
        abort(401)
    ok, message = arduino.connect()
    return jsonify(ok=ok, message=message), (200 if ok else 503)


@app.post("/api/station/command")
def api_station_command():
    if not admin_required():
        abort(401)
    payload = request.get_json(silent=True) or {}
    command = str(payload.get("command", ""))
    if command == "OPEN" and not current_sensor_present():
        return jsonify(error="The sensor must detect a vehicle within 8 cm before opening."), 409
    ok, message = arduino.send(command)
    return jsonify(ok=ok, message=message), (200 if ok else 503)


@app.post("/api/station/release")
def api_station_release():
    if not admin_required():
        abort(401)
    payload = request.get_json(silent=True) or {}
    bay_id = str(payload.get("bay_id", "")).strip().upper()
    if bay_id not in {"A1", "A2", "A3"}:
        return jsonify(error="Unknown bay."), 400
    now = datetime.now(timezone.utc).isoformat()
    with closing(db_connect()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT current_booking_id FROM bays WHERE id=?", (bay_id,)).fetchone()
        if not row or not row["current_booking_id"]:
            conn.rollback()
            return jsonify(error="This bay does not have an active reservation."), 409
        conn.execute(
            "UPDATE bookings SET status='completed', completed_at=? WHERE id=? AND status='reserved'",
            (now, row["current_booking_id"]),
        )
        conn.execute("UPDATE bays SET status='available', current_booking_id=NULL WHERE id=?", (bay_id,))
        conn.commit()
    return jsonify(ok=True, message=f"{bay_id} is available again.")


@app.get("/station-qr.png")
def station_qr():
    if not admin_required():
        abort(401)
    if not PUBLIC_URL:
        abort(503, description="Set PARKVISION_PUBLIC_URL in server/.env to your Tailscale Funnel URL.")
    if qrcode is None:
        abort(503, description="Install the qrcode[pil] package from requirements.txt.")
    target = PUBLIC_URL + "/customer"
    image = qrcode.make(target, box_size=10, border=3)
    output = io.BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    return send_file(output, mimetype="image/png", max_age=60)


@app.get("/health")
def health():
    with state_lock:
        connected = bool(station_state["serial_connected"])
    return jsonify(ok=True, serial_connected=connected)


@app.errorhandler(401)
def unauthorized(_error):
    return jsonify(error="Administrator login required."), 401


@app.errorhandler(503)
def unavailable(error):
    return jsonify(error=getattr(error, "description", "Service unavailable.")), 503


initialize_database()

if __name__ == "__main__":
    ok, message = arduino.connect()
    print("PARKVISION:", message)
    print("Station: http://127.0.0.1:5000/station")
    print("Customer: http://127.0.0.1:5000/customer")
    if not ADMIN_PASSWORD_CONFIGURED:
        print("WARNING: set a private PARKVISION_ADMIN_PASSWORD in server/.env before exposing Funnel. The example placeholder is blocked.")
    if not os.getenv("FLASK_SECRET_KEY", "").strip() or os.getenv("FLASK_SECRET_KEY", "").startswith("CHANGE-"):
        print("WARNING: set FLASK_SECRET_KEY in server/.env so administrator sessions survive restarts.")
    if PUBLIC_URL:
        print("Public QR URL:", PUBLIC_URL + "/customer")
    else:
        print("Set PARKVISION_PUBLIC_URL after running Tailscale Funnel to display the entrance QR.")
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True, use_reloader=False)
