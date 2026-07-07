"""Rec Sports Manager — Flask app (PRD 1.0)."""
import csv
import io
import os
import re
import threading
from datetime import datetime
from functools import wraps

from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   session, url_for)

import db
import notify

app = Flask(__name__)
app.secret_key = os.environ.get("REC_SECRET", "dev-secret-change-me")

POSITIONS = ["P", "C", "1B", "2B", "3B", "SS", "OF"]
STATUSES = ["in", "out", "tbd"]
SKILLS = ["competitive", "intermediate", "beginner"]

app.template_filter("gamedt")(notify.fmt_gamedt)
app.template_filter("fmtdate")(notify.fmt_date)


def normalize_phone(raw):
    """US numbers only (+1). Returns '(555) 555-0101', '' for empty,
    or None when the input isn't a valid 10-digit number."""
    digits = re.sub(r"\D", "", raw or "")
    if not digits:
        return ""
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return None
    return "(%s) %s-%s" % (digits[:3], digits[3:6], digits[6:])


def short_bits(con, game, team):
    """Shortfall for the status strips: {'more': 1, 'genders': '1F'} or None."""
    c = notify.game_counts(con, game)
    more = max(0, team["min_players"] - c["total"])
    genders = []
    if team["min_male"] and c["male"] < team["min_male"]:
        genders.append("%dM" % (team["min_male"] - c["male"]))
    if team["min_female"] and c["female"] < team["min_female"]:
        genders.append("%dF" % (team["min_female"] - c["female"]))
    if not more and not genders:
        return None
    return {"more": more, "genders": " · ".join(genders)}


# ------------------------------------------------------------ plumbing

def get_con():
    if "con" not in g:
        g.con = db.connect()
    return g.con


@app.teardown_appcontext
def close_con(exc):
    con = g.pop("con", None)
    if con is not None:
        con.close()


def current_user():
    uid = session.get("uid")
    if not uid:
        return None
    return get_con().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        u = current_user()
        if not u or u["role"] != "admin":
            abort(403)
        return f(*args, **kwargs)
    return wrapper


def can_manage(team):
    """Owner, co-manager, or system admin."""
    u = current_user()
    if not u:
        return False
    if u["role"] == "admin" or team["owner_id"] == u["id"]:
        return True
    return get_con().execute(
        "SELECT 1 FROM team_managers WHERE team_id=? AND user_id=?",
        (team["id"], u["id"])).fetchone() is not None


def get_team_or_404(team_id, manage=False):
    team = get_con().execute("SELECT * FROM teams WHERE id=?", (team_id,)).fetchone()
    if not team:
        abort(404)
    if manage and not can_manage(team):
        abort(403)
    return team


def get_player_or_404(player_id, manage=False):
    p = get_con().execute("SELECT * FROM players WHERE id=?", (player_id,)).fetchone()
    if not p:
        abort(404)
    if manage:
        u = current_user()
        if not u or (u["role"] != "admin" and p["manager_id"] != u["id"]):
            abort(403)
    return p


def my_teams(u):
    return get_con().execute(
        """SELECT DISTINCT t.* FROM teams t
           LEFT JOIN team_managers tm ON tm.team_id = t.id
           WHERE t.owner_id=? OR tm.user_id=? ORDER BY t.name""",
        (u["id"], u["id"])).fetchall()


@app.context_processor
def inject_globals():
    u = current_user()
    unread = 0
    if u:
        unread = get_con().execute(
            "SELECT COUNT(*) c FROM alerts WHERE user_id=? AND is_read=0",
            (u["id"],)).fetchone()["c"]
    return {"user": u, "unread_alerts": unread, "short_name": db.short_name,
            "POSITIONS": POSITIONS, "SKILLS": SKILLS, "matchup": notify.matchup}


# ------------------------------------------------------------ auth

@app.route("/")
def index():
    if current_user():
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        phone = normalize_phone(request.form.get("phone", ""))
        if not (name and email and password):
            flash("All fields are required.")
        elif phone is None:
            flash("Phone must be a 10-digit US number (country code +1).")
        elif get_con().execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            flash("That email is already registered.")
        else:
            con = get_con()
            cur = con.execute(
                "INSERT INTO users (name, email, phone, password_hash) VALUES (?,?,?,?)",
                (name, email, phone, db.hash_password(password)))
            con.commit()
            session["uid"] = cur.lastrowid
            return redirect(url_for("dashboard"))
    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        u = get_con().execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if u and db.check_password(u["password_hash"], request.form["password"]):
            session["uid"] = u["id"]
            return redirect(request.args.get("next") or url_for("dashboard"))
        flash("Invalid email or password.")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ------------------------------------------------------------ dashboard

