"""Notification engine: automated RSVP requests, daily reminders, 72-hour
short-roster alerts, tournament reminders, and emergency alerts.

Messages are written to the `notifications` outbox table (an SMS/email
gateway stub) — one consolidated message per contact per tick, so a player
on multiple teams gets a single batched text instead of several.
"""
import os
from datetime import datetime, timedelta

DT_FMT = "%Y-%m-%d %H:%M"
D_FMT = "%Y-%m-%d"
BASE_URL = (os.environ.get("REC_BASE_URL")
            or os.environ.get("RENDER_EXTERNAL_URL")  # set by Render hosting
            or "http://localhost:%s" % os.environ.get("PORT", "5000")).rstrip("/")


def parse_dt(s):
    return datetime.strptime(s, DT_FMT)


def parse_d(s):
    return datetime.strptime(s, D_FMT)


def fmt_gamedt(s):
    """'2026-07-06 19:00' -> 'Mon, Jul 6 · 7:00 PM' (dates always 'ddd, MMM d')."""
    d = parse_dt(s)
    t = d.strftime("%I:%M %p").lstrip("0")
    return "%s, %s %d · %s" % (d.strftime("%a"), d.strftime("%b"), d.day, t)


def fmt_date(s):
    """'2026-08-08' -> 'Sat, Aug 8'."""
    d = parse_d(s)
    return "%s, %s %d" % (d.strftime("%a"), d.strftime("%b"), d.day)


def matchup(game):
    """'vs Opponent' at home, '@ Opponent' away."""
    try:
        away = game["home_away"] == "away"
    except (KeyError, IndexError):
        away = False
    return "%s %s" % ("@" if away else "vs", game["opponent"] or "TBD")


def contact_key(player):
    """Players are matched across teams/managers by contact info."""
    return (player["phone"] or "").strip() or (player["email"] or "").strip().lower()


def player_link(team_id, player_id):
    return "%s/%s/%s" % (BASE_URL, team_id, player_id)


def sub_link(token):
    return "%s/sub/%s" % (BASE_URL, token)


# ---------------------------------------------------------------- outbox

class Collector:
    """Accumulates message lines per player, flushes one message per contact."""

    def __init__(self):
        self.items = {}  # contact_key -> {"player": row, "lines": [..]}

    def add(self, player, line):
        key = contact_key(player)
        if not key:
            return
        entry = self.items.setdefault(key, {"player": player, "lines": []})
        entry["lines"].append(line)

    def flush(self, con, now):
        for key, entry in self.items.items():
            p = entry["player"]
            channel = "sms" if (p["phone"] or "").strip() else "email"
            body = "\n".join(entry["lines"])
            con.execute(
                "INSERT INTO notifications (contact, channel, recipient, body, created_at)"
                " VALUES (?,?,?,?,?)",
                (key, channel, p["name"], body, now.strftime(DT_FMT)),
            )
        self.items = {}


def send_now(con, player, line, now):
    """Immediate single message (sub invites, tournament invites)."""
    c = Collector()
    c.add(player, line)
    c.flush(con, now)


# ---------------------------------------------------------------- counts

def game_counts(con, game):
    """In-counts for a game, split by gender. Confirmed subs count too."""
    row = con.execute(
        """SELECT
             COALESCE(SUM(CASE WHEN p.gender='M' THEN 1 ELSE 0 END),0) AS m,
             COALESCE(SUM(CASE WHEN p.gender='F' THEN 1 ELSE 0 END),0) AS f
           FROM rsvps r JOIN players p ON p.id = r.player_id
           WHERE r.event_type='game' AND r.event_id=? AND r.status='in'""",
        (game["id"],),
    ).fetchone()
    sub = con.execute(
        """SELECT
             COALESCE(SUM(CASE WHEN p.gender='M' THEN 1 ELSE 0 END),0) AS m,
             COALESCE(SUM(CASE WHEN p.gender='F' THEN 1 ELSE 0 END),0) AS f
           FROM sub_invites s JOIN players p ON p.id = s.player_id
           WHERE s.game_id=? AND s.status='in'""",
        (game["id"],),
    ).fetchone()
    male, female = row["m"] + sub["m"], row["f"] + sub["f"]
    return {"male": male, "female": female, "total": male + female}


