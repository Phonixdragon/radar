-- PARKVISION single-gate local database schema (SQLite)
CREATE TABLE IF NOT EXISTS bays (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'available'
        CHECK(status IN ('available', 'reserved')),
    current_booking_id TEXT
);

CREATE TABLE IF NOT EXISTS bookings (
    id TEXT PRIMARY KEY,
    bay_id TEXT NOT NULL REFERENCES bays(id),
    display_name TEXT NOT NULL,
    vehicle_number TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'reserved'
        CHECK(status IN ('reserved', 'completed', 'cancelled')),
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS bookings_created_at_idx ON bookings(created_at);