@app.route("/dashboard")
@login_required
def dashboard():
    u = current_user()
    con = get_con()
    teams = my_teams(u)
    cards = []
    now = datetime.now().strftime(notify.DT_FMT)
    for t in teams:
        game = con.execute(
            "SELECT * FROM games WHERE team_id=? AND game_dt>=? ORDER BY game_dt LIMIT 1",
            (t["id"], now)).fetchone()
        info = None
        if game:
            info = {"game": game,
                    "counts": notify.game_counts(con, game),
                    "short": short_bits(con, game, t)}
        cards.append({"team": t, "next": info})
    recent_alerts = con.execute(
        "SELECT * FROM alerts WHERE user_id=? ORDER BY created_at DESC LIMIT 6",
        (u["id"],)).fetchall()
    return render_template("dashboard.html", cards=cards, recent_alerts=recent_alerts)


@app.route("/tick", methods=["POST"])
@login_required
def tick():
    notify.run_tick(get_con())
    flash("Scheduler ran: requests, reminders and alerts are up to date.")
    return redirect(request.referrer or url_for("dashboard"))


# ------------------------------------------------------------ teams

@app.route("/teams/new", methods=["GET", "POST"])
@login_required
def team_new():
    if request.method == "POST":
        con = get_con()
        tid = db.new_token(4)
        con.execute(
            """INSERT INTO teams (id, name, sport, owner_id, min_players, min_male,
                                  min_female, team_type)
               VALUES (?,?,?,?,?,?,?,?)""",
            (tid, request.form["name"].strip(), request.form.get("sport", "").strip(),
             current_user()["id"],
             int(request.form.get("min_players") or 0),
             int(request.form.get("min_male") or 0),
             int(request.form.get("min_female") or 0),
             "tournament" if request.form.get("team_type") == "tournament" else "league"))
        con.commit()
        return redirect(url_for("team_manage", team_id=tid))
    return render_template("team_form.html", team=None, comanagers=[])


@app.route("/team/<team_id>/settings", methods=["GET", "POST"])
@login_required
def team_settings(team_id):
    team = get_team_or_404(team_id, manage=True)
    con = get_con()
    if request.method == "POST":
        con.execute(
            """UPDATE teams SET name=?, sport=?, min_players=?, min_male=?, min_female=?,
                      team_type=? WHERE id=?""",
            (request.form["name"].strip(), request.form.get("sport", "").strip(),
             int(request.form.get("min_players") or 0),
             int(request.form.get("min_male") or 0),
             int(request.form.get("min_female") or 0),
             "tournament" if request.form.get("team_type") == "tournament" else "league",
             team_id))
        con.commit()
        flash("Team updated.")
        return redirect(url_for("team_manage", team_id=team_id))
    comanagers = con.execute(
        """SELECT u.* FROM users u JOIN team_managers tm ON tm.user_id=u.id
           WHERE tm.team_id=?""", (team_id,)).fetchall()
    return render_template("team_form.html", team=team, comanagers=comanagers)


@app.route("/team/<team_id>/comanagers", methods=["POST"])
@login_required
def comanager_add(team_id):
    team = get_team_or_404(team_id, manage=True)
    con = get_con()
    email = request.form["email"].strip().lower()
    u = con.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    if not u:
        flash("No manager account with that email. Ask them to sign up first.")
    elif u["id"] == team["owner_id"]:
        flash("That's already the team owner.")
    else:
        con.execute("INSERT OR IGNORE INTO team_managers (team_id, user_id) VALUES (?,?)",
                    (team_id, u["id"]))
        con.commit()
        flash("%s added as co-manager." % u["name"])
    return redirect(url_for("team_settings", team_id=team_id))


@app.route("/team/<team_id>/comanagers/<int:user_id>/remove", methods=["POST"])
@login_required
def comanager_remove(team_id, user_id):
    get_team_or_404(team_id, manage=True)
    con = get_con()
    con.execute("DELETE FROM team_managers WHERE team_id=? AND user_id=?", (team_id, user_id))
    con.commit()
    return redirect(url_for("team_settings", team_id=team_id))


@app.route("/team/<team_id>/manage")
@login_required
def team_manage(team_id):
    team = get_team_or_404(team_id, manage=True)
    con = get_con()
    roster = notify.rostered_players(con, team_id)
    now = datetime.now().strftime(notify.DT_FMT)
    games = con.execute(
        "SELECT * FROM games WHERE team_id=? AND game_dt>=? ORDER BY game_dt",
        (team_id, now)).fetchall()
    past = con.execute(
        "SELECT * FROM games WHERE team_id=? AND game_dt<? ORDER BY game_dt DESC LIMIT 5",
        (team_id, now)).fetchall()
    game_infos = [{"game": gm, "counts": notify.game_counts(con, gm),
                   "short": short_bits(con, gm, team)} for gm in games]
    tournaments = con.execute(
        "SELECT * FROM tournaments WHERE team_id=? AND date>=? ORDER BY date",
        (team_id, datetime.now().strftime(notify.D_FMT))).fetchall()
    return render_template("team.html", team=team, roster=roster,
                           game_infos=game_infos, past=past,
                           tournaments=tournaments,
                           base_url=notify.BASE_URL)


