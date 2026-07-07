import re
from datetime import datetime, timedelta

import pytest

import app as appmod
import notify
from conftest import add_player, make_team, make_tournament, signup

DT = notify.DT_FMT


def game_at(client, team_id, dt, opponent="Tigers", location="Field 3"):
    client.post("/team/%s/games/new" % team_id, data={
        "date": dt.strftime("%Y-%m-%d"), "time": dt.strftime("%H:%M"),
        "location": location, "opponent": opponent, "home_away": "home"})


def last_game_id(con):
    return con.execute("SELECT id FROM games ORDER BY id DESC").fetchone()["id"]


# ------------------------------------------------------------ units

@pytest.mark.parametrize("raw,expected", [
    ("5555550101", "(555) 555-0101"),
    ("1-555-555-0101", "(555) 555-0101"),
    ("(555) 555-0101", "(555) 555-0101"),
    ("", ""),
    ("12345", None),
    ("555555010199", None),
])
def test_normalize_phone(raw, expected):
    assert appmod.normalize_phone(raw) == expected


def test_wildcard_expansion_leaves_unknowns():
    player = {"id": "p1", "name": "Alice Ames"}
    team = {"id": "t1", "name": "Dingers"}
    out = notify.expand_wildcards("hi {first} ({name}) of {team} {nope}",
                                  player, team)
    assert out == "hi Alice (Alice Ames) of Dingers {nope}"


# ------------------------------------------------------------ auth

def test_signup_login_logout(client):
    signup(client)
    client.get("/logout")
    r = client.post("/login", data={"email": "z@x.com", "password": "wrong"},
                    follow_redirects=True)
    assert b"Invalid email or password" in r.data
    r = client.post("/login", data={"email": "z@x.com", "password": "pw"})
    assert r.headers["Location"].endswith("/dashboard")


def test_login_throttled_after_repeated_failures(client):
    signup(client)
    client.get("/logout")
    for _ in range(10):
        client.post("/login", data={"email": "z@x.com", "password": "wrong"})
    r = client.post("/login", data={"email": "z@x.com", "password": "pw"},
                    follow_redirects=True)
    assert b"Too many attempts" in r.data


def test_stranger_cannot_manage(client, con):
    signup(client)
    team_id = make_team(client)
    p = add_player(client, team_id, "Alice Ames", "F", phone="5555550101")
    tid = make_tournament(client, team_id)
    client.get("/logout")
    signup(client, email="eve@x.com", name="Eve")
    assert client.post("/tournament/%d/remove/%s" % (tid, p["id"])).status_code == 403
    assert client.get("/team/%s/message" % team_id).status_code == 403
    assert client.post("/team/%s/roster/remove/%s" % (team_id, p["id"])).status_code == 403


# ------------------------------------------------------------ roster removal

def test_roster_remove_converts_player_to_sub(client, con):
    signup(client)
    team_id = make_team(client)
    p = add_player(client, team_id, "Alice Ames", "F", phone="5555550101")
    r = client.post("/team/%s/roster/remove/%s" % (team_id, p["id"]),
                    follow_redirects=True)
    assert b"sub pool" in r.data
    p2 = con.execute("SELECT * FROM players WHERE id=?", (p["id"],)).fetchone()
    assert p2 is not None and p2["is_sub"] == 1
    assert con.execute("SELECT 1 FROM team_players WHERE player_id=?",
                       (p["id"],)).fetchone() is None


def test_roster_remove_keeps_player_flag_when_on_another_team(client, con):
    signup(client)
    t1 = make_team(client, name="Dingers")
    t2 = make_team(client, name="Mashers")
    p = add_player(client, t1, "Alice Ames", "F", phone="5555550101")
    con.execute("INSERT INTO team_players (team_id, player_id) VALUES (?,?)",
                (t2, p["id"]))
    con.commit()
    client.post("/team/%s/roster/remove/%s" % (t1, p["id"]))
    p2 = con.execute("SELECT * FROM players WHERE id=?", (p["id"],)).fetchone()
    assert p2["is_sub"] == 0  # still rostered on Mashers


def test_tournament_remove_player_converts_to_sub(client, con):
    signup(client)
    team_id = make_team(client)
    p = add_player(client, team_id, "Alice Ames", "F", phone="5555550101")
    tid = make_tournament(client, team_id)
    client.post("/tournament/%d/invite" % tid, data={"player_id": [p["id"]]})
    client.post("/%s/%s/rsvp" % (team_id, p["id"]),
                data={"event_type": "tournament", "event_id": str(tid),
                      "status": "in"})
    client.post("/tournament/%d/remove/%s" % (tid, p["id"]))
    assert con.execute("SELECT 1 FROM tournament_invites WHERE tournament_id=?"
                       " AND player_id=?", (tid, p["id"])).fetchone() is None
    assert con.execute("SELECT 1 FROM rsvps WHERE event_type='tournament' AND"
                       " event_id=? AND player_id=?", (tid, p["id"])).fetchone() is None
    p2 = con.execute("SELECT * FROM players WHERE id=?", (p["id"],)).fetchone()
    assert p2 is not None and p2["is_sub"] == 1


