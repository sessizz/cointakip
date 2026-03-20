# CLAUDE.md — Cointakip Codebase Guide

## Overview

**Cointakip** is a Flask-based web application for analyzing cryptocurrency trading positions against real Binance market data. Users enter a trading position (coin, entry price, targets, stop-loss, leverage, open date) and the app fetches historical 1-minute candlestick data from Binance to evaluate the outcome and render a price chart.

The UI language is **Turkish**.

---

## Tech Stack

| Layer      | Technology                                 |
|------------|--------------------------------------------|
| Backend    | Python 3, Flask 2.3+                       |
| Server     | Gunicorn (production), Flask dev (local)   |
| Frontend   | HTML5, Jinja2, Bootstrap 5.3.2, Vanilla JS |
| Charts     | Matplotlib (rendered server-side as PNG)   |
| Data       | JSON files (no database)                   |
| External   | Binance REST API (`api.binance.com`)        |
| Timezone   | Europe/Istanbul (pytz)                     |

---

## Repository Structure

```
cointakip/
├── web_app.py              # Main Flask application (all backend logic)
├── templates/
│   └── index.html          # Single-page Jinja2 template
├── requirements.txt        # Python dependencies
├── Procfile.txt            # Heroku/Gunicorn: "web: gunicorn web_app:app"
├── web_settings.json       # Persisted form field defaults (auto-updated on submit)
├── saved_positions.json    # User-saved trading positions (list of JSON objects)
└── settings.json           # UI window geometry preferences
```

---

## Running the Application

```bash
# Install dependencies
pip install -r requirements.txt

# Development server (debug mode, port 5000)
python web_app.py

# Production server
gunicorn web_app:app
```

No environment variables or `.env` files are required. All config is either hardcoded or in JSON files.

---

## Application Architecture

### Entry Points

- `web_app.py` — contains everything: Flask app init, helper functions, and all route handlers.
- No blueprints, no separate modules. All logic lives in one file.

### Routes

| Method       | Path                          | Purpose                                      |
|--------------|-------------------------------|----------------------------------------------|
| GET          | `/`                           | Load form with saved defaults                |
| GET          | `/?load=<id>`                 | Pre-fill form from a saved position          |
| POST         | `/` (`action=check`)          | Fetch Binance data, evaluate, render chart   |
| POST         | `/` (`action=save`)           | Save current position to JSON                |
| POST         | `/delete_position/<id>`       | Delete a saved position by ID, redirect home |

### Key Functions in `web_app.py`

| Function                   | Purpose                                                                    |
|----------------------------|----------------------------------------------------------------------------|
| `get_binance_klines()`     | Fetches 1m OHLCV candles from Binance API (max 1000 per request)           |
| `determine_position_type()`| Returns `'long'` or `'short'` based on entry vs. target1                  |
| `evaluate_position()`      | Iterates klines to find when target1/target2/stop was hit first            |
| `calculate_profit_loss()`  | Computes leveraged P/L % for a given outcome                               |
| `render_chart()`           | Generates a matplotlib chart; returns base64-encoded PNG data URL          |
| `load_settings()`          | Reads `web_settings.json` for form defaults                                |
| `save_settings()`          | Writes current form values to `web_settings.json`                          |
| `load_saved_positions()`   | Reads `saved_positions.json` as a list                                     |
| `save_positions()`         | Overwrites `saved_positions.json` with updated list                        |
| `add_position()`           | Appends a new position with `id` and `saved_at` fields                     |
| `delete_position()`        | Filters out position by `id` and saves                                     |

---

## Data Persistence

No database. Two JSON files serve as the data store:

### `web_settings.json`
Stores the last-submitted form values so they are pre-filled on next visit.

```json
{
  "coin": "AVAXUSDT",
  "entry_price": "31.05",
  "target_price1": "30.24",
  "target_price2": "31.06",
  "stop_price": "31.46",
  "leverage": "20",
  "open_date": "2025-01-15 14:30"
}
```

### `saved_positions.json`
A JSON array of saved position objects.

