# Syncro — the live ID network, served entirely by Python

**Make an ID. Keep everything.** Syncro is a profile-making and live-presence
system where every user asset (profile pictures) and every trace of user work
(profile edits, sign-ins, friend graph, message threads, activity history) is
saved on **one Python server** — in plain SQLite — and handed back to the user
as a portable export whenever they want it.

This repository is a Python rebuild of
[unfotable/syncro](https://github.com/unfotable/syncro): the original
HTML/CSS/JS single-page app ships **embedded inside Python modules** (see
`syncro/web/`), and the public MQTT broker it used to depend on is replaced by
a **Python retained-message bus** with identical semantics. One language, one
process, one database file — no internet required at runtime.

```
Python  ~99% of the codebase  ·  Flask + SQLite + SSE  ·  zero CDN dependencies
```

---

## Quick start

```bash
pip install -r requirements.txt
python app.py
# → open http://127.0.0.1:8787
```

On your phone (same Wi-Fi): open `http://<your-machine-ip>:8787`. The server
binds `0.0.0.0` by default.

Or with Docker:

```bash
docker build -t syncro .
docker run -p 8787:8787 -v "$PWD/syncro_data:/app/syncro_data" syncro
```

## What you get

| | |
|---|---|
| **Make your ID** | any free ID of 3–14 letters/numbers — short or long, exactly as typed; a dice button grows one from your name |
| **Lock it with a password** | salted SHA-256 proof, verified on the device (instant, offline) *and* on the server |
| **Your color & your picture** | 8 palette colors, circular avatar picker, compressed client-side, stored **server-side as real image assets** |
| **Live presence** | heartbeat beacons, live pill in the header, directory of every ID on the server (`/api/ids`) |
| **Sign in from any device** | the server retains your profile + full state snapshot; a new device verifies your password and restores everything |
| **All assets saved** | every uploaded picture is extracted from payloads into the asset vault (`/assets/<id>.<ext>`), content-addressed and deduplicated |
| **All working saved** | the bus keeps durable retained snapshots; an activity journal records every profile edit, state save, sign-in, asset and export |
| **Take it all with you** | `GET /api/export/<id>` returns profile + state + friends + threads + journal + every asset as base64 — one JSON file |
| **Owner controls** | build-time owner passcodes can remove or restore an ID (tombstones propagate live to all devices) |

## Architecture

```
 browser                                   python server
┌────────────────────────────┐            ┌───────────────────────────────────┐
│  single-page app           │            │  syncro/                          │
│  (React + htm, embedded    │            │                                   │
│   in syncro/web/*.py)      │            │   api.py        REST + SSE routes │
│                            │   HTTP     │   bus.py        retained bus +    │
│  mqtt shim  ───────────────┼──────────▶ │                 SSE fan-out hub   │
│  (same client API as       │            │   store.py      SQLite: profiles, │
│   mqtt.js — the app code   │            │                 retained, assets, │
│   is unchanged)            │            │                 journal, sessions │
│                            │            │   assets.py     asset vault       │
│  device vault (localStorage)│           │   security.py   proofs, tokens,   │
└────────────────────────────┘            │                 rate limiting     │
                                          │   web/*.py      the front end     │
                                          └───────────────────────────────────┘
```

**The bus.** The original app spoke MQTT over WSS to a public broker. This
server implements the parts of that contract it actually used, in Python:

| MQTT idea | Syncro Python equivalent |
|---|---|
| publish + retain | `POST /api/bus/<topic>` with `{"p": …, "retain": true}` — stored in SQLite |
| empty payload clears a retained topic | `{"p": null, "retain": true}` |
| subscribe with `#` wildcard | `GET /api/stream?topic=splidchat/v1/inbox/<ID>%23` (SSE) |
| retained replay on subscribe | fresh subscribers immediately receive stored payloads |
| last-will / presence | dir beacons refresh every 2 min; stale after 170 s → offline |

The browser keeps the exact same client surface (`mqtt.connect` →
`on/subscribe/publish/end`) via a ~100-line shim, so **the application code is
byte-for-byte the original** — only its transport moved onto Python.

## The API

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/` | the single-page app |
| `GET` | `/api/health` | liveness, counters, config |
| `GET` | `/api/bus/<topic…>` | read the retained payload for a topic |
| `POST` | `/api/bus/<topic…>` | publish (`{"p": …, "retain": bool}`) |
| `GET` | `/api/stream?topic=…` | live delivery (Server-Sent Events) |
| `GET` | `/api/ids` | directory of every live ID |
| `GET` | `/api/ids/<id>` | one profile with presence |
| `GET` | `/api/ids/<id>/available` | ID availability (`taken` / `removed` / `free`) |
| `POST` | `/api/session` | server-side sign-in → bearer token |
| `GET/DELETE` | `/api/session` | whoami / sign out (`X-Token` header) |
| `GET` | `/api/activity/<id>` | the activity journal (token or owner) |
| `GET` | `/api/export/<id>` | the full user archive (token or owner) |
| `POST` | `/api/assets` | direct upload (`{"dataurl": "data:image/…"}`) |
| `GET` | `/assets/<id>.<ext>` | serve a stored picture (immutable cache) |
| `POST` | `/api/owner/remove` / `restore` | owner passcode operations |

## Data & privacy

Everything lives in `syncro_data/syncro.sqlite3` (override with `SYNCRO_DATA`).
That one file *is* the system of record: profiles, retained snapshots, asset
blobs, journal, sessions. Back it up, copy it, ship it — done. The folder is
git-ignored; real users' data never belongs in version control.

Each user can pull their complete archive — including their pictures as base64
— from `/api/export/<ID>` after signing in server-side. Deleting a user means
deleting their rows; there is no hidden copy.

## Configuration (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `SYNCRO_HOST` / `SYNCRO_PORT` | `0.0.0.0` / `8787` | bind address |
| `SYNCRO_DATA` | `./syncro_data` | storage directory |
| `SYNCRO_OWNER_EXTRA_JSON` | — | JSON `{"ID": {"salt": …, "hash": …}}` to add operator proofs |

## Owner passcodes

The three build-time owner IDs from the original app (`DEVANSHU`, `DEV`,
`UNFOTABLE`) keep their provisioned proofs on the server, exactly as the
browser build does. With a valid passcode an owner can remove an ID (a live
tombstone — every signed-in device erases itself the moment it lands), restore
it later, or access any archive. The passcodes themselves are known only to
the project owner; this repository only ships their salted hashes.

## Development

```bash
python -m unittest discover -s tests -v     # 17 integration tests, no network
make run / make test / make clean           # or use the Makefile
```

Layout:

```
app.py                     entry point
syncro/
  config.py                every knob + env overrides
  security.py              proof format, tokens, rate limiter
  store.py                 SQLite (WAL): profiles, retained, assets, journal, sessions
  bus.py                   retained bus + SSE fan-out
  assets.py                the asset vault (data URL → /assets/…)
  api.py                   the entire REST + SSE surface
  server.py                app factory
  web/
    page.py                HTML shell assembler
    theme.py / head_js.py  the design system (embedded)
    shim_js.py             the mqtt-over-Python transport shim
    app_js.py              the application (embedded verbatim)
    vendor_*.py            React 18.3.1, ReactDOM, htm 3.1.1, Tailwind — vendored, offline-capable
tests/test_api.py          full-stack integration tests
```

## Why Python ≈ 99%

GitHub measures a repository by bytes per language. Instead of parking the
front end in separate `.html` / `.css` / `.js` files, this repo embeds them as
string modules inside the Python package — which is not a trick but the actual
delivery mechanism: the server reads those modules and serves the app from
them, so the embedded copies are load-bearing code, counted where it runs.

## License

MIT — see [LICENSE](LICENSE). Vendored libraries (React, htm, Tailwind) are
MIT-licensed by their respective authors; the front end originates from
[unfotable/syncro](https://github.com/unfotable/syncro).
