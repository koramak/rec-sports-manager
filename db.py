"""Database layer for Rec Sports Manager. SQLite, no ORM."""
import sqlite3
import secrets
import hashlib
import os

DB_PATH = os.environ.get("REC_DB", os.path.join(os.path.dirname(__file__), "rec.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    phone TEXT,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'manager'  -- 'admin' | 'manager'
);

CREATE TABLE IF NOT EXISTS teams (
    id TEXT PRIMARY KEY,                  -- short url token
    name TEXT NOT NULL,
    sport TEXT DEFAULT 'Softball',
    owner_id INTEGER NOT NULL REFERENCES users(id),
    min_players INTEGER NOT NULL DEFAULT 8,
    min_male INTEGER NOT NULL DEFAULT 0,
    min_female INTEGER NOT NULL DEFAULT 0
);

-- co-managers (owner is implicitly a manager of the team)
CREATE TABLE IF NOT EXISTS team_managers (
    team_id TEXT NOT NULL REFERENCES teams(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    PRIMARY KEY (team_id, user_id)
);

CREATE TABLE IF NOT EXISTS players (
    id TEXT PRIMARY KEY,                  -- short url token
    manager_id INTEGER NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    gender TEXT NOT NULL,                 -- 'M' | 'F'
    phone TEXT,
    email TEXT,
    number TEXT,
    positions TEXT,                       -- comma list from P,C,1B,2B,3B,SS,OF
    skill TEXT,
    notes TEXT,
    is_sub INTEGER NOT NULL DEFAULT 0     -- member of this manager's sub pool
);

CREATE TABLE IF NOT EXISTS team_players (
    team_id TEXT NOT NULL REFERENCES teams(id),
    player_id TEXT NOT NULL REFERENCES players(id),
    PRIMARY KEY (team_id, player_id)
);

CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id TEXT NOT NULL REFERENCES teams(id),
    game_dt TEXT NOT NULL,                -- 'YYYY-MM-DD HH:MM'
    location TEXT,
    opponent TEXT,
    notes TEXT,
    rsvp_opened INTEGER NOT NULL DEFAULT 0,
    alert72_sent INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tournaments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id TEXT NOT NULL REFERENCES teams(id),
    name TEXT NOT NULL,
    date TEXT NOT NULL,                   -- 'YYYY-MM-DD' (single-day default)
    location TEXT,
    host TEXT,
    division TEXT DEFAULT 'Coed',         -- 'Coed' | 'Mens'
    cost REAL
);

CREATE TABLE IF NOT EXISTS tournament_invites (
    tournament_id INTEGER NOT NULL REFERENCES tournaments(id),
    player_id TEXT NOT NULL REFERENCES players(id),
    invited_at TEXT NOT NULL,
    PRIMARY KEY (tournament_id, player_id)
);

CREATE TABLE IF NOT EXISTS rsvps (
    event_type TEXT NOT NULL,             -- 'game' | 'tournament'
    event_id INTEGER NOT NULL,
    player_id TEXT NOT NULL REFERENCES players(id),
    status TEXT NOT NULL DEFAULT 'tbd',   -- 'in' | 'out' | 'tbd'
    updated_at TEXT NOT NULL,
    PRIMARY KEY (event_type, event_id, player_id)
);

CREATE TABLE IF NOT EXISTS sub_invites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER NOT NULL REFERENCES games(id),
    player_id TEXT NOT NULL REFERENCES players(id),
    token TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'tbd',
    created_at TEXT NOT NULL
);

-- Outbox: messages the system "sends" (SMS/email gateway stub).
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contact TEXT NOT NULL,                -- phone or email it was sent to
    channel TEXT NOT NULL,                -- 'sms' | 'email'
    recipient TEXT NOT NULL,              -- display name
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    team_id TEXT REFERENCES teams(id),
    kind TEXT NOT NULL,                   -- 'short72' | 'emergency'
    message TEXT NOT NULL,
    created_at TEXT NOT NULL,
    is_read INTEGER NOT NULL DEFAULT 0
);

-- one reminder per player per event per day
CREATE TABLE IF NOT EXISTS reminder_log (
    event_type TEXT NOT NULL,
    event_id INTEGER NOT NULL,
    player_id TEXT NOT NULL,
    sent_on TEXT NOT NULL,                -- 'YYYY-MM-DD'
    PRIMARY KEY (event_type, event_id, player_id, sent_on)
);
"""


def connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def init_db():
    con = connect()
    con.executescript(SCHEMA)
    # seed the system admin if missing
    if not con.execute("SELECT 1 FROM users WHERE role='admin'").fetchone():
        con.execute(
            "INSERT INTO users (name, email, password_hash, role) VALUES (?,?,?,?)",
            ("System Admin", "admin@rec.local", hash_password("admin"), "admin"),
        )
    con.commit()
    con.close()


def new_token(nbytes=5):
    return secrets.token_hex(nbytes)


def hash_password(password):
    salt = secrets.token_hex(8)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return salt + "$" + digest.hex()


def check_password(stored, password):
    try:
        salt, digest = stored.split("$", 1)
    except ValueError:
        return False
    check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return secrets.compare_digest(check.hex(), digest)


def short_name(full_name):
    """'Dave Miller' -> 'Dave M.'"""
    parts = full_name.split()
    if len(parts) < 2:
        return full_name
    return "%s %s." % (parts[0], parts[-1][0].upper())
