
import json
import os
import re
import sys
import tempfile
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

# ==========================================
# YALLA KORA - MULTI LEAGUE ENGINE
# ==========================================

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "matches.json"
BROADCASTS_FILE = ROOT / "broadcasts.json"

BASE_URL = "https://www.fotmob.com/api/data"
TZ = ZoneInfo("Asia/Riyadh")
COUNTRY_CODE = "IRQ"

DAYS = (-1, 0, 1)
TIMEOUT = 25

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 YallaKoraDataBot/4.0",
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://www.fotmob.com/"
})


# ==========================================
# HELPERS
# ==========================================

def clean(value):
    if value is None or isinstance(value, (dict, list)):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def normalize(value):
    value = unicodedata.normalize(
        "NFKC", clean(value)
    ).casefold()

    value = re.sub(
        r"[\u064B-\u065F\u0670ـ]", "", value
    )

    return re.sub(
        r"[^a-z0-9\u0600-\u06ff]+", "", value
    )


def fetch_json(path, params=None):
    response = session.get(
        f"{BASE_URL}/{path.lstrip('/')}",
        params=params or {},
        timeout=TIMEOUT
    )

    response.raise_for_status()
    return response.json()


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except Exception as error:
        print("JSON READ ERROR:", error)
        return default


# ==========================================
# OLD DATA PRESERVATION
# ==========================================

def old_data_maps():

    old = load_json(OUTPUT, {})

    streams = {}
    broadcasts = {}

    for match in old.get("matches", []):

        if not isinstance(match, dict):
            continue

        key = (
            clean(match.get("date")),
            normalize(match.get("home")),
            normalize(match.get("away"))
        )

        if not key[1] or not key[2]:
            continue

        if clean(match.get("streamUrl")):
            streams[key] = match["streamUrl"]

        broadcasts[key] = {
            "channel": clean(match.get("channel")),
            "commentator": clean(match.get("commentator"))
        }

    return streams, broadcasts


# ==========================================
# TIMEZONE
# ==========================================

def parse_utc(value):

    value = clean(value)

    if not value:
        return None

    try:
        dt = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(TZ)

    except ValueError:
        return None


# ==========================================
# MATCH DATA
# ==========================================

def team_info(team):

    if not isinstance(team, dict):
        return "", ""

    name = (
        clean(team.get("nameAr"))
        or clean(team.get("name_ar"))
        or clean(team.get("name"))
        or clean(team.get("shortName"))
    )

    logo = (
        clean(team.get("imageUrl"))
        or clean(team.get("logo"))
        or clean(team.get("logo_url"))
    )

    team_id = clean(team.get("id"))

    if not logo and team_id.isdigit():
        logo = (
            "https://images.fotmob.com/image_resources/"
            f"logo/teamlogo/{team_id}.png"
        )

    return name, logo


def match_status(status):

    if isinstance(status, dict):

        if status.get("cancelled") or status.get("finished"):
            return "ended"

        if status.get("started"):
            return "live"

        reason = clean(
            status.get("reason")
        ).lower()

        if reason in ("ft", "aet", "pen", "finished"):
            return "ended"

        if reason in ("ht", "1h", "2h", "live"):
            return "live"

    raw = clean(status).lower()

    if raw in ("live", "ht", "1h", "2h"):
        return "live"

    if raw in ("ft", "aet", "pen", "ended", "finished"):
        return "ended"

    return "upcoming"


def get_score(item, status):

    if isinstance(status, dict):

        score = clean(status.get("scoreStr"))

        if score and score not in ("-", "vs"):
            return score.replace(" ", "")

    home = item.get("home", {})
    away = item.get("away", {})

    if isinstance(home, dict) and isinstance(away, dict):

        h = home.get("score")
        a = away.get("score")

        if h is not None and a is not None:
            return f"{h}-{a}"

    return ""


# ==========================================
# BROADCAST INFORMATION
# ==========================================

def load_broadcasts():
    data = load_json(BROADCASTS_FILE, {})
    return data if isinstance(data, dict) else {}


def get_broadcast(
    item, date, home, away,
    old_broadcasts, overrides
):

    key = (
        date,
        normalize(home),
        normalize(away)
    )

    previous = old_broadcasts.get(key, {})

    match_id = clean(item.get("id"))

    override = overrides.get(match_id, {})

    if not isinstance(override, dict):
        override = {}

    if not override:

        override = overrides.get(
            "|".join(key), {}
        )

        if not isinstance(override, dict):
            override = {}

    channel = (
        clean(override.get("channel"))
        or clean(previous.get("channel"))
    )

    commentator = (
        clean(override.get("commentator"))
        or clean(previous.get("commentator"))
    )

    return channel, commentator


# ==========================================
# CONVERT MATCH
# ==========================================

