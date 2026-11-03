import json
import os
import re
import sys
import tempfile
import requests

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup

# ==========================================
# YALLA KORA - ADVANCED TIFO MATCHES UPDATER
# ==========================================

API = "https://tifo.elyoxe.com/v1"
BASE_URL = "https://tifo.elyoxe.com"
OUTPUT = "matches.json"

BAGHDAD = ZoneInfo("Asia/Baghdad")
DUBAI = ZoneInfo("Asia/Dubai")

session = requests.Session()

session.headers.update({
    "User-Agent": "Mozilla/5.0 YallaKora-MatchUpdater/3.0",
    "Accept": "application/json,text/html,*/*",
    "Accept-Encoding": "gzip, deflate",
})


# ==========================================
# TEXT HELPERS
# ==========================================

def clean(value):
    if value is None or isinstance(value, (dict, list)):
        return ""

    return re.sub(r"\s+", " ", str(value)).strip()


def normalize(value):
    value = clean(value).casefold()
    value = value.replace("ـ", "")
    value = re.sub(r"[\u064B-\u065F\u0670]", "", value)
    return value


def fetch_json(path):
    response = session.get(
        API + path,
        timeout=30
    )

    response.raise_for_status()
    return response.json()


def fetch_page(url):
    response = session.get(
        url,
        timeout=25,
        headers={
            "Accept": "text/html,application/xhtml+xml"
        }
    )

    response.raise_for_status()
    return response.text


# ==========================================
# DATE AND TIME
# ==========================================

def parse_datetime(value, default_tz):
    value = clean(value)

    if not value:
        return None

    try:
        dt = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=default_tz)

        return dt.astimezone(BAGHDAD)

    except (ValueError, TypeError):
        return None


def get_kickoff(match):

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


# ==========================================
# TEAM DATA
# ==========================================

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


# ==========================================
# MATCH STATUS
# ==========================================

def get_status(status):

    status = clean(status).lower()

    if status in (
        "live",
        "ht",
        "half_time",
        "in_progress"
    ):
        return "live"

    if status in (
        "finished",
        "ft",
        "ended",
        "completed"
    ):
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


# ==========================================
# COMMENTATORS AND CHANNELS API
# ==========================================

def get_commentators(data):

    result = {}

    if not isinstance(data, dict):
        return result

    people = data.get("commentators", {})

    if not isinstance(people, dict):
        return result

    # Next assignments override recent assignments.
    for section in ("recent", "next"):

        for person in people.values():

            if not isinstance(person, dict):
                continue

            name = clean(person.get("name"))

            assignments = person.get(section, [])

            if not isinstance(assignments, list):
                continue

            for assignment in assignments:

                if not isinstance(
                    assignment,
                    (list, tuple)
                ):
                    continue

                if len(assignment) < 2:
                    continue

                match_id = clean(assignment[0])
                channel = clean(assignment[1])

                if match_id and name:

                    result[match_id] = {
                        "commentator": name,
                        "channel": channel
                    }

    return result


# ==========================================
# OLD DATA PRESERVATION
# ==========================================

def load_old_matches():

    streams = {}
    broadcasts = {}

    if not os.path.exists(OUTPUT):
        return streams, broadcasts

    try:

        with open(
            OUTPUT,
            "r",
            encoding="utf-8"
        ) as file:

            old_data = json.load(file)

        for match in old_data.get("matches", []):

            if not isinstance(match, dict):
                continue

            key = (
                clean(match.get("date")),
                normalize(match.get("home")),
                normalize(match.get("away"))
            )

            if not key[1] or not key[2]:
                continue

            stream = clean(match.get("streamUrl"))

            if stream:
                streams[key] = stream

            broadcasts[key] = {
                "channel": clean(match.get("channel")),
                "commentator": clean(
                    match.get("commentator")
                )
            }

    except Exception as error:

        print(
            "Old matches could not be read:",
            error
        )

    return streams, broadcasts


# ==========================================
# CONVERT API MATCH
# ==========================================