def test_tournament_remove_sub_deletes_invite_only(client, con):
    signup(client)
    team_id = make_team(client)
    client.post("/players/new", data={"name": "Bob Beck", "gender": "M",
                                      "email": "bob@x.com"})
    bob = con.execute("SELECT * FROM players WHERE name='Bob Beck'").fetchone()
    tid = make_tournament(client, team_id)
    client.post("/tournament/%d/invite" % tid, data={"player_id": [bob["id"]]})
    client.post("/tournament/%d/remove/%s" % (tid, bob["id"]))
    assert con.execute("SELECT 1 FROM tournament_invites WHERE tournament_id=?"
                       " AND player_id=?", (tid, bob["id"])).fetchone() is None
    bob2 = con.execute("SELECT * FROM players WHERE id=?", (bob["id"],)).fetchone()
    assert bob2 is not None and bob2["is_sub"] == 1


# ------------------------------------------------------------ messaging

def test_message_team_expands_wildcards(client, con):
    signup(client)
    team_id = make_team(client)
    p = add_player(client, team_id, "Dana Dill", "F", phone="5555550104")
    game_at(client, team_id, datetime.now() + timedelta(days=30))
    r = client.post("/team/%s/message" % team_id,
                    data={"body": "Hey {first}, {team} plays {game}: {link}"},
                    follow_redirects=True)
    assert b"Message sent to 1 player(s)." in r.data
    note = con.execute("SELECT * FROM notifications ORDER BY id DESC").fetchone()
    assert note["body"].startswith("Hey Dana, Dingers plays vs Tigers on ")
    assert "/%s/%s" % (team_id, p["id"]) in note["body"]
    assert note["channel"] == "sms"


def test_message_tournament_only_in(client, con):
    signup(client)
    team_id = make_team(client)
    dana = add_player(client, team_id, "Dana Dill", "F", phone="5555550104")
    carl = add_player(client, team_id, "Carl Cole", "M", phone="5555550103")
    tid = make_tournament(client, team_id)
    client.post("/tournament/%d/invite" % tid,
                data={"player_id": [dana["id"], carl["id"]]})
    client.post("/%s/%s/rsvp" % (team_id, dana["id"]),
                data={"event_type": "tournament", "event_id": str(tid),
                      "status": "in"})
    before = con.execute("SELECT COUNT(*) c FROM notifications").fetchone()["c"]
    r = client.post("/team/%s/message?tournament=%d" % (team_id, tid),
                    data={"body": "{first}: {tournament} {date} {cost}",
                          "only_in": "on"}, follow_redirects=True)
    assert b"Message sent to 1 player(s)." in r.data
    rows = con.execute("SELECT * FROM notifications ORDER BY id").fetchall()[before:]
    assert len(rows) == 1 and rows[0]["recipient"] == "Dana Dill"
    assert rows[0]["body"] == "Dana: Summer Slam Sat, Aug 8 ~$25/person"


def test_message_skips_contactless_players(client, con):
    signup(client)
    team_id = make_team(client)
    add_player(client, team_id, "Dana Dill", "F", phone="5555550104")
    con.execute("INSERT INTO players (id, manager_id, name, gender, is_sub)"
                " VALUES ('ghost1', 1, 'Ghost', 'M', 0)")
    con.execute("INSERT INTO team_players (team_id, player_id) VALUES (?, 'ghost1')",
                (team_id,))
    con.commit()
    r = client.post("/team/%s/message" % team_id, data={"body": "hi {first}"},
                    follow_redirects=True)
    assert b"Message sent to 1 player(s). Skipped 1" in r.data


# ------------------------------------------------------------ rsvp + reminders

def test_game_rsvp_counts(client, con):
    signup(client)
    team_id = make_team(client, min_players=2, min_male=0, min_female=0)
    a = add_player(client, team_id, "Alice Ames", "F", phone="5555550101")
    game_at(client, team_id, datetime.now() + timedelta(days=5))
    gid = last_game_id(con)
    client.post("/%s/%s/rsvp" % (team_id, a["id"]),
                data={"event_type": "game", "event_id": str(gid), "status": "in"})
    game = con.execute("SELECT * FROM games WHERE id=?", (gid,)).fetchone()
    counts = notify.game_counts(con, game)
    assert counts == {"male": 0, "female": 1, "total": 1}


