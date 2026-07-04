# Handoff: Rec Sports Manager — "Game Day" Redesign

## Overview
Visual redesign of the Rec Sports Manager app (repo: `koramak/rec-sports-manager`, Flask + Jinja2 + single CSS file). Same structure and functionality — this is a restyle plus small layout improvements. The chosen direction is **"Game Day"**: bold navy + orange on cream, chunky white cards with 2px navy borders and hard offset shadows, tracked uppercase headings.

## About the Design Files
`Coach App Redesign.dc.html` in this bundle is a **design reference created in HTML** — a mockup showing intended look, not production code to copy. The task is to **recreate this design in the existing codebase**: primarily rewriting `static/style.css` and adjusting markup in `templates/*.html`. Keep Flask routes, Jinja logic, and all functionality unchanged.

The section badged **2a** (top of the file) is the approved design. Ignore sections 1a/1b/1c below it — those were early explorations.

## Fidelity
**High-fidelity.** Colors, typography, spacing, radii, and shadows are final. Recreate pixel-perfectly within the app's mobile-first single-column layout system.

## Design Tokens

Replace the `:root` variables in `static/style.css`:

- `--bg: #f7f3ea` (warm cream page background)
- `--card: #ffffff`
- `--ink: #1b2233` (navy — text, borders, dark buttons)
- `--muted: #6d7385` · secondary muted: `#8a8fa0` · body-secondary: `#4b5265`
- `--accent: #f2542d` (orange — alerts, SHORT states, primary CTAs, date eyebrows)
- `--ok: #2a9d5c` (green — covered states, IN)
- `--danger: #b3362f` (OUT pill)
- `--warn: #d9a400` border / `#9a6b00` text (TBD pill)
- Hairline dividers inside cards: `#e8e4d9`
- Neutral input/button border: `#c9cdd8` · dashed borders: `#b8b09d` (buttons) / `#c9c1ae` (linkbox)
- Card radius: `14px` · buttons `10–12px` · inputs `10px` · pills `999px`
- Card border: `2px solid #1b2233` · card shadow: `4px 4px 0 #1b2233` (hard offset, no blur)
- Small CTA shadow: `2px 2px 0 #1b2233`
- Phone-frame page padding: ~18px; card padding: 14–16px; vertical gap between cards: 14px

## Typography
- Font: **Barlow** (Google Fonts), weights 400/500/600/700/800. Load via `<link>` in `base.html`. Fallback: sans-serif. Mono (RSVP link box only): IBM Plex Mono or `ui-monospace`.
- **All-caps text must always have positive letter-spacing** — this was an explicit user requirement for legibility:
  - Page titles (e.g. MY TEAMS): 25px / 800 / uppercase / `letter-spacing: 0.04em`
  - Section headings (UPCOMING GAMES, ROSTER): 15px / 800 / uppercase / `0.08em`
  - Status strips & buttons: 12–14px / 800 / uppercase / `0.06–0.08em`
  - Date eyebrows (orange): 12px / 800 / uppercase / `0.1em`, color `#f2542d`
- Card titles (team names, matchups): 19px / 800, normal case, no tracking
- Body/meta: 13–14.5px / 500, `#4b5265` or `#6d7385`
- Big headcount numbers: 27–40px / 800 navy, with the `/10` denominator smaller (15–20px / 700, `#8a8fa0`)

## Screens (all in the 2a section of the HTML file)

### 1. Manager dashboard (`templates/dashboard.html`)
- Top bar: navy `#1b2233`, brand "RECMGR" 18px/800/uppercase/0.06em white; right-aligned nav (Subs, Alerts) 13px/700/uppercase; alert count badge orange `#f2542d` pill.
- Title "MY TEAMS".
- One card per team: title, next-game line ("Thu Jul 9 · 6:30 PM vs **Brewhouse Bombers**", opponent bold), headcount "9/10" big + "6M · 3F" small caps.
- **Status strip**: full-width colored footer bar inside the card (replaces the old inline "SHORT:" text). Orange `#f2542d` with "SHORT — NEED 1 MORE · 1F" + white "FIND SUBS" chip button (white bg, orange text) when short; green `#2a9d5c` "COVERED ✓" when fine.
- "+ NEW TEAM" full-width navy button, 15px padding, radius 12px.