def convert_match(
    item,
    commentators,
    old_streams,
    old_broadcasts
):

    if not isinstance(item, dict):
        return None

    match_id = clean(item.get("id"))

    home, home_img = get_team(
        item.get("home")
    )

    away, away_img = get_team(
        item.get("away")
    )

    if not home or not away:
        return None

    kickoff = get_kickoff(item)

    if not kickoff:

        print(
            "Skipped match without kickoff:",
            match_id
        )

        return None

    local_date = kickoff.strftime("%Y-%m-%d")
    local_hour = kickoff.strftime("%H:%M")

    key = (
        local_date,
        normalize(home),
        normalize(away)
    )

    new_broadcast = commentators.get(
        match_id,
        {}
    )

    old_broadcast = old_broadcasts.get(
        key,
        {}
    )

    channel = (
        clean(new_broadcast.get("channel"))
        or clean(old_broadcast.get("channel"))
    )

    commentator = (
        clean(new_broadcast.get("commentator"))
        or clean(old_broadcast.get("commentator"))
    )

    league = (
        clean(item.get("comp_name_ar"))
        or clean(item.get("comp_name"))
        or clean(item.get("competition"))
    )

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

        "status": get_status(
            item.get("status")
        ),

        "score": get_score(item),

        "channel": channel,
        "commentator": commentator,

        # Preserve the old player URL.
        "streamUrl": old_streams.get(key, "")
    }


# ==========================================
# SCHEDULE PAGE ENRICHMENT
# ==========================================

def extract_schedule_info(text_value):

    text_value = clean(text_value)

    channel = ""
    commentator = ""

    # Channel labels and icons.
    channel_patterns = [
        r"📺\s*[:：]?\s*(.*?)(?=🎙|المعلق|$)",
        r"(?:القناة|القنوات)\s*[:：]\s*(.*?)(?=🎙|المعلق|$)"
    ]

    # Commentator labels and icons.
    commentator_patterns = [
        r"🎙\s*[:：]?\s*(.*?)(?=📺|القناة|$)",
        r"المعلق\s*[:：]\s*(.*?)(?=📺|القناة|$)"
    ]

    for pattern in channel_patterns:

        found = re.search(
            pattern,
            text_value,
            re.IGNORECASE
        )

        if found:

            channel = clean(
                found.group(1)
            )

            if channel:
                break

    for pattern in commentator_patterns:

        found = re.search(
            pattern,
            text_value,
            re.IGNORECASE
        )

        if found:

            commentator = clean(
                found.group(1)
            )

            if commentator:
                break

    return channel, commentator


def enrich_from_schedule_pages(matches):

    pages = [
        "/yesterday/",
        "/today/",
        "/tomorrow/"
    ]

    for page in pages:

        url = BASE_URL + page

        print(
            "Reading schedule page:",
            url
        )

        try:

            html = fetch_page(url)

            soup = BeautifulSoup(
                html,
                "html.parser"
            )

            for match in matches:

                if (
                    match.get("channel")
                    and match.get("commentator")
                ):
                    continue

                home = normalize(
                    match.get("home")
                )

                away = normalize(
                    match.get("away")
                )

                if not home or not away:
                    continue

                best_text = ""

                # Search small HTML containers first.
                for node in soup.find_all(
                    [
                        "article",
                        "li",
                        "tr",
                        "div",
                        "section"
                    ]
                ):

                    content = clean(
                        node.get_text(
                            " ",
                            strip=True
                        )
                    )

                    normalized_content = normalize(
                        content
                    )

                    if (
                        home in normalized_content
                        and away in normalized_content
                        and len(content) <= 1800
                    ):

                        if (
                            not best_text
                            or len(content) < len(best_text)
                        ):
                            best_text = content

                if not best_text:
                    continue

                channel, commentator = (
                    extract_schedule_info(best_text)
                )

                if (
                    not match.get("channel")
                    and channel
                ):
                    match["channel"] = channel

                if (
                    not match.get("commentator")
                    and commentator
                ):
                    match["commentator"] = commentator

        except Exception as error:

            print(
                "Schedule page error:",
                url,
                error
            )

    return matches


# ==========================================
# OPTIONAL EXTRA DATA
# ==========================================

def fetch_extra_data():

    data = {}

    endpoints = {
        "index": "/index.json",
        "live": "/live.json",
        "teams": "/teams.json",
        "streams": "/streams.json"
    }

    for name, endpoint in endpoints.items():

        try:

            payload = fetch_json(endpoint)

            data[name] = payload

            print(
                "Extra source loaded:",
                name
            )

        except Exception as error:

            print(
                "Extra source unavailable:",
                name,
                error
            )

    return data


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
            dir=".",
            delete=False
        ) as file:

            file.write(content)
            temp_path = file.name

        # Validate before replacing existing file.
        with open(
            temp_path,
            "r",
            encoding="utf-8"
        ) as file:

            json.load(file)

        os.replace(
            temp_path,
            OUTPUT
        )

    finally:

        if (
            temp_path
            and os.path.exists(temp_path)
        ):
            os.remove(temp_path)