# ------------------------------------------------------------ players

def player_from_form(form):
    """Returns (data, error). error is a message to flash, or None."""
    positions = ",".join(p for p in POSITIONS if form.get("pos_" + p))
    phone = normalize_phone(form.get("phone", ""))
    error = None
    if phone is None:
        error = "Phone must be a 10-digit US number including area code (country code +1)."
        phone = ""
    skill = form.get("skill", "").strip().lower()
    d = {
        "name": form["name"].strip(),
        "gender": form.get("gender", "M"),
        "phone": phone,
        "email": form.get("email", "").strip(),
        "number": "",
        "positions": positions,
        "skill": skill if skill in SKILLS else "",
        "notes": form.get("notes", "").strip(),
    }
    if not error and (not d["name"] or not (d["phone"] or d["email"])):
        error = "Name and at least one contact method (phone or email) are required."
    return d, error


@app.route("/team/<team_id>/players/new", methods=["GET", "POST"])
@login_required
def player_new(team_id):
    team = get_team_or_404(team_id, manage=True)
    if request.method == "POST":
        d, err = player_from_form(request.form)
        if err:
            flash(err)
            return render_template("player_form.html", team=team, player=None, is_sub=False)
        con = get_con()
        pid = db.new_token(5)
        con.execute(
            """INSERT INTO players (id, manager_id, name, gender, phone, email, number,
                                    positions, skill, notes, is_sub)
               VALUES (?,?,?,?,?,?,?,?,?,?,0)""",
            (pid, team["owner_id"], d["name"], d["gender"], d["phone"], d["email"],
             d["number"], d["positions"], d["skill"], d["notes"]))
        con.execute("INSERT INTO team_players (team_id, player_id) VALUES (?,?)",
                    (team_id, pid))
        con.commit()
        return redirect(url_for("team_manage", team_id=team_id))
    return render_template("player_form.html", team=team, player=None, is_sub=False)


@app.route("/players/new", methods=["GET", "POST"])
@login_required
def sub_new():
    if request.method == "POST":
        d, err = player_from_form(request.form)
        if err:
            flash(err)
            return render_template("player_form.html", team=None, player=None, is_sub=True)
        con = get_con()
        con.execute(
            """INSERT INTO players (id, manager_id, name, gender, phone, email, number,
                                    positions, skill, notes, is_sub)
               VALUES (?,?,?,?,?,?,?,?,?,?,1)""",
            (db.new_token(5), current_user()["id"], d["name"], d["gender"], d["phone"],
             d["email"], d["number"], d["positions"], d["skill"], d["notes"]))
        con.commit()
        return redirect(url_for("subs"))
    return render_template("player_form.html", team=None, player=None, is_sub=True)


@app.route("/player/<player_id>/edit", methods=["GET", "POST"])
@login_required
def player_edit(player_id):
    p = get_player_or_404(player_id, manage=True)
    if request.method == "POST":
        d, err = player_from_form(request.form)
        if err:
            flash(err)
        else:
            con = get_con()
            con.execute(
                """UPDATE players SET name=?, gender=?, phone=?, email=?, number=?,
                          positions=?, skill=?, notes=? WHERE id=?""",
                (d["name"], d["gender"], d["phone"], d["email"], d["number"],
                 d["positions"], d["skill"], d["notes"], player_id))
            con.commit()
            flash("Player updated.")
            return redirect(request.args.get("next") or url_for("dashboard"))
    return render_template("player_form.html", team=None, player=p, is_sub=bool(p["is_sub"]))


@app.route("/player/<player_id>/delete", methods=["POST"])
@login_required
def player_delete(player_id):
    get_player_or_404(player_id, manage=True)
    con = get_con()
    for table, col in [("team_players", "player_id"), ("rsvps", "player_id"),
                       ("sub_invites", "player_id"), ("tournament_invites", "player_id")]:
        con.execute("DELETE FROM %s WHERE %s=?" % (table, col), (player_id,))
    con.execute("DELETE FROM players WHERE id=?", (player_id,))
    con.commit()
    return redirect(request.args.get("next") or url_for("dashboard"))


