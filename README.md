# Rec Sports Manager

Lightweight availability tracker for recreational sports teams (PRD 1.0).
Managers schedule games and tournaments; players RSVP through no-login links;
the system chases stragglers automatically and alerts managers when a game is
short-handed (including gender minimums), prompting manual sub selection.

## Try it on the web

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/koramak/rec-sports-manager)

One click (free tier, sign in with GitHub): Render reads `render.yaml`, seeds
demo data on each deploy, and gives you a public `https://…onrender.com` URL.

## Stack

Python 3.9+ · Flask · SQLite. No other dependencies.

```bash
pip install flask
python3 seed.py    # optional: demo data
python3 app.py     # serves on $PORT (default 5000)
```

Demo logins after seeding — manager: `zane@example.com` / `demo`,
system admin: `admin@rec.local` / `admin`. Demo team RSVP link: `/demo`.

## How it maps to the PRD

- **Roles** — system admin (sees everything via `/admin`), managers (own teams,
  rosters, sub pools; isolated from each other), co-managers (added by email,
  identical team powers), rostered players and subs (no accounts at all).
- **Player links** — `domain.com/<team_id>/<player_id>` for individuals;
  `domain.com/<team_id>` shows a "pick your name" dropdown (`Dave M.` format).
  The RSVP page shows game details and everyone's current status.
- **Player model** — name, gender and one contact method required; optional
  number, positions (P/C/1B/2B/3B/SS/OF), skill, notes. Bulk import via the
  mobile Contact Picker API with CSV upload/paste as the fallback.
- **Season workflow** — RSVP requests open the morning after the previous game
  or 7 days out, whichever is first. Statuses are In / Out / T.B.D. Daily
  reminders go to anyone not firmly in or out. 72 hours before a short game the
  manager gets an alert and picks subs, each of whom receives a one-off
  personal link (`/sub/<token>`). Late status changes that drop the team below
  minimums trigger immediate emergency alerts.
- **Tournaments** — single-day events with date, estimated location, host,
  division (Coed/Mens) and estimated cost. Rolling invites; automated
  reminders for unconfirmed players start exactly 3 weeks out.
- **Notification consolidation** — outgoing messages are batched per contact
  (phone/email), so a player on multiple teams gets one message per pass.
  Delivery is a gateway stub: everything lands in the Outbox screen (swap in
  Twilio/SMTP in `notify.Collector.flush` for real sending).
- **Mobile-first** — single-column layout, large tap targets, no exports.

## Layout

- `app.py` — routes (manager dashboard, player RSVP pages, admin) + background
  scheduler thread (runs every 60 s; also triggerable from the dashboard)
- `notify.py` — notification engine: request/reminder/alert rules, batching
- `db.py` — schema and helpers
- `seed.py` — demo data
- `templates/`, `static/` — mobile-first UI
