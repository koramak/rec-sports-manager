"""Test fixtures. Each test gets a throwaway SQLite DB and a logged-out client."""
import os
import sys
import tempfile

os.environ["REC_SCHEDULER"] = "0"
os.environ.setdefault("REC_DB", os.path.join(tempfile.mkdtemp(), "import.db"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import db
import app as appmod


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    db.init_db()
    appmod.app.config.update(TESTING=True, CSRF_ENABLED=False)
    appmod._login_fails.clear()
    with appmod.app.test_client() as c:
        yield c


@pytest.fixture
def con(client):
    con = db.connect()
    yield con
    con.close()


def signup(client, email="z@x.com", name="Zane", password="pw"):
    return client.post("/signup", data={
        "name": name, "email": email, "password": password})


def make_team(client, name="Dingers", **kw):
    data = {"name": name, "sport": "Softball", "min_players": "10",
            "min_male": "7", "min_female": "3", "team_type": "tournament"}
    data.update({k: str(v) for k, v in kw.items()})
    r = client.post("/teams/new", data=data)
    return r.headers["Location"].split("/")[2]


def add_player(client, team_id, name, gender="M", phone="", email=""):
    client.post("/team/%s/players/new" % team_id, data={
        "name": name, "gender": gender, "phone": phone, "email": email})
    con = db.connect()
    p = con.execute("SELECT * FROM players WHERE name=?", (name,)).fetchone()
    con.close()
    return p


def make_tournament(client, team_id, name="Summer Slam", date="2099-08-08", **kw):
    data = {"name": name, "date": date, "location": "Big Park",
            "division": "Coed", "cost": "25"}
    data.update({k: str(v) for k, v in kw.items()})
    r = client.post("/team/%s/tournaments/new" % team_id, data=data)
    return int(r.headers["Location"].rstrip("/").split("/")[-1])
