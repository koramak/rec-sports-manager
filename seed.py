"""Seed demo data so every workflow is visible immediately.

Usage: python3 seed.py   (safe to re-run: it wipes and recreates the demo db)
"""
import os
from datetime import datetime, timedelta

import db
import notify

if os.path.exists(db.DB_PATH):
    os.remove(db.DB_PATH)
db.init_db()

con = db.connect()
now = datetime.now()


def dt(days, hour=19, minute=0):
    return (now + timedelta(days=days)).replace(hour=hour, minute=minute).strftime(notify.DT_FMT)


def d(days):
    return (now + timedelta(days=days)).strftime(notify.D_FMT)


# manager
cur = con.execute(
    "INSERT INTO users (name, email, phone, password_hash) VALUES (?,?,?,?)",
    ("Zane Miller", "zane@example.com", "555-0100", db.hash_password("demo")))
manager_id = cur.lastrowid

# team
team_id = "demo"
con.execute(
    "INSERT INTO teams (id, name, sport, owner_id, min_players, min_male, min_female)"
    " VALUES (?,?,?,?,?,?,?)",
    (team_id, "Brew Crew", "Coed Softball", manager_id, 10, 5, 4))

ROSTER = [
    ("Dave Miller", "M", "555-0101", "", "7", "P,SS", "B", ""),
    ("Sara Ortiz", "F", "555-0102", "", "12", "C,2B", "A", ""),
    ("Mike Chen", "M", "555-0103", "", "23", "OF", "B", ""),
    ("Jess Park", "F", "", "jess@example.com", "3", "1B", "B", "prefers infield"),
    ("Tom Alvarez", "M", "555-0105", "", "9", "3B,OF", "C", ""),
    ("Amy Rhodes", "F", "555-0106", "", "18", "OF", "B", ""),
    ("Luis Gomez", "M", "555-0107", "", "5", "SS,2B", "A", ""),
    ("Nina Patel", "F", "555-0108", "", "21", "OF,C", "C", ""),
    ("Ray Johnson", "M", "555-0109", "", "44", "1B,P", "B", ""),
    ("Kate Wu", "F", "555-0110", "", "8", "2B", "B", ""),
    ("Ben Foster", "M", "555-0111", "", "2", "OF", "C", ""),
]
player_ids = []
for name, g, phone, email, num, pos, skill, notes_ in ROSTER:
    pid = db.new_token(5)
    player_ids.append(pid)
    con.execute(
        "INSERT INTO players (id, manager_id, name, gender, phone, email, number,"
        " positions, skill, notes, is_sub) VALUES (?,?,?,?,?,?,?,?,?,?,0)",
        (pid, manager_id, name, g, phone, email, num, pos, skill, notes_))
    con.execute("INSERT INTO team_players (team_id, player_id) VALUES (?,?)", (team_id, pid))

SUBS = [
    ("Carlos Vega", "M", "555-0201", "", "P,OF", "A"),
    ("Dana Kim", "F", "555-0202", "", "C,1B", "B"),
    ("Erin Walsh", "F", "", "erin@example.com", "OF", "B"),
    ("Frank Ito", "M", "555-0204", "", "SS", "A"),
]
for name, g, phone, email, pos, skill in SUBS:
    con.execute(
        "INSERT INTO players (id, manager_id, name, gender, phone, email, number,"
        " positions, skill, notes, is_sub) VALUES (?,?,?,?,?,?,'',?,?,'',1)",
        (db.new_token(5), manager_id, name, g, phone, email, pos, skill))

# games: one inside the 72h window (drives the short alert), one next week
cur = con.execute(
    "INSERT INTO games (team_id, game_dt, location, opponent) VALUES (?,?,?,?)",
    (team_id, dt(2), "Riverside Field #3", "The Mashers"))
game_soon = cur.lastrowid
con.execute(
    "INSERT INTO games (team_id, game_dt, location, opponent) VALUES (?,?,?,?)",
    (team_id, dt(9), "Riverside Field #1", "Pitch Slap"))

# some RSVPs for the near game: 6 in (4M/2F) -> short vs 10 total / 5M / 4F
ts = now.strftime(notify.DT_FMT)
for i, status in enumerate(["in", "in", "in", "out", "in", "in", "tbd", "in", "out", "tbd", "tbd"]):
    con.execute(
        "INSERT INTO rsvps (event_type, event_id, player_id, status, updated_at)"
        " VALUES ('game',?,?,?,?)", (game_soon, player_ids[i], status, ts))

# tournament two weeks out (inside the 3-week reminder window), invite everyone
cur = con.execute(
    "INSERT INTO tournaments (team_id, name, date, location, host, division, cost)"
    " VALUES (?,?,?,?,?,?,?)",
    (team_id, "Summer Slam", d(14), "Lakeview Complex", "Metro Rec League", "Coed", 35))
tourney = cur.lastrowid
for pid in player_ids[:8]:
    con.execute(
        "INSERT INTO tournament_invites (tournament_id, player_id, invited_at) VALUES (?,?,?)",
        (tourney, pid, ts))

con.commit()

# run one scheduler pass so requests/reminders/alerts exist right away
notify.run_tick(con)
con.close()

print("Seeded demo data.")
print("  Manager login: zane@example.com / demo")
print("  Admin login:   admin@rec.local / admin")
print("  Team RSVP link: %s/%s" % (notify.BASE_URL, team_id))