def demote_to_sub(con, team_id, player_id):
    """Take a player off a team roster without deleting them. Once they're on
    no roster at all they become part of the manager's sub pool."""
    con.execute("DELETE FROM team_players WHERE team_id=? AND player_id=?",
                (team_id, player_id))
    if not con.execute("SELECT 1 FROM team_players WHERE player_id=?",
                       (player_id,)).fetchone():
        con.execute("UPDATE players SET is_sub=1 WHERE id=?", (player_id,))


@app.route("/team/<team_id>/roster/remove/<player_id>", methods=["POST"])
@login_required
def roster_remove(team_id, player_id):
    get_team_or_404(team_id, manage=True)
    p = get_player_or_404(player_id)
    con = get_con()
    demote_to_sub(con, team_id, player_id)
    con.commit()
    flash("%s moved off the roster into your sub pool." % p["name"])
    return redirect(url_for("team_manage", team_id=team_id))


@app.route("/players")
@login_required
def subs():
    """All players across every team this manager owns or co-manages,
    plus their unrostered sub pool."""
    u = current_user()
    con = get_con()
    entries = {}
    for t in my_teams(u):
        for p in notify.rostered_players(con, t["id"]):
            e = entries.setdefault(p["id"], {"player": p, "teams": []})
            e["teams"].append(t["name"])
    for p in con.execute("SELECT * FROM players WHERE manager_id=?", (u["id"],)):
        entries.setdefault(p["id"], {"player": p, "teams": []})
    items = sorted(entries.values(), key=lambda e: e["player"]["name"].lower())
    return render_template("players.html", items=items)


# ------------------------------------------------------------ import

@app.route("/team/<team_id>/import", methods=["GET", "POST"])
@login_required
def player_import(team_id):
    team = get_team_or_404(team_id, manage=True)
    if request.method == "POST":
        text = request.form.get("csv_text", "")
        upload = request.files.get("csv_file")
        if upload and upload.filename:
            text = upload.read().decode("utf-8", errors="replace")
        as_subs = bool(request.form.get("as_subs"))
        added, skipped = 0, 0
        con = get_con()
        reader = csv.DictReader(io.StringIO(text.strip()))
        for row in reader:
            row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            name = row.get("name", "")
            phone = normalize_phone(row.get("phone", "")) or ""
            email = row.get("email", "")
            skill = row.get("skill", "").strip().lower()
            if not name or not (phone or email):
                skipped += 1
                continue
            pid = db.new_token(5)
            con.execute(
                """INSERT INTO players (id, manager_id, name, gender, phone, email, number,
                                        positions, skill, notes, is_sub)
                   VALUES (?,?,?,?,?,?,'',?,?,?,?)""",
                (pid, team["owner_id"], name, row.get("gender", "M")[:1].upper() or "M",
                 phone, email, row.get("positions", ""),
                 skill if skill in SKILLS else "", row.get("notes", ""),
                 1 if as_subs else 0))
            if not as_subs:
                con.execute("INSERT INTO team_players (team_id, player_id) VALUES (?,?)",
                            (team_id, pid))
            added += 1
        con.commit()
        flash("Imported %d player(s), skipped %d row(s) missing name/contact." % (added, skipped))
        return redirect(url_for("subs") if as_subs else url_for("team_manage", team_id=team_id))
    return render_template("import.html", team=team)


# ------------------------------------------------------------ games

def game_form_values(form):
    return (form["date"] + " " + form["time"], form.get("location", "").strip(),
            form.get("opponent", "").strip(), form.get("notes", "").strip(),
            "away" if form.get("home_away") == "away" else "home")


@app.route("/team/<team_id>/games/new", methods=["GET", "POST"])
@login_required
def game_new(team_id):
    team = get_team_or_404(team_id, manage=True)
    if request.method == "POST":
        con = get_con()
        gdt, loc, opp, notes, home_away = game_form_values(request.form)
        con.execute(
            "INSERT INTO games (team_id, game_dt, location, opponent, notes, home_away)"
            " VALUES (?,?,?,?,?,?)",
            (team_id, gdt, loc, opp, notes, home_away))
        con.commit()
        return redirect(url_for("team_manage", team_id=team_id))
    return render_template("game_form.html", team=team, game=None)


@app.route("/game/<int:game_id>/edit", methods=["GET", "POST"])
@login_required
def game_edit(game_id):
    con = get_con()
    game = con.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone()
    if not game:
        abort(404)
    team = get_team_or_404(game["team_id"], manage=True)
    if request.method == "POST":
        gdt, loc, opp, notes, home_away = game_form_values(request.form)
        con.execute("UPDATE games SET game_dt=?, location=?, opponent=?, notes=?, home_away=?"
                    " WHERE id=?", (gdt, loc, opp, notes, home_away, game_id))
        con.commit()
        flash("Game updated.")
        return redirect(url_for("game_view", game_id=game_id))
    return render_template("game_form.html", team=team, game=game)