```json
[
  {
    "coin": "BTCUSDT",
    "entry_price": 95000.0,
    "target_price1": 98000.0,
    "target_price2": 100000.0,
    "stop_price": 93000.0,
    "leverage": 10.0,
    "open_date": "2025-01-10 09:00",
    "name": "BTCUSDT - 01/10 09:00",
    "saved_at": "2025-01-10 09:05:22",
    "id": 1
  }
]
```

**Important:** The `id` field is assigned as `len(positions) + 1` at save time. If positions are deleted and new ones added, IDs are not guaranteed to be unique. Be careful with this when modifying position management logic.

---

## Position Evaluation Logic

1. **Position type** is determined by comparing `entry_price` to `target1`:
   - `target1 > entry_price` → `long`
   - `target1 < entry_price` → `short`

2. **Klines are scanned sequentially** (oldest to newest). For each 1-minute candle:
   - Long: target hit if `high >= target`, stop hit if `low <= stop`
   - Short: target hit if `low <= target`, stop hit if `high >= stop`

3. **Precedence rule:** If stop was hit at or before the earliest target hit time → outcome is **stop (loss)**. Otherwise, highest target hit counts.

4. **Outcome categories:**
   - Stop hit first → loss
   - Target 2 hit (without prior stop) → profit at target2
   - Target 1 hit (without prior stop) → profit at target1
   - Nothing hit → position still open (live P/L shown)

---

## Frontend Notes

- Single HTML file: `templates/index.html`
- Bootstrap 5.3.2 loaded from CDN (no local assets)
- Two-column layout: left sidebar (saved positions), right panel (form + results)
- Chart is embedded as a `<img src="data:image/png;base64,...">` tag
- Two JavaScript functions:
  - `loadPosition(id)` — redirects to `/?load=<id>`
  - `deletePosition(id)` — submits a hidden form to `/delete_position/<id>`
- All user-visible text is in **Turkish**

---

## External API

The app calls **Binance Spot REST API**:

```
GET https://api.binance.com/api/v3/klines
  ?symbol=BTCUSDT
  &interval=1m
  &startTime=<unix_ms>
  &endTime=<unix_ms>
  &limit=1000
```

- Requires no API key (public endpoint)
- Returns at most 1000 candles per request — for positions open longer than ~16 hours, data will be truncated
- Timeout: 10 seconds
- Error handling: `resp.raise_for_status()` + runtime error if empty response
- Debug logging is printed to stdout for each request

---

## Known Limitations & Gotchas

1. **1000-candle limit:** Binance returns max 1000 × 1-minute candles per request (~16.6 hours). Positions open longer will have incomplete data.
2. **No API key:** Only public endpoints are used; no rate-limit authentication.
3. **ID collision:** Position IDs are set to `len(list) + 1`, so deletions followed by additions can produce duplicate IDs.
4. **No input sanitization:** Coin symbols are uppercased but not otherwise validated before hitting the Binance API.
5. **Debug prints in production:** `get_binance_klines()` prints verbose debug output to stdout unconditionally.
6. **No tests:** There is no test suite. Manual testing only.
7. **Single-threaded JSON writes:** No file locking; concurrent requests could corrupt `saved_positions.json`.

---

## Development Conventions

- **No build step** — edit files directly, restart Flask to see changes.
- **No linter/formatter configured** — follow PEP 8 for Python, standard Bootstrap conventions for HTML.
- **All business logic lives in `web_app.py`** — do not split into multiple files unless the application grows significantly.
- **Turkish strings** — error messages, UI labels, and result text are all in Turkish. Keep this consistent when adding new user-facing text.
- **Form field names** must match between `index.html` and `web_app.py` (`request.form.get()`).
- **Chart rendering** uses `matplotlib.figure.Figure` (not `plt`) to avoid global state issues in a web context.

---

## Deployment

Configured for Heroku-style deployment via `Procfile.txt`:

```
web: gunicorn web_app:app
```

The app binds to `0.0.0.0:5000` in dev mode. In production, Gunicorn manages the port via the `PORT` environment variable automatically.

JSON data files (`web_settings.json`, `saved_positions.json`) are written to the working directory. On ephemeral filesystems (e.g., Heroku dynos), these will be reset on restart — consider adding persistent storage if saving positions long-term is important.