### 2. Team page (`templates/team.html`)
- Navy top bar with back arrow + team name (uppercase, tracked).
- Meta line ("Coed softball · min 10 players · 4F") with small outlined SETTINGS / IMPORT buttons (2px navy border, uppercase 11.5px).
- Team RSVP link card: orange eyebrow "TEAM RSVP LINK", helper text, mono link in dashed cream box + navy COPY button.
- Upcoming games: compact cards — matchup + location left, headcount "9/10" right, status strip footer (orange Short / green Covered).
- "+ ADD GAME" / "+ ADD PLAYER": dashed-border ghost buttons (2px dashed `#b8b09d`).
- Tournaments: simple card, title + meta line.
- Roster: card containing list rows (name 15px/700 + #number muted, positions · contact 12px muted below; gender letter; underlined EDIT link), hairline `#e8e4d9` dividers, cream "+ 11 MORE" footer row.

### 3. Game detail (`templates/game.html`)
- Navy header: back arrow, orange date eyebrow "THU JUL 9 · 6:30 PM", "VS BREWHOUSE BOMBERS" below.
- Headcount card: 40px "9/10", "HEADCOUNT" label caps, "6M · 3F — need 10, 4F"; orange status strip "SHORT 1 PLAYER, 1F — PICK SUBS BELOW".
- Roster RSVPs: list rows with name + gender letter, status pill right: IN = solid green pill white text; OUT = white pill, 2px `#b3362f` border, red text; TBD = white pill, 2px `#d9a400` border, `#9a6b00` text. All pills 11px/800/tracked.
- Invite subs card: helper text, checkbox rows (20px squares, 2px border, checked = green fill + white ✓; name + muted meta "F · C, OF · Strong"), orange "SEND 1 SUB INVITE" button with 2px navy border + 2px hard shadow. Button label should reflect selection count.

### 4. Player RSVP page (`templates/rsvp.html`)
- Navy bar with team name. Greeting "HI DAVE 👋" 25px/800 + "Not you? Pick your name" link.
- One card per game: orange date eyebrow, "vs Brewhouse Bombers" 19px/800, 📍 location muted.
- RSVP buttons: 3-col grid, gap 8px, padding 15px 0, 15px/700–800/tracked, radius 10px. Unselected: white, 2px `#c9cdd8` border, navy text. Selected IN: green bg, white text, 2px navy border + 2px hard shadow. Selected OUT: same treatment in `#b3362f`; selected TBD: `#d9a400` bg, navy text.
- "▸ WHO'S IN" collapsed `<details>` with navy count pill.
- Tournament cards: same pattern, eyebrow "TOURNAMENT · SAT AUG 8".

### 5. Forms (`game_form.html`, `player_form.html`, `team_form.html`, etc.)
- Labels above inputs: 12px/800/uppercase/0.08em `#6d7385`; optional marker lighter.
- Inputs: white, 2px navy border (empty/inactive fields may use `#c9cdd8`), radius 10px, padding 12px, 15px/600 text.
- Date/time on one 2-col grid row.
- Submit: full-width orange button, 2px navy border, 2px hard shadow, uppercase tracked. Cancel: plain centered uppercase text link.

### 6. Desktop (base layout, min-width ~900px media query)
The app is mobile-first; add a desktop breakpoint:
- Nav becomes a horizontal bar: brand + Teams/Subs/Alerts/Outbox links (active link gets 2px orange underline), user email + Log out right.
- Dashboard: main content + 320px right sidebar for alerts. Team cards in a 2-col grid. Alert cards have a 6px orange left border, eyebrow (e.g. "72-HOUR CHECK"), message, timestamp.
- Team page: two columns — left: games, tournaments, RSVP link; right: roster as a table (grid `minmax(0,1fr) 28px 112px 44px`: player+meta / G / contact / edit), header row cream caps. Names truncate with ellipsis rather than wrap; number/positions go on a second smaller line.
- Content max-width ~1160px, 32px padding.

## Interactions & Behavior
- All existing behavior unchanged (forms POST, details/summary toggles, flash messages).
- Flash messages: restyle as white card, 2px navy border, green left accent for success.
- Hover: buttons darken slightly or translate 1px with shadow reduced to 3px 3px; links underline.
- Tap targets ≥ 44px on mobile (RSVP buttons and primary buttons already exceed this).
- The 🥎 and 👋 emoji are part of the app's voice — keep them.

## Assets
None — no images. Barlow from Google Fonts; emoji are native.

## Files
- `Coach App Redesign.dc.html` — the design reference. Open it in a browser; the **2a** section at top is the approved design (5 mobile screens + 2 desktop screens). Sections 1a/1b/1c are rejected explorations.
