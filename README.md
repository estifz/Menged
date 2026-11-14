# Menged backend

One Python backend behind the **Menged Telegram bot** (hackathon demo) and the
**mobile app** (later). It tells public-transport riders in Addis Ababa what they
are passing and when to get off, in English or Amharic, using only free
OpenStreetMap services.

```
Telegram ──▶ adapters/telegram ─┐                      ┌─▶ Nominatim / Photon (names ⇄ points)
                                ├─▶ engine/trips ──────┼─▶ OpenRouteService / OSRM (route)
Mobile app ─▶ adapters/api  ────┘    engine/notifications└─▶ Overpass (places along the route)
                                      │
                                      └─▶ PostgreSQL (Neon)  ·  APScheduler (30 s timer)
```

Every rule lives in `app/engine/`; the adapters only translate messages in and out.

## Run it on a laptop (demo setup)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env            # fill in DATABASE_URL, TELEGRAM_BOT_TOKEN, ORS_API_KEY
.venv/bin/alembic upgrade head  # creates the 5 tables
.venv/bin/uvicorn app.main:app --port 8000
```

The bot starts in **polling** mode (no HTTPS needed). Optional: `sudo apt install ffmpeg`
so voice notes are sent as OGG/Opus instead of MP3.

### Demo data (already recorded, re-run to refresh)

```bash
.venv/bin/python -m scripts.build_gazetteer                       # offline Addis place list (3,400+ places)
.venv/bin/python -m scripts.record_demo "Merkato" "Bole Medhanialem"  # route + places + streets for /simulate
```

## Using the bot

| You | The bot |
|---|---|
| `/start` | Asks for language (English / አማርኛ); voice notes are on by default |
| Type a place, e.g. *Bole Medhanialem* or *ቦሌ መድኃኔዓለም* | Shows up to 3 matches as buttons |
| Pick one | Asks you to share **live location** (📎 → Location → Share My Live Location) |
| Share live location | Plans the route, pins a **trip card** that updates silently, and starts talking only when a rule fires |
| 📍 Where am I? · ⏱ Time left · 🍽 Nearby restaurants · ⏹ Stop trip | One-tap answers (also voiced) |
| `/settings` | Language, voice on/off, alert level (quiet / normal / chatty) |
| `/simulate [speedup]` | Replays the recorded demo trip, indoors, no GPS (default 10× real time) |

### What it says, and when

| Rule | Fires when | Priority |
|---|---|---|
| Passing a place | within 100 m of a landmark along the route (once each) | normal |
| New street | the street name changes (once each) | normal |
| Time left | estimated time crosses 15 / 10 minutes | normal |
| Food nearby | ≥ 2 cafés/restaurants within 500 m ahead, at most every 10 min, with **Show / Not now / Don't ask** buttons | normal, silent |
| Still here | nothing said for 3 min while moving (chatty only) | low |
| Getting close 🔔 | 500 m or 5 min from the destination | high |
| Next 🔔 | 150 m or 1 min | high |
| Arrived 🔔 | within 50 m (two points in a row) | high |
| Location lost 🔔 | no location for 2 min; the trip ends after 10 min | high |

Limits: ≥ 45 s between messages, ≤ 4 per 5 minutes; high priority skips both.
Time left is recalculated from the rider's real speed. Raw location points are
deleted 24 h after a trip ends. The essential thresholds are listed in `.env`
with a comment each (restart the server after changing one); every other
setting lives in `app/config.py`.

## REST API for the app (`/v1`)

Auth: `Authorization: Bearer <token>` from `POST /v1/devices`. The app speaks the
messages itself with on-device TTS; the server sends text plus a message `type`
and `params` for native rendering.

| Method & path | Purpose |
|---|---|
| `POST /v1/devices` | Register the install → token |
| `GET/PUT /v1/me/settings` | language, voice_on, alert_level |
| `GET /v1/places/search?q=` | Destination suggestions |
| `POST /v1/trips` | `{destination:{lat,lon,name}` or `destination_query, start:{lat,lon}}` |
| `GET /v1/trips/{id}` | Status, distance and time left |
| `POST /v1/trips/{id}/locations` | `{points:[{lat,lon,accuracy_m,recorded_at}]}` → new messages |
| `GET /v1/trips/{id}/messages?since=<id>` | Poll for messages (FCM push is optional) |
| `POST /v1/trips/{id}/end` | End the trip |
| `GET /v1/places/nearby?lat=&lon=` | Up to 5 restaurants/cafés within 500 m |
| `GET /v1/where?lat=&lon=` | "Where am I?" text |

Interactive docs: `http://localhost:8000/docs`.

## Tests

```bash
.venv/bin/pytest -q
```

Covers geometry, the Amharic normaliser and offline search, every rule and the
anti-overload limits on a synthetic ride, stale/timeout handling, the privacy
purge, the REST API, and a full offline replay of the demo trip.

## Deploying on Render (webhook mode)

`render.yaml` is a Render Blueprint: push the repo to GitHub, then in Render
choose **New + → Blueprint**, pick the repo, fill in the four secrets
(`DATABASE_URL`, `DATABASE_URL_POOLED`, `TELEGRAM_BOT_TOKEN`, `ORS_API_KEY`)
and apply. The Dockerfile installs ffmpeg and runs migrations on start; the bot
registers its webhook from Render's `RENDER_EXTERNAL_URL`.

Render's free plan sleeps after 15 idle minutes, which stops the 30-second
timer (stale-location and timeout alerts). Keep it awake with a free uptime
monitor (e.g. UptimeRobot) that requests `/health` every 5 minutes.

Don't run the bot locally in polling mode while it is deployed: polling deletes
the webhook. If that happens, restart the Render service to re-register it.

## Layout

```
app/config.py        settings + every tunable threshold
app/models.py        users, trips, location_points, trip_places, notifications
app/geo.py           distances, route projection, GPS smoothing
app/services/        nominatim, photon, routing (ORS→OSRM), overpass, gazetteer, tts, push
app/engine/trips.py  the only code that changes trips.status
app/engine/notifications.py  rules, levels, anti-overload limits
app/engine/templates.py      all texts, en + am  (Amharic needs a native-speaker review)
app/adapters/telegram/       bot, handlers, keyboards, channel
app/adapters/api/            REST routes and schemas
app/demo/            demo_trip.json + /simulate replay
scripts/             build_gazetteer.py, record_demo.py
```
