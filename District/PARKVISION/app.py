from __future__ import annotations

import csv
from collections import defaultdict, deque
import hashlib
import io
import os
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

from flask import Flask, jsonify, render_template, request, session, Response

BASE = Path(__file__).resolve().parent
DATA_DIR = BASE / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "parkvision.sqlite3"
MODE = os.getenv("PARKVISION_MODE", "demo").strip().lower()
if MODE not in {"demo", "hardware"}:
    MODE = "demo"
SERIAL_PORT = os.getenv("PARKVISION_SERIAL_PORT", "").strip()
ADMIN_PASSWORD = os.getenv("PARKVISION_ADMIN_PASSWORD", "")
SECRET_KEY = os.getenv("PARKVISION_SECRET_KEY", "")

app = Flask(__name__)
app.secret_key = SECRET_KEY or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    MAX_CONTENT_LENGTH=1_000_000,
)

SLOTS = [
    {"id": "P-01", "label": "Bay 01", "kind": "physical", "note": "Live HC-SR04 + servo gate"},
    {"id": "P-02", "label": "Bay 02", "kind": "virtual", "note": "Simulated demonstration slot"},
    {"id": "P-03", "label": "Bay 03", "kind": "virtual", "note": "Simulated demonstration slot"},
]

state_lock = threading.RLock()
state = {
    "mode": MODE,
    "connected": False,
    "serial_error": "",
    "distance_cm": None,
    "occupied": False,
    "gate": "CLOSED",
    "last_seen": None,
    "demo_occupied": False,
    "gate_opened_at": None,
    "last_sensor_log": 0.0,
}
serial_manager = None
rate_lock = threading.Lock()
rate_buckets = defaultdict(deque)


def rate_limited(bucket: str, limit: int, window_seconds: int) -> bool:
    key = (bucket, request.remote_addr or "unknown")
    current = time.monotonic()
    with rate_lock:
        history = rate_buckets[key]
        while history and current - history[0] > window_seconds:
            history.popleft()
        if len(history) >= limit:
            return True
        history.append(current)
        return False


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None = None) -> str:
    return (dt or now_utc()).isoformat(timespec="seconds")


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc, tb):
        try:
            return super().__exit__(exc_type, exc, tb)
        finally:
            self.close()