def test_tick_opens_rsvps_and_reminds_once_per_day(client, con):
    signup(client)
    team_id = make_team(client)
    add_player(client, team_id, "Alice Ames", "F", phone="5555550101")
    # 5 days out: inside the 7-day RSVP window, outside the 72h alert window
    game_at(client, team_id, datetime.now() + timedelta(days=5))
    notify.run_tick(con)
    n1 = con.execute("SELECT COUNT(*) c FROM notifications").fetchone()["c"]
    assert n1 == 1  # the RSVP request went out
    notify.run_tick(con)
    n2 = con.execute("SELECT COUNT(*) c FROM notifications").fetchone()["c"]
    assert n2 == n1  # same-day tick doesn't double-message


def test_tick_72h_short_alert_fires_once(client, con):
    signup(client)
    team_id = make_team(client)  # min 10 players, nobody in
    add_player(client, team_id, "Alice Ames", "F", phone="5555550101")
    game_at(client, team_id, datetime.now() + timedelta(days=2))
    notify.run_tick(con)
    alerts = con.execute("SELECT * FROM alerts WHERE kind='short72'").fetchall()
    assert len(alerts) == 1
    notify.run_tick(con)
    assert len(con.execute("SELECT * FROM alerts WHERE kind='short72'").fetchall()) == 1


def test_emergency_alert_on_dropout(client, con):
    signup(client)
    team_id = make_team(client, min_players=1, min_male=0, min_female=0)
    a = add_player(client, team_id, "Alice Ames", "F", phone="5555550101")
    game_at(client, team_id, datetime.now() + timedelta(days=2))
    gid = last_game_id(con)
    rsvp = {"event_type": "game", "event_id": str(gid)}
    client.post("/%s/%s/rsvp" % (team_id, a["id"]), data=dict(rsvp, status="in"))
    assert con.execute("SELECT 1 FROM alerts WHERE kind='emergency'").fetchone() is None
    client.post("/%s/%s/rsvp" % (team_id, a["id"]), data=dict(rsvp, status="out"))
    assert con.execute("SELECT 1 FROM alerts WHERE kind='emergency'").fetchone() is not None


# ------------------------------------------------------------ csrf

def test_csrf_blocks_tokenless_posts(client):
    appmod.app.config["CSRF_ENABLED"] = True
    try:
        r = client.post("/signup", data={"name": "Z", "email": "z@x.com",
                                         "password": "pw"})
        assert r.status_code == 400
        page = client.get("/signup").data.decode()
        token = re.search(r'name="_csrf" value="([0-9a-f]+)"', page).group(1)
        r = client.post("/signup", data={"name": "Z", "email": "z@x.com",
                                         "password": "pw", "_csrf": token})
        assert r.status_code == 302
    finally:
        appmod.app.config["CSRF_ENABLED"] = False


def test_every_post_form_carries_csrf_token(client, con):
    signup(client)
    team_id = make_team(client)
    p = add_player(client, team_id, "Alice Ames", "F", phone="5555550101")
    tid = make_tournament(client, team_id)
    client.post("/tournament/%d/invite" % tid, data={"player_id": [p["id"]]})
    game_at(client, team_id, datetime.now() + timedelta(days=5))
    gid = last_game_id(con)
    client.post("/players/new", data={"name": "Bob Beck", "gender": "M",
                                      "email": "bob@x.com"})
    bob = con.execute("SELECT * FROM players WHERE name='Bob Beck'").fetchone()
    client.post("/game/%d/invite-sub" % gid, data={"player_id": [bob["id"]]})
    token = con.execute("SELECT token FROM sub_invites").fetchone()["token"]

    pages = ["/login", "/signup", "/dashboard",
             "/team/%s/manage" % team_id, "/team/%s/settings" % team_id,
             "/team/%s/import" % team_id, "/team/%s/message" % team_id,
             "/team/%s/message?tournament=%d" % (team_id, tid),
             "/team/%s/players/new" % team_id,
             "/player/%s/edit" % p["id"],
             "/game/%d" % gid, "/game/%d/edit" % gid,
             "/tournament/%d" % tid, "/tournament/%d/edit" % tid,
             "/%s/%s" % (team_id, p["id"]), "/sub/%s" % token]
    for page in pages:
        html = client.get(page).data.decode()
        forms = html.count('<form method="post"')
        tokens = html.count('name="_csrf"')
        assert forms == tokens, "%s: %d post forms but %d csrf fields" % (
            page, forms, tokens)
