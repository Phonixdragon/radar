"""Manually archive PARKVISION CSV snapshots to a private Copyparty folder.

Required environment variables:
  COPYPARTY_URL       e.g. http://100.x.y.z:3923/PARKVISION/
  COPYPARTY_PASSWORD  Copyparty upload password
Optional:
  COPYPARTY_USERNAME  needed only if your Copyparty has usernames enabled

Run from the PARKVISION folder after the Flask server has created the database.
"""
import csv
import io
import os
import sqlite3
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB = BASE / "data" / "parkvision.sqlite3"
BASE_URL = os.environ.get("COPYPARTY_URL", "").rstrip("/") + "/"
PASSWORD = os.environ.get("COPYPARTY_PASSWORD", "")
USERNAME = os.environ.get("COPYPARTY_USERNAME", "")

if not BASE_URL.startswith(("http://", "https://")) or not PASSWORD:
    raise SystemExit("Set COPYPARTY_URL and COPYPARTY_PASSWORD first. Use a private Tailscale address.")
if not DB.exists():
    raise SystemExit("PARKVISION database not found. Start the app once, then retry.")

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
exports = {
    "bookings": "SELECT id,slot_id,visitor_name,created_at,expires_at,status,checked_in_at FROM bookings ORDER BY created_at",
    "sensors": "SELECT recorded_at,distance_cm,occupied,source FROM sensor_logs ORDER BY recorded_at",
    "events": "SELECT recorded_at,event_type,details FROM events ORDER BY id",
}
with sqlite3.connect(DB) as con:
    for name, query in exports.items():
        rows = con.execute(query).fetchall()
        cols = [d[0] for d in con.execute(query).description]
        buf = io.StringIO(newline="")
        writer = csv.writer(buf)
        writer.writerow(cols)
        writer.writerows(rows)
        filename = f"{name}_{stamp}.csv"
        url = BASE_URL + urllib.parse.quote(filename)
        auth_value = f"{USERNAME}:{PASSWORD}" if USERNAME else PASSWORD
        req = urllib.request.Request(url, data=buf.getvalue().encode("utf-8"), method="PUT",
                                     headers={"PW": auth_value, "Content-Type": "text/csv"})
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                print(f"Uploaded {filename}: HTTP {response.status}")
        except Exception as exc:
            raise SystemExit(f"Upload failed for {filename}: {exc}")
print("PARKVISION archive upload finished.")