@app.route("/game/<int:game_id>/delete", methods=["POST"])
@login_required
def game_delete(game_id):
    con = get_con()
    game = con.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone()
    if not game:
        abort(404)
    get_team_or_404(game["team_id"], manage=True)
    con.execute("DELETE FROM rsvps WHERE event_type='game' AND event_id=?", (game_id,))
    con.execute("DELETE FROM sub_invites WHERE game_id=?", (game_id,))
    con.execute("DELETE FROM games WHERE id=?", (game_id,))
    con.commit()
    return redirect(url_for("team_manage", team_id=game["team_id"]))


@app.route("/game/<int:game_id>")
@login_required
def game_view(game_id):
    con = get_con()
    game = con.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone()
    if not game:
        abort(404)
    team = get_team_or_404(game["team_id"], manage=True)
    roster = notify.rostered_players(con, team["id"])
    rows = []
    for p in roster:
        rows.append({"player": p, "status": notify.rsvp_status(con, "game", game_id, p["id"])})
    sub_rows = con.execute(
        """SELECT s.*, p.name, p.gender FROM sub_invites s
           JOIN players p ON p.id=s.player_id WHERE s.game_id=?""", (game_id,)).fetchall()
    invited_ids = {s["player_id"] for s in sub_rows}
    roster_ids = {p["id"] for p in roster}
    # sub pool varies per team: anyone in this manager's player pool who
    # isn't already on this team's roster
    pool = [p for p in con.execute(
        "SELECT * FROM players WHERE manager_id=? ORDER BY name",
        (team["owner_id"],)).fetchall()
        if p["id"] not in invited_ids and p["id"] not in roster_ids]
    return render_template("game.html", team=team, game=game, rows=rows,
                           counts=notify.game_counts(con, game),
                           short=short_bits(con, game, team),
                           sub_rows=sub_rows, pool=pool, base_url=notify.BASE_URL)


@app.route("/game/<int:game_id>/invite-sub", methods=["POST"])
@login_required
def invite_sub(game_id):
    con = get_con()
    game = con.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone()
    if not game:
        abort(404)
    team = get_team_or_404(game["team_id"], manage=True)
    now = datetime.now()
    for pid in request.form.getlist("player_id"):
        p = con.execute("SELECT * FROM players WHERE id=? AND manager_id=?",
                        (pid, team["owner_id"])).fetchone()
        if not p:
            continue
        token = db.new_token(8)
        con.execute(
            "INSERT INTO sub_invites (game_id, player_id, token, created_at) VALUES (?,?,?,?)",
            (game_id, pid, token, now.strftime(notify.DT_FMT)))
        notify.send_now(con, p,
            "Can you sub? %s. RSVP here: %s"
            % (notify.game_line(team, game), notify.sub_link(token)), now)
    con.commit()
    flash("Sub invite(s) sent.")
    return redirect(url_for("game_view", game_id=game_id))


# ------------------------------------------------------------ tournaments

@app.route("/team/<team_id>/tournaments/new", methods=["GET", "POST"])
@login_required
def tournament_new(team_id):
    team = get_team_or_404(team_id, manage=True)
    if request.method == "POST":
        con = get_con()
        cur = con.execute(
            """INSERT INTO tournaments (team_id, name, date, location, host, division, cost)
               VALUES (?,?,?,?,?,?,?)""",
            (team_id, request.form["name"].strip(), request.form["date"],
             request.form.get("location", "").strip(), request.form.get("host", "").strip(),
             request.form.get("division", "Coed"),
             float(request.form.get("cost") or 0)))
        con.commit()
        return redirect(url_for("tournament_view", tournament_id=cur.lastrowid))
    return render_template("tournament_form.html", team=team, tournament=None)


@app.route("/tournament/<int:tournament_id>/edit", methods=["GET", "POST"])
@login_required
def tournament_edit(tournament_id):
    con = get_con()
    t = con.execute("SELECT * FROM tournaments WHERE id=?", (tournament_id,)).fetchone()
    if not t:
        abort(404)
    team = get_team_or_404(t["team_id"], manage=True)
    if request.method == "POST":
        con.execute(
            """UPDATE tournaments SET name=?, date=?, location=?, host=?, division=?, cost=?
               WHERE id=?""",
            (request.form["name"].strip(), request.form["date"],
             request.form.get("location", "").strip(), request.form.get("host", "").strip(),
             request.form.get("division", "Coed"),
             float(request.form.get("cost") or 0), tournament_id))
        con.commit()
        return redirect(url_for("tournament_view", tournament_id=tournament_id))
    return render_template("tournament_form.html", team=team, tournament=t)