# ==========================================
# MAIN UPDATE
# ==========================================

def main():

    now = datetime.now(BAGHDAD)

    today_date = now.date()

    yesterday_date = (
        today_date - timedelta(days=1)
    )

    tomorrow_date = (
        today_date + timedelta(days=1)
    )

    old_streams, old_broadcasts = (
        load_old_matches()
    )

    all_raw_matches = {}
    failed_days = []

    # ======================================
    # DOWNLOAD MATCHES
    # ======================================

    for offset in range(-2, 3):

        target_date = (
            today_date + timedelta(days=offset)
        )

        day_key = target_date.strftime(
            "%Y%m%d"
        )

        print(
            "Downloading matches:",
            day_key
        )

        try:

            payload = fetch_json(
                f"/day/{day_key}.json"
            )

            rows = payload.get(
                "matches",
                []
            )

            if not isinstance(rows, list):

                raise ValueError(
                    "Invalid matches array"
                )

            for item in rows:

                if not isinstance(item, dict):
                    continue

                match_id = clean(
                    item.get("id")
                )

                if match_id:

                    all_raw_matches[match_id] = item

        except Exception as error:

            failed_days.append(day_key)

            print(
                "Download failed:",
                day_key,
                error
            )

    if not all_raw_matches:

        raise RuntimeError(
            "No matches received. Existing matches.json preserved."
        )

    # ======================================
    # COMMENTATORS API
    # ======================================

    commentators = {}

    try:

        tv_data = fetch_json(
            "/tv/commentators.json"
        )

        commentators = get_commentators(
            tv_data
        )

        print(
            "Commentator mappings:",
            len(commentators)
        )

    except Exception as error:

        print(
            "TV data unavailable:",
            error
        )

    # ======================================
    # OPTIONAL EXTRA SOURCES
    # ======================================

    extra_data = fetch_extra_data()

    # ======================================
    # CONVERT MATCHES
    # ======================================

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

    # ======================================
    # FILTER THREE DAYS
    # ======================================

    converted = [
        match
        for match in converted
        if match["date"] in (
            yesterday_key,
            today_key,
            tomorrow_key
        )
    ]

    # ======================================
    # REMOVE DUPLICATES
    # ======================================

    unique = {}

    for match in converted:

        key = (
            match["date"],
            normalize(match["home"]),
            normalize(match["away"])
        )

        unique[key] = match

    matches = list(
        unique.values()
    )

    # ======================================
    # ENRICH CHANNELS AND COMMENTATORS
    # ======================================

    matches = enrich_from_schedule_pages(
        matches
    )

    # ======================================
    # SORT MATCHES
    # ======================================

    matches.sort(
        key=lambda match: (
            match["date"],
            match["hour"],
            match["league"],
            match["home"]
        )
    )

    # ======================================
    # SPLIT DAYS
    # ======================================

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

    # ======================================
    # SAFETY CHECKS
    # ======================================

    if today_key.replace("-", "") in failed_days:

        raise RuntimeError(
            "Today's feed failed. Existing JSON preserved."
        )

    if not today:

        raise RuntimeError(
            "No matches found for today. Existing JSON preserved."
        )

    # ======================================
    # FINAL JSON
    # ======================================

    output = {

        "success": True,

        "updated_at": datetime.now(
            BAGHDAD
        ).isoformat(),

        "timezone": "Asia/Baghdad",

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

    # ======================================
    # REPORT
    # ======================================

    print("")
    print("========== UPDATE COMPLETE ==========")

    print(
        "Today:",
        len(today)
    )

    print(
        "Yesterday:",
        len(yesterday)
    )

    print(
        "Tomorrow:",
        len(tomorrow)
    )

    print(
        "Total:",
        len(matches)
    )

    print(
        "Channels:",
        sum(
            bool(m["channel"])
            for m in matches
        )
    )

    print(
        "Commentators:",
        sum(
            bool(m["commentator"])
            for m in matches
        )
    )

    print(
        "Preserved stream URLs:",
        sum(
            bool(m["streamUrl"])
            for m in matches
        )
    )

    print(
        "Extra sources:",
        ", ".join(extra_data.keys())
    )

    print(
        "Source: https://tifo.elyoxe.com"
    )

    print("=====================================")


# ==========================================
# RUN
# ==========================================

if __name__ == "__main__":

    try:

        main()

    except Exception as error:

        print(
            "UPDATE FAILED:",
            error
        )

        sys.exit(1)