def db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=10, factory=ClosingConnection)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init_db() -> None:
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS bookings (
            id TEXT PRIMARY KEY,
            slot_id TEXT NOT NULL,
            visitor_name TEXT NOT NULL,
            token_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'RESERVED',
            checked_in_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_bookings_slot_status ON bookings(slot_id, status);
        CREATE TABLE IF NOT EXISTS sensor_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recorded_at TEXT NOT NULL,
            distance_cm REAL,
            occupied INTEGER NOT NULL,
            source TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recorded_at TEXT NOT NULL,
            event_type TEXT NOT NULL,
            details TEXT NOT NULL
        );
        """)


def event(event_type: str, details: str) -> None:
    with db() as con:
        con.execute("INSERT INTO events(recorded_at,event_type,details) VALUES(?,?,?)",
                    (iso(), event_type, details[:500]))


def log_sensor(distance, occupied, source="arduino") -> None:
    with db() as con:
        con.execute("INSERT INTO sensor_logs(recorded_at,distance_cm,occupied,source) VALUES(?,?,?,?)",
                    (iso(), distance, 1 if occupied else 0, source))


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("admin_ok"):
            return jsonify({"ok": False, "error": "Admin login required."}), 401
        return fn(*args, **kwargs)
    return wrapped


def expire_bookings() -> None:
    now = iso()
    with db() as con:
        rows = con.execute("SELECT id,slot_id FROM bookings WHERE status='RESERVED' AND expires_at<=?", (now,)).fetchall()
        con.execute("UPDATE bookings SET status='EXPIRED' WHERE status='RESERVED' AND expires_at<=?", (now,))
    for row in rows:
        event("BOOKING_EXPIRED", f"{row['id']} / {row['slot_id']}")


def active_booking(slot_id: str):
    with db() as con:
        return con.execute(
            "SELECT id,slot_id,visitor_name,created_at,expires_at,status,checked_in_at FROM bookings "
            "WHERE slot_id=? AND status IN ('RESERVED','CHECKED_IN') ORDER BY created_at DESC LIMIT 1",
            (slot_id,),
        ).fetchone()


def set_gate(value: str) -> None:
    with state_lock:
        state["gate"] = value
        state["gate_opened_at"] = time.time() if value == "OPEN" else None
    event("GATE", value)


def handle_serial_line(line: str) -> None:
    line = line.strip()
    if not line:
        return
    parts = line.split(",", 1)
    kind = parts[0].strip().upper()
    payload = parts[1].strip() if len(parts) > 1 else ""
    changed_occ = None
    sensor_log_due = False
    with state_lock:
        state["last_seen"] = iso()
        state["connected"] = True
        if kind in {"DIST", "SENSOR"}:
            try:
                value = float(payload)
                if 0 < value < 500:
                    state["distance_cm"] = round(value, 1)
                    if time.monotonic() - state["last_sensor_log"] >= 1.0:
                        state["last_sensor_log"] = time.monotonic()
                        sensor_log_due = True
            except ValueError:
                pass
        elif kind == "OCCUPANCY" and payload in {"0", "1"}:
            new_value = payload == "1"
            if new_value != state["occupied"]:
                state["occupied"] = new_value
                changed_occ = new_value
        elif kind == "GATE" and payload.upper() in {"OPEN", "CLOSED"}:
            state["gate"] = payload.upper()
            state["gate_opened_at"] = time.time() if payload.upper() == "OPEN" else None
    if sensor_log_due:
        log_sensor(state.get("distance_cm"), state.get("occupied", False), "arduino")
    if changed_occ is not None:
        event("OCCUPANCY", "OCCUPIED" if changed_occ else "CLEAR")
        log_sensor(state.get("distance_cm"), changed_occ, "arduino")
        if not changed_occ:
            with db() as con:
                con.execute("UPDATE bookings SET status='COMPLETED' WHERE slot_id='P-01' AND status='CHECKED_IN'")


class SerialManager:
    def __init__(self, port: str):
        self.port = port
        self.ser = None
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def start(self):
        self.thread.start()

    def send(self, command: str) -> bool:
        with state_lock:
            ser = self.ser
        if not ser:
            return False
        try:
            ser.write((command.strip() + "\n").encode("ascii"))
            return True
        except Exception as exc:
            with state_lock:
                state["serial_error"] = str(exc)
                state["connected"] = False
            return False

    def run(self):
        while not self.stop_event.is_set():
            try:
                import serial
                if not self.port:
                    raise RuntimeError("Set PARKVISION_SERIAL_PORT to the Arduino serial port.")
                with serial.Serial(self.port, 9600, timeout=1) as ser:
                    with state_lock:
                        self.ser = ser
                        state["connected"] = True
                        state["serial_error"] = ""
                    event("SERIAL", f"Connected on {self.port}")
                    while not self.stop_event.is_set():
                        raw = ser.readline()
                        if raw:
                            try:
                                handle_serial_line(raw.decode("utf-8", errors="replace"))
                            except Exception as exc:
                                with state_lock:
                                    state["serial_error"] = str(exc)
                    with state_lock:
                        self.ser = None
                        state["connected"] = False
            except Exception as exc:
                with state_lock:
                    self.ser = None
                    state["connected"] = False
                    state["serial_error"] = str(exc)
                self.stop_event.wait(4)


if MODE == "hardware":
    # Create tables before the serial worker can emit its first event.
    init_db()
    serial_manager = SerialManager(SERIAL_PORT)
    serial_manager.start()


def send_command(command: str) -> bool:
    if MODE == "demo":
        if command == "OPEN_GATE":
            set_gate("OPEN")
        elif command == "CLOSE_GATE":
            set_gate("CLOSED")
        return True
    if serial_manager:
        return serial_manager.send(command)
    return False


def demo_tick() -> None:
    if MODE != "demo":
        return
    with state_lock:
        opened = state["gate_opened_at"]
        occupied = state["demo_occupied"]
        should_close = opened is not None and ((occupied and time.time() - opened >= 10) or time.time() - opened >= 30)
        if should_close:
            state["occupied"] = occupied
    if should_close:
        set_gate("CLOSED")


def build_state():
    expire_bookings()
    demo_tick()
    with state_lock:
        snap = dict(state)
    slot_list = []
    for s in SLOTS:
        booking = active_booking(s["id"])
        occupied = snap["occupied"] if s["id"] == "P-01" else False
        if occupied:
            status = "OCCUPIED"
        elif booking:
            status = "RESERVED" if booking["status"] == "RESERVED" else "CHECKED IN"
        else:
            status = "AVAILABLE"
        slot_list.append({**s, "status": status, "booking": ({
            "id": booking["id"], "visitor_name": booking["visitor_name"],
            "expires_at": booking["expires_at"], "status": booking["status"]
        } if booking else None)})
    with db() as con:
        counts = con.execute("SELECT status,COUNT(*) n FROM bookings GROUP BY status").fetchall()
    return {
        "ok": True,
        "mode": snap["mode"],
        "connected": snap["connected"] if MODE == "hardware" else True,
        "serial_error": snap["serial_error"] if MODE == "hardware" else "",
        "distance_cm": snap["distance_cm"],
        "occupied": snap["occupied"],
        "gate": snap["gate"],
        "last_seen": snap["last_seen"],
        "slots": slot_list,
        "booking_counts": {r["status"]: r["n"] for r in counts},
        "physical_bay_count": 1,
        "total_demo_slots": len(SLOTS),
    }


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/state")
def api_state():
    return jsonify(build_state())


@app.post("/api/book")
def api_book():
    if rate_limited("book", 12, 60):
        return jsonify({"ok": False, "error": "Too many booking attempts. Please wait a minute."}), 429
    data = request.get_json(silent=True) or {}
    slot_id = str(data.get("slot_id", "")).upper().strip()
    name = " ".join(str(data.get("visitor_name", "")).split())[:40]
    try:
        duration = int(data.get("duration_minutes", 15))
    except (TypeError, ValueError):
        duration = 15
    if slot_id not in {s["id"] for s in SLOTS}:
        return jsonify({"ok": False, "error": "Choose a listed parking bay."}), 400
    if len(name) < 2:
        return jsonify({"ok": False, "error": "Enter a name with at least 2 characters."}), 400
    if duration not in {10, 15, 20, 30}:
        return jsonify({"ok": False, "error": "Choose a supported reservation duration."}), 400
    expire_bookings()
    if slot_id == "P-01":
        with state_lock:
            if state["occupied"]:
                return jsonify({"ok": False, "error": "Bay P-01 is currently occupied."}), 409
    con = db()
    try:
        con.execute("BEGIN IMMEDIATE")
        existing = con.execute("SELECT id FROM bookings WHERE slot_id=? AND status IN ('RESERVED','CHECKED_IN') AND expires_at>?",
                               (slot_id, iso())).fetchone()
        if existing:
            con.rollback()
            return jsonify({"ok": False, "error": "That bay has just been reserved. Please choose another."}), 409
        booking_id = "PV-" + secrets.token_hex(4).upper()
        code = str(secrets.randbelow(900000) + 100000)
        created = now_utc()
        expiry = created + timedelta(minutes=duration)
        con.execute("INSERT INTO bookings(id,slot_id,visitor_name,token_hash,created_at,expires_at,status) VALUES(?,?,?,?,?,?, 'RESERVED')",
                    (booking_id, slot_id, name, token_hash(code), iso(created), iso(expiry)))
        con.commit()
    finally:
        con.close()
    event("BOOKING_CREATED", f"{booking_id} / {slot_id} / {name}")
    return jsonify({"ok": True, "booking_id": booking_id, "access_code": code,
                    "slot_id": slot_id, "expires_at": iso(expiry),
                    "note": "Keep the booking ID and access code for check-in. P-02 and P-03 are simulated bays."})


@app.post("/api/checkin")
def api_checkin():
    if rate_limited("checkin", 12, 60):
        return jsonify({"ok": False, "error": "Too many check-in attempts. Please wait a minute."}), 429
    data = request.get_json(silent=True) or {}
    booking_id = str(data.get("booking_id", "")).upper().strip()
    code = str(data.get("access_code", "")).strip()
    if not booking_id or not code:
        return jsonify({"ok": False, "error": "Enter both booking ID and access code."}), 400
    expire_bookings()
    with db() as con:
        booking = con.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
        if not booking or not secrets.compare_digest(booking["token_hash"], token_hash(code)):
            return jsonify({"ok": False, "error": "Booking ID or access code is incorrect."}), 403
        if booking["status"] != "RESERVED" or booking["expires_at"] <= iso():
            return jsonify({"ok": False, "error": "This reservation is no longer active."}), 409
        slot_id = booking["slot_id"]
        with state_lock:
            occupied = state["occupied"] if slot_id == "P-01" else False
        if occupied:
            return jsonify({"ok": False, "error": "The physical bay is already occupied. Ask the project operator."}), 409
        if slot_id == "P-01" and MODE == "hardware" and not state["connected"]:
            return jsonify({"ok": False, "error": "Arduino is not connected. Ask the operator to check the USB connection."}), 503
        con.execute("UPDATE bookings SET status='CHECKED_IN',checked_in_at=? WHERE id=?", (iso(), booking_id))
    if slot_id == "P-01":
        if not send_command("OPEN_GATE"):
            with db() as con:
                con.execute("UPDATE bookings SET status='RESERVED',checked_in_at=NULL WHERE id=?", (booking_id,))
            return jsonify({"ok": False, "error": "Could not send the gate command. Check Arduino connection."}), 503
    event("CHECK_IN", f"{booking_id} / {slot_id}")
    return jsonify({"ok": True, "message": "Check-in confirmed. The physical model gate is opening for P-01." if slot_id == "P-01" else "Virtual demo check-in confirmed. No physical gate is connected to this bay."})


@app.post("/api/admin/login")
def admin_login():
    if rate_limited("admin_login", 5, 60):
        return jsonify({"ok": False, "error": "Too many login attempts. Wait one minute before retrying."}), 429
    data = request.get_json(silent=True) or {}
    supplied = str(data.get("password", ""))
    if not ADMIN_PASSWORD:
        return jsonify({"ok": False, "error": "Set PARKVISION_ADMIN_PASSWORD before using admin features."}), 503
    if not secrets.compare_digest(supplied, ADMIN_PASSWORD):
        time.sleep(0.6)
        return jsonify({"ok": False, "error": "Incorrect admin password."}), 403
    session.clear()
    session["admin_ok"] = True
    session["csrf"] = secrets.token_urlsafe(24)
    return jsonify({"ok": True, "csrf": session["csrf"]})


@app.post("/api/admin/logout")
@admin_required
def admin_logout():
    session.clear()
    return jsonify({"ok": True})


def csrf_ok() -> bool:
    return secrets.compare_digest(str(request.headers.get("X-PV-CSRF", "")), str(session.get("csrf", "")))


@app.get("/api/admin/overview")
@admin_required
def admin_overview():
    with db() as con:
        bookings = con.execute("SELECT id,slot_id,visitor_name,created_at,expires_at,status,checked_in_at FROM bookings ORDER BY created_at DESC LIMIT 30").fetchall()
        events = con.execute("SELECT recorded_at,event_type,details FROM events ORDER BY id DESC LIMIT 30").fetchall()
    return jsonify({"ok": True, "bookings": [dict(r) for r in bookings], "events": [dict(r) for r in events]})


@app.post("/api/admin/gate")
@admin_required
def admin_gate():
    if not csrf_ok():
        return jsonify({"ok": False, "error": "Session validation failed. Log in again."}), 403
    action = (request.get_json(silent=True) or {}).get("action")
    if action not in {"open", "close"}:
        return jsonify({"ok": False, "error": "Unknown gate action."}), 400
    if MODE == "hardware" and not state["connected"]:
        return jsonify({"ok": False, "error": "Arduino is disconnected."}), 503
    ok = send_command("OPEN_GATE" if action == "open" else "CLOSE_GATE")
    return (jsonify({"ok": True}) if ok else jsonify({"ok": False, "error": "Command failed."}), 200 if ok else 503)


@app.post("/api/admin/demo-occupancy")
@admin_required
def admin_demo_occupancy():
    if not csrf_ok():
        return jsonify({"ok": False, "error": "Session validation failed. Log in again."}), 403
    if MODE != "demo":
        return jsonify({"ok": False, "error": "Demo simulation is disabled in hardware mode."}), 400
    occupied = bool((request.get_json(silent=True) or {}).get("occupied"))
    with state_lock:
        changed = state["demo_occupied"] != occupied
        state["demo_occupied"] = occupied
        state["occupied"] = occupied
        state["distance_cm"] = 12.0 if occupied else 24.0
        state["last_seen"] = iso()
    if changed:
        event("DEMO_OCCUPANCY", "OCCUPIED" if occupied else "CLEAR")
        log_sensor(12.0 if occupied else 24.0, occupied, "demo")
    if not occupied:
        with db() as con:
            con.execute("UPDATE bookings SET status='COMPLETED' WHERE slot_id='P-01' AND status='CHECKED_IN'")
    return jsonify({"ok": True})


@app.get("/api/admin/export/<kind>")
@admin_required
def admin_export(kind):
    tables = {
        "bookings": ("SELECT id,slot_id,visitor_name,created_at,expires_at,status,checked_in_at FROM bookings ORDER BY created_at", "parkvision_bookings.csv"),
        "sensors": ("SELECT recorded_at,distance_cm,occupied,source FROM sensor_logs ORDER BY recorded_at", "parkvision_sensor_logs.csv"),
        "events": ("SELECT recorded_at,event_type,details FROM events ORDER BY id", "parkvision_events.csv"),
    }
    if kind not in tables:
        return jsonify({"ok": False, "error": "Unknown export type."}), 404
    query, filename = tables[kind]
    with db() as con:
        rows = con.execute(query).fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    if rows:
        writer.writerow(rows[0].keys())
        writer.writerows([tuple(row) for row in rows])
    else:
        writer.writerow(["No records yet"])
    return Response(output.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})


if __name__ == "__main__":
    init_db()
    print("PARKVISION starting on http://127.0.0.1:5000")
    print(f"Mode: {MODE}. Admin password configured: {'yes' if ADMIN_PASSWORD else 'NO'}")
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