def convert_match(
    item,
    streams,
    old_broadcasts,
    overrides
):

    if not isinstance(item, dict):
        return None

    home, home_img = team_info(
        item.get("home")
    )

    away, away_img = team_info(
        item.get("away")
    )

    if not home or not away:
        return None

    status = item.get("status", {})

    kickoff = parse_utc(
        status.get("utcTime")
        if isinstance(status, dict)
        else item.get("utcTime")
    )

    if kickoff is None:
        kickoff = parse_utc(
            item.get("utcTime")
            or item.get("startTime")
        )

    if kickoff is None:
        print("Missing kickoff:", home, away)
        return None

    date = kickoff.strftime("%Y-%m-%d")
    hour = kickoff.strftime("%H:%M")

    key = (
        date,
        normalize(home),
        normalize(away)
    )

    league = item.get("league") or {}

    if isinstance(league, dict):
        league = (
            league.get("name")
            or league.get("localizedName")
            or ""
        )

    channel, commentator = get_broadcast(
        item,
        date,
        home,
        away,
        old_broadcasts,
        overrides
    )

    return {

        "league": clean(league),

        "home": home,
        "away": away,

        "team1": home,
        "team2": away,

        "home_img": home_img,
        "away_img": away_img,

        "hour": hour,
        "time": hour,

        "date": date,
        "match_date": date,

        "status": match_status(status),

        "score": get_score(item, status),

        "channel": channel,
        "commentator": commentator,

        "streamUrl": streams.get(key, "")
    }


# ==========================================
# FETCH MATCHES
# ==========================================

def extract_matches(payload):

    if isinstance(payload, dict):

        if isinstance(payload.get("matches"), list):
            return payload["matches"]

        rows = []

        for league in payload.get("leagues", []):

            if not isinstance(league, dict):
                continue

            for match in league.get("matches", []):

                if isinstance(match, dict):

                    match = dict(match)
                    match.setdefault("league", league)

                    rows.append(match)

        if rows:
            return rows

    raise ValueError("Invalid matches response")


def fetch_day(date):

    day = date.strftime("%Y%m%d")

    print("Fetching:", day)

    payload = fetch_json(
        "matches",
        {
            "date": day,
            "timezone": TZ.key,
            "ccode3": COUNTRY_CODE
        }
    )

    return extract_matches(payload)


# ==========================================
# SAVE JSON SAFELY
# ==========================================

def save_matches(data):

    content = json.dumps(
        data,
        ensure_ascii=False,
        indent=2
    ) + "\n"

    temp_path = None

    try:

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=ROOT,
            delete=False
        ) as f:

            f.write(content)
            temp_path = f.name

        with open(temp_path, encoding="utf-8") as f:
            json.load(f)

        os.replace(temp_path, OUTPUT)

    finally:

        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


# ==========================================
# MAIN
# ==========================================

def main():

    now = datetime.now(TZ)
    today_date = now.date()

    streams, old_broadcasts = old_data_maps()
    overrides = load_broadcasts()

    collected = {}
    errors = {}

    for offset in DAYS:

        target = today_date + timedelta(days=offset)
        date_key = target.isoformat()

        try:

            for item in fetch_day(target):

                match_id = clean(item.get("id"))

                stable_key = (
                    match_id
                    or json.dumps(
                        item,
                        sort_keys=True,
                        ensure_ascii=False
                    )
                )

                collected[stable_key] = item

        except Exception as error:

            errors[date_key] = str(error)
            print("FETCH ERROR:", date_key, error)

    today_key = today_date.isoformat()

    if today_key in errors:
        raise RuntimeError(
            "Today's feed failed. Old JSON preserved."
        )

    if not collected:
        raise RuntimeError("No matches received.")

    converted = []

    for item in collected.values():

        match = convert_match(
            item,
            streams,
            old_broadcasts,
            overrides
        )

        if match:
            converted.append(match)

    yesterday_key = (
        today_date - timedelta(days=1)
    ).isoformat()

    tomorrow_key = (
        today_date + timedelta(days=1)
    ).isoformat()

    allowed = {
        yesterday_key,
        today_key,
        tomorrow_key
    }

    unique = {}

    for match in converted:

        if match["date"] not in allowed:
            continue

        key = (
            match["date"],
            normalize(match["home"]),
            normalize(match["away"])
        )

        unique[key] = match

    matches = list(unique.values())

    matches.sort(
        key=lambda m: (
            m["date"],
            m["hour"],
            m["league"],
            m["home"]
        )
    )

    yesterday = [
        m for m in matches
        if m["date"] == yesterday_key
    ]

    today = [
        m for m in matches
        if m["date"] == today_key
    ]

    tomorrow = [
        m for m in matches
        if m["date"] == tomorrow_key
    ]

    if not today:
        raise RuntimeError(
            "No matches today. Old JSON preserved."
        )

    output = {

        "success": True,

        "updated_at": datetime.now(TZ).isoformat(),

        "timezone": TZ.key,

        "count": len(matches),

        "today_count": len(today),

        "yesterday_count": len(yesterday),

        "tomorrow_count": len(tomorrow),

        "matches": matches,

        "today": today,

        "yesterday": yesterday,

        "tomorrow": tomorrow
    }

    save_matches(output)

    print("\n===== YALLA KORA UPDATE =====")

    print("Timezone:", TZ.key)

    print("Today:", len(today))
    print("Yesterday:", len(yesterday))
    print("Tomorrow:", len(tomorrow))

    print("Total:", len(matches))

    print(
        "Channels:",
        sum(bool(m["channel"]) for m in matches)
    )

    print(
        "Commentators:",
        sum(bool(m["commentator"]) for m in matches)
    )

    print(
        "Stream URLs:",
        sum(bool(m["streamUrl"]) for m in matches)
    )

    print("Errors:", errors or "None")

    print("=============================")


if __name__ == "__main__":

    try:
        main()

    except Exception as error:

        print("UPDATE FAILED:", error)
        sys.exit(1)