@app.route("/tournament/<int:tournament_id>")
@login_required
def tournament_view(tournament_id):
    con = get_con()
    t = con.execute("SELECT * FROM tournaments WHERE id=?", (tournament_id,)).fetchone()
    if not t:
        abort(404)
    team = get_team_or_404(t["team_id"], manage=True)
    invitees = con.execute(
        """SELECT p.* FROM players p JOIN tournament_invites ti ON ti.player_id=p.id
           WHERE ti.tournament_id=? ORDER BY p.name""", (tournament_id,)).fetchall()
    rows = [{"player": p,
             "status": notify.rsvp_status(con, "tournament", tournament_id, p["id"])}
            for p in invitees]
    invited_ids = {p["id"] for p in invitees}
    candidates = [p for p in con.execute(
        "SELECT * FROM players WHERE manager_id=? ORDER BY is_sub, name",
        (team["owner_id"],)).fetchall() if p["id"] not in invited_ids]
    in_count = sum(1 for r in rows if r["status"] == "in")
    return render_template("tournament.html", team=team, t=t, rows=rows,
                           candidates=candidates, in_count=in_count)


@app.route("/tournament/<int:tournament_id>/invite", methods=["POST"])
@login_required
def tournament_invite(tournament_id):
    con = get_con()
    t = con.execute("SELECT * FROM tournaments WHERE id=?", (tournament_id,)).fetchone()
    if not t:
        abort(404)
    team = get_team_or_404(t["team_id"], manage=True)
    now = datetime.now()
    for pid in request.form.getlist("player_id"):
        p = con.execute("SELECT * FROM players WHERE id=? AND manager_id=?",
                        (pid, team["owner_id"])).fetchone()
        if not p:
            continue
        con.execute(
            "INSERT OR IGNORE INTO tournament_invites (tournament_id, player_id, invited_at)"
            " VALUES (?,?,?)", (tournament_id, pid, now.strftime(notify.DT_FMT)))
        notify.send_now(con, p,
            "Tournament invite: %s on %s at %s (%s, ~$%s/person). RSVP: %s"
            % (t["name"], notify.fmt_date(t["date"]), t["location"] or "TBD", t["division"],
               t["cost"] or "?", notify.player_link(team["id"], pid)), now)
    con.commit()
    flash("Invite(s) sent.")
    return redirect(url_for("tournament_view", tournament_id=tournament_id))


@app.route("/tournament/<int:tournament_id>/remove/<player_id>", methods=["POST"])
@login_required
def tournament_remove(tournament_id, player_id):
    con = get_con()
    t = con.execute("SELECT * FROM tournaments WHERE id=?", (tournament_id,)).fetchone()
    if not t:
        abort(404)
    team = get_team_or_404(t["team_id"], manage=True)
    p = con.execute("SELECT * FROM players WHERE id=?", (player_id,)).fetchone()
    if not p:
        abort(404)
    con.execute("DELETE FROM tournament_invites WHERE tournament_id=? AND player_id=?",
                (tournament_id, player_id))
    con.execute("DELETE FROM rsvps WHERE event_type='tournament' AND event_id=? AND player_id=?",
                (tournament_id, player_id))
    if p["is_sub"]:
        flash("%s removed from the tournament." % p["name"])
    else:
        # roster players aren't deleted — they convert to subs
        demote_to_sub(con, team["id"], player_id)
        flash("%s removed from the tournament and moved to your sub pool." % p["name"])
    con.commit()
    return redirect(url_for("tournament_view", tournament_id=tournament_id))


# ------------------------------------------------------------ messaging

@app.route("/team/<team_id>/message", methods=["GET", "POST"])
@login_required
def team_message(team_id):
    team = get_team_or_404(team_id, manage=True)
    con = get_con()
    tournament = None
    tid = request.args.get("tournament", type=int)
    if tid:
        tournament = con.execute(
            "SELECT * FROM tournaments WHERE id=? AND team_id=?",
            (tid, team_id)).fetchone()
        if not tournament:
            abort(404)
    if tournament:
        recipients = con.execute(
            """SELECT p.* FROM players p JOIN tournament_invites ti ON ti.player_id=p.id
               WHERE ti.tournament_id=? ORDER BY p.name""",
            (tournament["id"],)).fetchall()
    else:
        recipients = notify.rostered_players(con, team_id)
    next_game = con.execute(
        "SELECT * FROM games WHERE team_id=? AND game_dt>=? ORDER BY game_dt LIMIT 1",
        (team_id, datetime.now().strftime(notify.DT_FMT))).fetchone()

    if request.method == "POST":
        body = request.form.get("body", "").strip()
        if not body:
            flash("Write a message first.")
        else:
            targets = recipients
            if tournament and request.form.get("only_in"):
                targets = [p for p in recipients if notify.rsvp_status(
                    con, "tournament", tournament["id"], p["id"]) == "in"]
            now = datetime.now()
            sent = skipped = 0
            for p in targets:
                if not notify.contact_key(p):
                    skipped += 1
                    continue
                notify.send_now(con, p, notify.expand_wildcards(
                    body, p, team, game=next_game, tournament=tournament), now)
                sent += 1
            con.commit()
            msg = "Message sent to %d player(s)." % sent
            if skipped:
                msg += " Skipped %d with no phone or email." % skipped
            flash(msg)
            if tournament:
                return redirect(url_for("tournament_view", tournament_id=tournament["id"]))
            return redirect(url_for("team_manage", team_id=team_id))
    sample = (notify.wildcard_values(recipients[0], team, game=next_game,
                                     tournament=tournament) if recipients else {})
    return render_template("message_form.html", team=team, tournament=tournament,
                           recipients=recipients, sample=sample)