def game_shortfall(con, game, team):
    """Human-readable list of unmet minimums, empty if the game is covered."""
    c = game_counts(con, game)
    problems = []
    if c["total"] < team["min_players"]:
        problems.append("%d/%d players" % (c["total"], team["min_players"]))
    if team["min_male"] and c["male"] < team["min_male"]:
        problems.append("%d/%d men" % (c["male"], team["min_male"]))
    if team["min_female"] and c["female"] < team["min_female"]:
        problems.append("%d/%d women" % (c["female"], team["min_female"]))
    return problems


def team_manager_ids(con, team):
    ids = {team["owner_id"]}
    for r in con.execute("SELECT user_id FROM team_managers WHERE team_id=?", (team["id"],)):
        ids.add(r["user_id"])
    return ids


def alert_managers(con, team, kind, message, now):
    """In-app alert plus an SMS to each manager (email fallback), via the outbox."""
    for uid in team_manager_ids(con, team):
        con.execute(
            "INSERT INTO alerts (user_id, team_id, kind, message, created_at)"
            " VALUES (?,?,?,?,?)",
            (uid, team["id"], kind, message, now.strftime(DT_FMT)),
        )
        u = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if not u:
            continue
        contact = (u["phone"] or "").strip() or (u["email"] or "").strip().lower()
        if not contact:
            continue
        channel = "sms" if (u["phone"] or "").strip() else "email"
        con.execute(
            "INSERT INTO notifications (contact, channel, recipient, body, created_at)"
            " VALUES (?,?,?,?,?)",
            (contact, channel, u["name"], message, now.strftime(DT_FMT)),
        )


# ---------------------------------------------------------------- helpers

def rostered_players(con, team_id):
    return con.execute(
        """SELECT p.* FROM players p JOIN team_players tp ON tp.player_id = p.id
           WHERE tp.team_id=? ORDER BY p.name""",
        (team_id,),
    ).fetchall()


def rsvp_status(con, event_type, event_id, player_id):
    r = con.execute(
        "SELECT status FROM rsvps WHERE event_type=? AND event_id=? AND player_id=?",
        (event_type, event_id, player_id),
    ).fetchone()
    return r["status"] if r else "tbd"


def reminded_today(con, event_type, event_id, player_id, now):
    return con.execute(
        "SELECT 1 FROM reminder_log WHERE event_type=? AND event_id=? AND player_id=? AND sent_on=?",
        (event_type, event_id, player_id, now.strftime(D_FMT)),
    ).fetchone() is not None


def log_reminder(con, event_type, event_id, player_id, now):
    con.execute(
        "INSERT OR IGNORE INTO reminder_log (event_type, event_id, player_id, sent_on) VALUES (?,?,?,?)",
        (event_type, event_id, player_id, now.strftime(D_FMT)),
    )


def game_line(team, game):
    return "%s %s on %s at %s" % (
        team["name"], matchup(game), fmt_gamedt(game["game_dt"]), game["location"] or "TBD")


# ---------------------------------------------------------------- the tick

