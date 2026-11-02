
import json
import os
import re
import sys
import tempfile
import requests

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# ==========================================
# YALLA KORA - TIFO MATCHES UPDATER
# ==========================================

API = "https://tifo.elyoxe.com/v1"
OUTPUT = "matches.json"

BAGHDAD = ZoneInfo("Asia/Baghdad")
DUBAI = ZoneInfo("Asia/Dubai")

session = requests.Session()
session.headers.update({
    "User-Agent": "YallaKora-MatchUpdater/2.0",
    "Accept": "application/json",
    "Accept-Encoding": "gzip, deflate",
})


def clean(value):
    if value is None or isinstance(value, (dict, list)):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def normalize(value):
    return clean(value).casefold().replace("ـ", "")


def fetch_json(path):
    response = session.get(API + path, timeout=30)
    response.raise_for_status()
    return response.json()


def parse_datetime(value, default_tz):
    value = clean(value)
    if not value:
        return None

    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=default_tz)

        return dt.astimezone(BAGHDAD)
    except (ValueError, TypeError):
        return None


def get_kickoff(match):
    # kickoff_utc must be interpreted as UTC, even if
    # the API omits the trailing Z or timezone offset.
    dt = parse_datetime(
        match.get("kickoff_utc"),
        timezone.utc
    )
    if dt:
        return dt

    dt = parse_datetime(
        match.get("kickoff_uae"),
        DUBAI
    )
    if dt:
        return dt

    return None


def get_team(data):
    if not isinstance(data, dict):
        return clean(data), ""

    name = (
        clean(data.get("name_ar"))
        or clean(data.get("name"))
        or clean(data.get("short_name_ar"))
        or clean(data.get("short_name"))
    )

    logo = (
        clean(data.get("logo"))
        or clean(data.get("logo_url"))
        or clean(data.get("image"))
    )

    return name, logo


def get_status(status):
    status = clean(status).lower()

    if status in ("live", "ht"):
        return "live"

    if status == "finished":
        return "ended"

    return "upcoming"


def get_score(match):
    score = match.get("score")

    if not isinstance(score, dict):
        return ""

    home = score.get("home")
    away = score.get("away")

    if home is None or away is None:
        return ""

    return f"{home}-{away}"


def get_commentators(data):
    result = {}

    people = data.get("commentators", {})

    if not isinstance(people, dict):
        return result

    # Next assignments take priority over recent assignments.
    for section in ("recent", "next"):
        for person in people.values():

            if not isinstance(person, dict):
                continue

            name = clean(person.get("name"))
            assignments = person.get(section, [])

            if not isinstance(assignments, list):
                continue

            for assignment in assignments:

                if not isinstance(assignment, (list, tuple)):
                    continue

                if len(assignment) < 2:
                    continue

                match_id = clean(assignment[0])
                channel = clean(assignment[1])

                if match_id and name:
                    result[match_id] = {
                        "commentator": name,
                        "channel": channel,
                    }

    return result


def load_old_matches():
    streams = {}
    broadcasts = {}

    if not os.path.exists(OUTPUT):
        return streams, broadcasts

    try:
        with open(OUTPUT, "r", encoding="utf-8") as file:
            old_data = json.load(file)

        for match in old_data.get("matches", []):

            if not isinstance(match, dict):
                continue

            key = (
                clean(match.get("date")),
                normalize(match.get("home")),
                normalize(match.get("away")),
            )

            if not key[1] or not key[2]:
                continue

            stream = clean(match.get("streamUrl"))

            if stream:
                streams[key] = stream

            broadcasts[key] = {
                "channel": clean(match.get("channel")),
                "commentator": clean(match.get("commentator")),
            }

    except Exception as error:
        print("Old matches could not be read:", error)

    return streams, broadcasts


def convert_match(
    item,
    commentators,
    old_streams,
    old_broadcasts
):
    if not isinstance(item, dict):
        return None

    match_id = clean(item.get("id"))

    home, home_img = get_team(item.get("home"))
    away, away_img = get_team(item.get("away"))

    if not home or not away:
        return None

    kickoff = get_kickoff(item)

    if not kickoff:
        print("Skipped match without kickoff:", match_id)
        return None

    local_date = kickoff.strftime("%Y-%m-%d")
    local_hour = kickoff.strftime("%H:%M")

    key = (
        local_date,
        normalize(home),
        normalize(away),
    )

    new_broadcast = commentators.get(match_id, {})
    old_broadcast = old_broadcasts.get(key, {})

    channel = (
        clean(new_broadcast.get("channel"))
        or clean(old_broadcast.get("channel"))
    )

    commentator = (
        clean(new_broadcast.get("commentator"))
        or clean(old_broadcast.get("commentator"))
    )

    league = clean(item.get("comp_name_ar"))

    return {
        "league": league,
        "home": home,
        "away": away,
        "team1": home,
        "team2": away,
        "home_img": home_img,
        "away_img": away_img,
        "hour": local_hour,
        "time": local_hour,
        "date": local_date,
        "match_date": local_date,
        "status": get_status(item.get("status")),
        "score": get_score(item),
        "channel": channel,
        "commentator": commentator,
        "streamUrl": old_streams.get(key, ""),
    }


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
            dir=".",
            delete=False
        ) as file:
            file.write(content)
            temp_path = file.name

        # Validate JSON before replacing the existing file.
        with open(temp_path, "r", encoding="utf-8") as file:
            json.load(file)

        os.replace(temp_path, OUTPUT)

    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