# ------------------------------------------------------------ alerts / outbox / admin

@app.route("/alerts")
@login_required
def alerts():
    con = get_con()
    rows = con.execute(
        "SELECT * FROM alerts WHERE user_id=? ORDER BY created_at DESC LIMIT 100",
        (current_user()["id"],)).fetchall()
    con.execute("UPDATE alerts SET is_read=1 WHERE user_id=?", (current_user()["id"],))
    con.commit()
    return render_template("alerts.html", rows=rows)


@app.route("/outbox")
@login_required
def outbox():
    con = get_con()
    u = current_user()
    if u["role"] == "admin":
        rows = con.execute(
            "SELECT * FROM notifications ORDER BY created_at DESC LIMIT 200").fetchall()
    else:
        # the manager's players' messages, plus alert SMS sent to the manager
        rows = con.execute(
            """SELECT DISTINCT n.* FROM notifications n
               WHERE n.contact IN (
                 SELECT CASE WHEN TRIM(COALESCE(p.phone,''))<>'' THEN TRIM(p.phone)
                             ELSE LOWER(TRIM(COALESCE(p.email,''))) END
                 FROM players p WHERE p.manager_id=?)
                 OR n.contact IN (?, ?)
               ORDER BY n.created_at DESC LIMIT 200""",
            (u["id"], (u["phone"] or "").strip(),
             (u["email"] or "").strip().lower())).fetchall()
    return render_template("outbox.html", rows=rows)


@app.route("/donate")
def donate():
    return render_template("donate.html")


@app.route("/admin")
@admin_required
def admin():
    con = get_con()
    managers = con.execute("SELECT * FROM users ORDER BY role, name").fetchall()
    teams = con.execute(
        """SELECT t.*, u.name AS owner_name,
                  (SELECT COUNT(*) FROM team_players tp WHERE tp.team_id=t.id) AS roster_n
           FROM teams t JOIN users u ON u.id=t.owner_id ORDER BY t.name""").fetchall()
    stats = {
        "players": con.execute("SELECT COUNT(*) c FROM players").fetchone()["c"],
        "games": con.execute("SELECT COUNT(*) c FROM games").fetchone()["c"],
        "tournaments": con.execute("SELECT COUNT(*) c FROM tournaments").fetchone()["c"],
        "notifications": con.execute("SELECT COUNT(*) c FROM notifications").fetchone()["c"],
    }
    return render_template("admin.html", managers=managers, teams=teams, stats=stats)


# ------------------------------------------------------------ player-facing (no login)

def open_events_for_player(con, team, player_id):
    now = datetime.now()
    games = con.execute(
        "SELECT * FROM games WHERE team_id=? AND game_dt>=? ORDER BY game_dt",
        (team["id"], now.strftime(notify.DT_FMT))).fetchall()
    game_items = []
    for gm in games:
        responses = con.execute(
            """SELECT p.name, p.id AS pid, r.status FROM players p
               JOIN team_players tp ON tp.player_id=p.id AND tp.team_id=?
               LEFT JOIN rsvps r ON r.event_type='game' AND r.event_id=? AND r.player_id=p.id
               ORDER BY p.name""", (team["id"], gm["id"])).fetchall()
        game_items.append({
            "game": gm,
            "mine": notify.rsvp_status(con, "game", gm["id"], player_id),
            "responses": responses,
        })
    tournaments = con.execute(
        """SELECT t.* FROM tournaments t JOIN tournament_invites ti
             ON ti.tournament_id=t.id AND ti.player_id=?
           WHERE t.team_id=? AND t.date>=? ORDER BY t.date""",
        (player_id, team["id"], now.strftime(notify.D_FMT))).fetchall()
    t_items = []
    for t in tournaments:
        responses = con.execute(
            """SELECT p.name, p.id AS pid, r.status FROM players p
               JOIN tournament_invites ti ON ti.player_id=p.id AND ti.tournament_id=?
               LEFT JOIN rsvps r ON r.event_type='tournament' AND r.event_id=? AND r.player_id=p.id
               ORDER BY p.name""", (t["id"], t["id"])).fetchall()
        t_items.append({
            "t": t,
            "mine": notify.rsvp_status(con, "tournament", t["id"], player_id),
            "responses": responses,
        })
    return game_items, t_items