def run_tick(con, now=None):
    """One scheduler pass. Idempotent per day/threshold; safe to run often."""
    now = now or datetime.now()
    outbox = Collector()

    teams = {t["id"]: t for t in con.execute("SELECT * FROM teams")}

    # --- games ---
    games = con.execute("SELECT * FROM games ORDER BY game_dt").fetchall()
    by_team = {}
    for g in games:
        by_team.setdefault(g["team_id"], []).append(g)

    for team_id, tgames in by_team.items():
        team = teams.get(team_id)
        if not team:
            continue
        for i, g in enumerate(tgames):
            gdt = parse_dt(g["game_dt"])
            if gdt < now:
                continue  # past game

            # 1. Open RSVPs: morning after the previous game OR 7 days out.
            if not g["rsvp_opened"]:
                opens_at = gdt - timedelta(days=7)
                prev = [x for x in tgames if parse_dt(x["game_dt"]) < gdt]
                if prev:
                    prev_dt = parse_dt(prev[-1]["game_dt"])
                    morning_after = (prev_dt + timedelta(days=1)).replace(hour=8, minute=0)
                    opens_at = min(opens_at, morning_after)
                if now >= opens_at:
                    con.execute("UPDATE games SET rsvp_opened=1 WHERE id=?", (g["id"],))
                    g = dict(g, rsvp_opened=1)
                    # the initial request counts as today's touch (reminder_log
                    # entries below keep step 2 from double-messaging)
                    for p in rostered_players(con, team_id):
                        outbox.add(p, "RSVP for %s: %s" % (
                            game_line(team, g), player_link(team_id, p["id"])))
                        log_reminder(con, "game", g["id"], p["id"], now)

            # 2. Daily reminders to anyone not firmly in/out.
            if g["rsvp_opened"]:
                for p in rostered_players(con, team_id):
                    if rsvp_status(con, "game", g["id"], p["id"]) in ("in", "out"):
                        continue
                    if reminded_today(con, "game", g["id"], p["id"], now):
                        continue
                    outbox.add(p, "Reminder — still need your RSVP for %s: %s" % (
                        game_line(team, g), player_link(team_id, p["id"])))
                    log_reminder(con, "game", g["id"], p["id"], now)

            # 3. 72-hour short-roster alert to managers.
            if not g["alert72_sent"] and now >= gdt - timedelta(hours=72):
                con.execute("UPDATE games SET alert72_sent=1 WHERE id=?", (g["id"],))
                problems = game_shortfall(con, g, team)
                if problems:
                    alert_managers(con, team, "short72",
                        "72-hour check: %s is SHORT (%s). Pick subs to fill the gap."
                        % (game_line(team, g), ", ".join(problems)), now)

    # --- tournaments: daily reminders start exactly 3 weeks out ---
    for t in con.execute("SELECT * FROM tournaments").fetchall():
        team = teams.get(t["team_id"])
        if not team:
            continue
        tdate = parse_d(t["date"])
        if tdate.date() < now.date():
            continue
        if now < tdate - timedelta(days=21):
            continue
        invitees = con.execute(
            """SELECT p.* FROM players p JOIN tournament_invites ti ON ti.player_id = p.id
               WHERE ti.tournament_id=?""", (t["id"],)).fetchall()
        for p in invitees:
            if rsvp_status(con, "tournament", t["id"], p["id"]) in ("in", "out"):
                continue
            if reminded_today(con, "tournament", t["id"], p["id"], now):
                continue
            outbox.add(p, "Reminder — RSVP for tournament %s on %s (%s, ~$%s/person): %s" % (
                t["name"], fmt_date(t["date"]), t["division"], t["cost"] or "?",
                player_link(team["id"], p["id"])))
            log_reminder(con, "tournament", t["id"], p["id"], now)

    outbox.flush(con, now)
    con.commit()


# ------------------------------------------------- emergency status alerts

def emergency_check(con, game, team, was_covered, now=None):
    """Called after an RSVP change. If the change dropped a near-term game
    below its minimums, alert managers immediately."""
    now = now or datetime.now()
    gdt = parse_dt(game["game_dt"])
    if not (now <= gdt <= now + timedelta(hours=72)):
        return
    problems = game_shortfall(con, game, team)
    if was_covered and problems:
        alert_managers(con, team, "emergency",
            "EMERGENCY: a status change dropped %s below minimums (%s)."
            % (game_line(team, game), ", ".join(problems)), now)
        con.commit()