def main():

    now = datetime.now(BAGHDAD)
    today_date = now.date()

    yesterday_date = today_date - timedelta(days=1)
    tomorrow_date = today_date + timedelta(days=1)

    old_streams, old_broadcasts = load_old_matches()

    all_raw_matches = {}
    failed_days = []

    # Tifo uses UAE dates. Fetch a margin around Baghdad's
    # current date, then classify matches using Baghdad time.
    for offset in range(-2, 3):

        target_date = today_date + timedelta(days=offset)
        day_key = target_date.strftime("%Y%m%d")

        print("Downloading:", day_key)

        try:
            payload = fetch_json(f"/day/{day_key}.json")

            rows = payload.get("matches", [])

            if not isinstance(rows, list):
                raise ValueError("Invalid matches array")

            for item in rows:

                if not isinstance(item, dict):
                    continue

                match_id = clean(item.get("id"))

                if match_id:
                    all_raw_matches[match_id] = item

        except Exception as error:
            failed_days.append(day_key)
            print("Download failed:", day_key, error)

    if not all_raw_matches:
        raise RuntimeError(
            "No matches received. Existing matches.json preserved."
        )

    # Optional commentator and TV channel assignments.
    commentators = {}

    try:
        tv_data = fetch_json("/tv/commentators.json")
        commentators = get_commentators(tv_data)

        print(
            "Commentator mappings:",
            len(commentators)
        )

    except Exception as error:
        print("TV data unavailable:", error)

    converted = []

    for item in all_raw_matches.values():

        match = convert_match(
            item,
            commentators,
            old_streams,
            old_broadcasts
        )

        if match:
            converted.append(match)

    yesterday_key = yesterday_date.isoformat()
    today_key = today_date.isoformat()
    tomorrow_key = tomorrow_date.isoformat()

    # Keep only yesterday, today and tomorrow in the output.
    converted = [
        match for match in converted
        if match["date"] in (
            yesterday_key,
            today_key,
            tomorrow_key
        )
    ]

    # Remove duplicate fixtures.
    unique = {}

    for match in converted:

        key = (
            match["date"],
            normalize(match["home"]),
            normalize(match["away"]),
        )

        unique[key] = match

    matches = list(unique.values())

    matches.sort(
        key=lambda match: (
            match["date"],
            match["hour"],
            match["league"],
            match["home"]
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

    # Do not overwrite valid old data if today's feed failed.
    if today_key.replace("-", "") in failed_days:
        raise RuntimeError(
            "Today's feed failed. Existing JSON preserved."
        )

    if not today:
        raise RuntimeError(
            "No matches found for today. Existing JSON preserved."
        )

    output = {
        "success": True,
        "updated_at": datetime.now(BAGHDAD).isoformat(),
        "timezone": "Asia/Baghdad",
        "count": len(matches),
        "today_count": len(today),
        "yesterday_count": len(yesterday),
        "tomorrow_count": len(tomorrow),
        "matches": matches,
        "today": today,
        "yesterday": yesterday,
        "tomorrow": tomorrow,
    }

    save_matches(output)

    print("")
    print("========== UPDATE COMPLETE ==========")
    print("Today:", len(today))
    print("Yesterday:", len(yesterday))
    print("Tomorrow:", len(tomorrow))
    print(
        "Channels:",
        sum(bool(m["channel"]) for m in matches)
    )
    print(
        "Commentators:",
        sum(bool(m["commentator"]) for m in matches)
    )
    print(
        "Preserved stream URLs:",
        sum(bool(m["streamUrl"]) for m in matches)
    )
    print("Source: https://tifo.elyoxe.com")
    print("=====================================")


if __name__ == "__main__":

    try:
        main()

    except Exception as error:
        print("UPDATE FAILED:", error)
        sys.exit(1)