@app.route("/<team_id>")
def team_landing(team_id):
    team = get_con().execute("SELECT * FROM teams WHERE id=?", (team_id,)).fetchone()
    if not team:
        abort(404)
    roster = notify.rostered_players(get_con(), team_id)
    return render_template("pick_name.html", team=team, roster=roster)


@app.route("/<team_id>/<player_id>")
def player_rsvp_page(team_id, player_id):
    con = get_con()
    team = con.execute("SELECT * FROM teams WHERE id=?", (team_id,)).fetchone()
    if not team:
        abort(404)
    player = con.execute(
        """SELECT p.* FROM players p JOIN team_players tp ON tp.player_id=p.id
           WHERE tp.team_id=? AND p.id=?""", (team_id, player_id)).fetchone()
    if not player:
        abort(404)
    game_items, t_items = open_events_for_player(con, team, player_id)
    return render_template("rsvp.html", team=team, player=player,
                           game_items=game_items, t_items=t_items)


@app.route("/<team_id>/<player_id>/rsvp", methods=["POST"])
def player_rsvp_post(team_id, player_id):
    con = get_con()
    team = con.execute("SELECT * FROM teams WHERE id=?", (team_id,)).fetchone()
    if not team:
        abort(404)
    if not con.execute("SELECT 1 FROM team_players WHERE team_id=? AND player_id=?",
                       (team_id, player_id)).fetchone():
        abort(404)
    event_type = request.form["event_type"]
    event_id = int(request.form["event_id"])
    status = request.form["status"]
    if event_type not in ("game", "tournament") or status not in STATUSES:
        abort(400)
    now = datetime.now()
    game = team_row = None
    was_covered = True
    if event_type == "game":
        game = con.execute("SELECT * FROM games WHERE id=? AND team_id=?",
                           (event_id, team_id)).fetchone()
        if not game:
            abort(404)
        was_covered = not notify.game_shortfall(con, game, team)
    con.execute(
        """INSERT INTO rsvps (event_type, event_id, player_id, status, updated_at)
           VALUES (?,?,?,?,?)
           ON CONFLICT(event_type, event_id, player_id)
           DO UPDATE SET status=excluded.status, updated_at=excluded.updated_at""",
        (event_type, event_id, player_id, status, now.strftime(notify.DT_FMT)))
    con.commit()
    if game is not None:
        notify.emergency_check(con, game, team, was_covered, now)
    flash("Thanks! You're marked %s." % status.upper())
    return redirect(url_for("player_rsvp_page", team_id=team_id, player_id=player_id))


@app.route("/sub/<token>", methods=["GET", "POST"])
def sub_rsvp(token):
    con = get_con()
    inv = con.execute("SELECT * FROM sub_invites WHERE token=?", (token,)).fetchone()
    if not inv:
        abort(404)
    game = con.execute("SELECT * FROM games WHERE id=?", (inv["game_id"],)).fetchone()
    team = con.execute("SELECT * FROM teams WHERE id=?", (game["team_id"],)).fetchone()
    player = con.execute("SELECT * FROM players WHERE id=?", (inv["player_id"],)).fetchone()
    if request.method == "POST":
        status = request.form["status"]
        if status not in STATUSES:
            abort(400)
        con.execute("UPDATE sub_invites SET status=? WHERE id=?", (status, inv["id"]))
        con.commit()
        flash("Thanks! You're marked %s." % status.upper())
        return redirect(url_for("sub_rsvp", token=token))
    return render_template("sub_rsvp.html", inv=inv, game=game, team=team, player=player)


# ------------------------------------------------------------ scheduler thread

def scheduler_loop():
    con = db.connect()
    while True:
        try:
            notify.run_tick(con)
        except Exception as e:  # keep the loop alive
            print("scheduler error:", e)
        _stop.wait(60)
        if _stop.is_set():
            break


_stop = threading.Event()

db.init_db()

if os.environ.get("REC_SCHEDULER", "1") == "1":
    t = threading.Thread(target=scheduler_loop, daemon=True)
    t.start()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)),
            debug=False, use_reloader=False)
