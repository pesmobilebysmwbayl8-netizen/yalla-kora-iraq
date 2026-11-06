
# ============================================================
# YALLA KORA V11
# Multi-source football matches + Arabic broadcasters
# Timezone: Asia/Baghdad
# Output: matches.json
# ============================================================

import requests
import json
import re
import os
import html
import time
import unicodedata

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# ---------------- CONFIG ----------------

TZ = ZoneInfo("Asia/Baghdad")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

OUTPUT_FILE = os.path.join(BASE_DIR, "matches.json")
BROADCAST_FILE = os.path.join(BASE_DIR, "broadcasts.json")

AS_GOAL = "https://as-goal.net/commentators-channels/"
TALK_NOW = "https://talknow.online/"
FILGOAL = "https://www.filgoal.com/"
ORIGINAL = "https://originalpro.online/"
ALMASHHAD = (
    "https://www.almashhad.com/amp/article/"
    "218257510540304-sports/"
    "563101227576063-%D8%AC%D8%AF%D9%88%D9%84-%D9%85%D9%88%D8%A7%D8%B9%D9%8A%D8%AF-%D9%85%D8%A8%D8%A7%D8%B1%D9%8A%D8%A7%D8%AA-%D8%A7%D9%84%D9%8A%D9%88%D9%85-%D8%A7%D9%84%D8%AC%D9%85%D8%B9%D8%A9-06112026-%D9%85%D8%B9-%D8%A7%D9%84%D9%82%D9%86%D9%88%D8%A7%D8%AA-%D8%A7%D9%84%D9%86%D8%A7%D9%82%D9%84%D8%A9-%D9%88%D8%A7%D9%84%D9%85%D8%B9%D9%84%D9%82%D9%8A%D9%86"
)

FOTMOB = "https://www.fotmob.com/api/data/matches"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 10) "
        "AppleWebKit/537.36 Chrome/130.0 Mobile Safari/537.36"
    ),
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
}

TIMEOUT = 25
DAYS = [-1, 0, 1]

session = requests.Session()
session.headers.update(HEADERS)

stats = {
    "fotmob": 0,
    "as_goal": 0,
    "talknow": 0,
    "filgoal": 0,
    "original": 0,
    "almashhad": 0,
    "errors": 0,
}

# ---------------- HELPERS ----------------

def log(message):
    print(message, flush=True)


def get_page(url):
    try:
        response = session.get(url, timeout=TIMEOUT)
        response.raise_for_status()

        if not response.encoding or response.encoding == "ISO-8859-1":
            response.encoding = response.apparent_encoding

        return response.text

    except Exception as e:
        stats["errors"] += 1
        log(f"FETCH ERROR: {url} | {e}")
        return ""


def normalize(value):
    value = html.unescape(str(value or ""))
    value = unicodedata.normalize("NFKC", value)
    value = value.replace("ـ", "")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def clean_name(value):
    value = normalize(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip(" -|،")


def team_key(value):
    value = normalize(value).lower()

    replacements = {
        "أ": "ا", "إ": "ا", "آ": "ا",
        "ى": "ي", "ة": "ه",
        "ي": "ي",
    }

    for a, b in replacements.items():
        value = value.replace(a, b)

    value = re.sub(r"[^a-z0-9\u0600-\u06ff]", "", value)
    return value


def get_json(url, params=None):
    try:
        response = session.get(
            url,
            params=params,
            timeout=TIMEOUT
        )
        response.raise_for_status()
        return response.json()

    except Exception as e:
        stats["errors"] += 1
        log(f"JSON ERROR: {e}")
        return {}


def empty_match():
    return {
        "league": "",
        "home": "",
        "away": "",
        "team1": "",
        "team2": "",
        "home_img": "",
        "away_img": "",
        "hour": "",
        "time": "",
        "date": "",
        "match_date": "",
        "status": "upcoming",
        "score": "",
        "channel": "",
        "commentator": "",
        "streamUrl": "",
    }


# ---------------- MATCH ID ----------------

def match_id(match):
    return (
        team_key(match.get("home", "")),
        team_key(match.get("away", "")),
        match.get("date", "")
    )


def same_match(a, b):
    if not a or not b:
        return False

    if a.get("date") != b.get("date"):
        return False

    ah = team_key(a.get("home"))
    aa = team_key(a.get("away"))
    bh = team_key(b.get("home"))
    ba = team_key(b.get("away"))

    if not all([ah, aa, bh, ba]):
        return False

    direct = (
        ah in bh or bh in ah
    ) and (
        aa in ba or ba in aa
    )

    reverse = (
        ah in ba or ba in ah
    ) and (
        aa in bh or bh in aa
    )

    return direct or reverse


# ---------------- FOTMOB ----------------

def fotmob_matches():
    results = []

    for offset in DAYS:
        day = datetime.now(TZ).date() + timedelta(days=offset)
        date_string = day.strftime("%Y%m%d")

        log(f"FOTMOB FETCH: {date_string}")

        data = get_json(
            FOTMOB,
            params={
                "date": date_string,
                "timezone": "Asia/Baghdad",
                "ccode3": "IRQ",
            }
        )

        leagues = data.get("leagues", [])

        for league in leagues:
            league_name = league.get("name", "")

            for item in league.get("matches", []):
                try:
                    home_data = item.get("home", {})
                    away_data = item.get("away", {})

                    home = clean_name(
                        home_data.get("name", "")
                    )

                    away = clean_name(
                        away_data.get("name", "")
                    )

                    if not home or not away:
                        continue

                    match = empty_match()

                    match["league"] = clean_name(league_name)
                    match["home"] = home
                    match["away"] = away
                    match["team1"] = home
                    match["team2"] = away

                    match["home_img"] = (
                        home_data.get("imageUrl", "")
                        or home_data.get("logo", "")
                    )

                    match["away_img"] = (
                        away_data.get("imageUrl", "")
                        or away_data.get("logo", "")
                    )

                    match["date"] = day.isoformat()
                    match["match_date"] = day.isoformat()

                    status_data = item.get("status", {})
                    status_text = normalize(
                        status_data.get("reason", "")
                    ).lower()

                    if item.get("status", {}).get("started"):
                        match["status"] = "live"
                    elif item.get("status", {}).get("finished"):
                        match["status"] = "ended"
                    else:
                        match["status"] = "upcoming"

                    score_home = home_data.get("score")
                    score_away = away_data.get("score")

                    if score_home is not None and score_away is not None:
                        match["score"] = (
                            f"{score_home}-{score_away}"
                        )

                    timestamp = (
                        item.get("status", {}).get("utcTime")
                        or item.get("status", {}).get("startTime")
                        or item.get("utcTime")
                    )

                    if timestamp:
                        try:
                            dt = datetime.fromisoformat(
                                str(timestamp).replace("Z", "+00:00")
                            ).astimezone(TZ)

                            match["hour"] = dt.strftime("%H:%M")
                            match["time"] = match["hour"]
                            match["date"] = dt.date().isoformat()
                            match["match_date"] = match["date"]

                        except Exception:
                            pass

                    results.append(match)

                except Exception as e:
                    log(f"FOTMOB MATCH ERROR: {e}")

    stats["fotmob"] = len(results)
    return results


# ---------------- AS GOAL ----------------

CHANNEL_WORDS = [
    "بي إن سبورت",
    "beIN SPORTS",
    "beIN Sport",
    "اون سبورت",
    "أون سبورت",
    "ON Sport",
    "الكأس",
    "Al-Kass",
    "SSC",
    "اس اس سي",
    "STARZPLAY",
    "ستارز بلاي",
    "MBC",
    "شاهد",
    "دبي الرياضية",
    "أبوظبي الرياضية",
    "AD Sports",
    "القنوات الرياضية",
    "الرياضية المغربية",
    "الكويت الرياضية",
    "العراقية الرياضية",
    "عمان الرياضية",
    "قناة الرابعة",
]

def find_channel(text):
    low = normalize(text).lower()

    for channel in CHANNEL_WORDS:
        if channel.lower() in low:
            return channel

    return ""


def parse_as_goal():
    results = []

    page = get_page(AS_GOAL)
    if not page:
        return results

    soup = BeautifulSoup(page, "html.parser")

    for anchor in soup.find_all("a"):
        text = clean_name(anchor.get_text(" ", strip=True))

        if len(text) < 15:
            continue

        time_match = re.search(
            r"\b([01]?\d|2[0-3]):[0-5]\d\b",
            text
        )

        if not time_match:
            continue

        channel = find_channel(text)
        if not channel:
            continue

        before = text[:time_match.start()].strip()
        after = text[time_match.end():].strip()

        # Remove possible competition prefix if present.
        before = re.sub(
            r"^(مباريات اليوم|مباريات الغد)\s*",
            "",
            before
        )

        # Find channel position in remaining text.
        lower_after = after.lower()
        positions = []

        for word in CHANNEL_WORDS:
            pos = lower_after.find(word.lower())
            if pos >= 0:
                positions.append(pos)

        if not positions:
            continue

        channel_pos = min(positions)
        away = clean_name(after[:channel_pos])

        channel_and_commentator = after[channel_pos:]

        channel_match = None
        for word in CHANNEL_WORDS:
            found = re.search(
                re.escape(word),
                channel_and_commentator,
                re.I
            )
            if found:
                channel_match = found
                break

        if not channel_match:
            continue

        commentator = clean_name(
            channel_and_commentator[channel_match.end():]
        )

        # Remove English duplicate names when possible.
        commentator = re.sub(
            r"\b[A-Z][A-Za-z .'-]{3,}$",
            "",
            commentator
        ).strip()

        home = clean_name(before)

        if not home or not away:
            continue

        match = empty_match()

        match["home"] = home
        match["away"] = away
        match["team1"] = home
        match["team2"] = away
        match["channel"] = channel
        match["commentator"] = commentator

        match["hour"] = time_match.group()
        match["time"] = match["hour"]

        # Determine date by section heading.
        match["date"] = datetime.now(TZ).date().isoformat()
        match["match_date"] = match["date"]

        results.append(match)

    stats["as_goal"] = len(results)
    log(f"AS GOAL MATCHES: {len(results)}")

    return results


# ---------------- TALK NOW ----------------

def parse_talknow():
    results = []

    page = get_page(TALK_NOW)
    if not page:
        return results

    soup = BeautifulSoup(page, "html.parser")

    for node in soup.find_all(["article", "div", "li"]):
        text = clean_name(node.get_text(" ", strip=True))

        if len(text) < 20 or len(text) > 1200:
            continue

        # A card must contain a time and two teams.
        tm = re.search(
            r"\b([01]?\d|2[0-3]):[0-5]\d\b",
            text
        )

        if not tm:
            continue

        channel = find_channel(text)
        if not channel:
            continue

        commentator = ""

        for word in CHANNEL_WORDS:
            pos = text.lower().find(word.lower())
            if pos >= 0:
                remainder = text[pos + len(word):]
                parts = remainder.split()
                if parts:
                    commentator = clean_name(
                        " ".join(parts[:5])
                    )
                break

        # Use a conservative card parser.
        parts = re.split(
            r"\b([01]?\d|2[0-3]):[0-5]\d\b",
            text,
            maxsplit=1
        )

        if len(parts) < 3:
            continue

        left = clean_name(parts[0])
        right = clean_name(parts[2])

        # Avoid accepting large page containers.
        if len(left) > 100 or len(right) > 250:
            continue

        match = empty_match()
        match["home"] = left
        match["away"] = right.split(channel)[0].strip()
        match["team1"] = match["home"]
        match["team2"] = match["away"]
        match["channel"] = channel
        match["commentator"] = commentator
        match["hour"] = tm.group()
        match["time"] = match["hour"]
        match["date"] = datetime.now(TZ).date().isoformat()
        match["match_date"] = match["date"]

        if match["home"] and match["away"]:
            results.append(match)

    # Remove duplicate cards.
    unique = {}
    for match in results:
        key = (
            team_key(match["home"]),
            team_key(match["away"]),
            match["hour"]
        )
        unique[key] = match

    results = list(unique.values())
    stats["talknow"] = len(results)

    log(f"TALKNOW MATCHES: {len(results)}")
    return results


# ---------------- FILGOAL ----------------

def parse_filgoal():
    results = []

    page = get_page(FILGOAL)
    if not page:
        return results

    soup = BeautifulSoup(page, "html.parser")

    links = []

    for a in soup.find_all("a", href=True):
        href = a["href"]

        if "/matches/" in href and "/overview/" in href:
            full_url = urljoin(FILGOAL, href)

            if full_url not in links:
                links.append(full_url)

    log(f"FILGOAL MATCH LINKS: {len(links)}")

    for url in links[:100]:
        detail = get_page(url)
        if not detail:
            continue

        detail_soup = BeautifulSoup(detail, "html.parser")
        text = clean_name(
            detail_soup.get_text(" ", strip=True)
        )

        # Extract the two team names from page title/headings.
        title = detail_soup.title.get_text(
            " ", strip=True
        ) if detail_soup.title else ""

        match = empty_match()

        # FilGoal detail pages expose channel/commentator
        # in the match information text.
        channel = find_channel(text)

        if not channel:
            continue

        match["channel"] = channel

        channel_pos = text.lower().find(channel.lower())
        if channel_pos >= 0:
            tail = text[channel_pos + len(channel):]
            words = tail.split()

            if words:
                commentator = clean_name(
                    " ".join(words[:5])
                )
                match["commentator"] = commentator

        # Extract team names from the page title when available.
        found = re.search(
            r"مباراة فريقي\s+(.+?)\s+و\s+(.+?)\s+في بطولة",
            title
        )

        if found:
            match["home"] = clean_name(found.group(1))
            match["away"] = clean_name(found.group(2))
            match["team1"] = match["home"]
            match["team2"] = match["away"]

        # Extract competition.
        competition = re.search(
            r"(الدوري|كأس|دوري أبطال)[^،|]{2,70}",
            text
        )

        if competition:
            match["league"] = clean_name(
                competition.group()
            )

        # Extract date/time.
        date_match = re.search(
            r"(\d{1,2})\s+(يناير|فبراير|مارس|أبريل|مايو|يونيو|يوليو|أغسطس|سبتمبر|أكتوبر|نوفمبر|ديسمبر)\s+(\d{4})\s+(\d{1,2}:\d{2})",
            text
        )

        if date_match:
            match["hour"] = date_match.group(4)
            match["time"] = match["hour"]

        if match["home"] and match["away"]:
            results.append(match)

        time.sleep(0.2)

    stats["filgoal"] = len(results)
    log(f"FILGOAL DETAILS: {len(results)}")

    return results


# ---------------- ORIGINAL TV ----------------

def parse_original():
    results = []

    # The supplied URL is a single match page.
    # Do not guess other match IDs.
    page = get_page(
        urljoin(ORIGINAL, "live?match=27094")
    )

    if not page:
        return results

    soup = BeautifulSoup(page, "html.parser")
    text = clean_name(soup.get_text(" ", strip=True))

    channel = find_channel(text)

    if not channel:
        return results

    commentator = ""

    patterns = [
        r"🎙️?\s*([^🏆📺🎙️]{3,50})",
        r"معلق\s*[:：]?\s*([^،|]{3,50})",
    ]

    for pattern in patterns:
        found = re.search(pattern, text)
        if found:
            commentator = clean_name(found.group(1))
            break

    match = empty_match()
    match["channel"] = channel
    match["commentator"] = commentator

    stats["original"] = 1
    results.append(match)

    log("ORIGINAL: extracted supplied match page")
    return results


# ---------------- ALMASHHAD ----------------

def parse_almashhad():
    results = []

    # This is a dated article, not a daily fixture endpoint.
    # It is retained as an optional source and must not be
    # treated as current after its publication date.
    page = get_page(ALMASHHAD)

    if not page:
        return results

    soup = BeautifulSoup(page, "html.parser")
    text = clean_name(soup.get_text(" ", strip=True))

    if not text:
        return results

    # The article may contain multiple match rows.
    # Only accept rows with a channel and a commentator.
    for line in soup.find_all(["tr", "li", "p"]):
        row = clean_name(line.get_text(" ", strip=True))

        if len(row) < 20:
            continue

        channel = find_channel(row)
        if not channel:
            continue

        results.append({
            "raw": row,
            "channel": channel
        })

    stats["almashhad"] = len(results)
    log(f"ALMASHHAD ROWS: {len(results)}")

    return results


# ---------------- MERGE ----------------

def merge_matches(base, extra):
    for item in extra:
        if not item.get("home") or not item.get("away"):
            continue

        found = None

        for current in base:
            if same_match(current, item):
                found = current
                break

        if found:
            for field in [
                "league", "home_img", "away_img",
                "channel", "commentator", "streamUrl"
            ]:
                if item.get(field) and not found.get(field):
                    found[field] = item[field]

            if item.get("hour"):
                found["hour"] = item["hour"]
                found["time"] = item["hour"]

        else:
            base.append(item)

    return base


def apply_broadcasts(matches):
    if not os.path.exists(BROADCAST_FILE):
        return

    try:
        with open(
            BROADCAST_FILE,
            "r",
            encoding="utf-8"
        ) as f:
            data = json.load(f)

        records = data if isinstance(data, list) else data.get("matches", [])

        for item in matches:
            for manual in records:
                if same_match(item, manual):
                    for field in [
                        "channel",
                        "commentator",
                        "streamUrl"
                    ]:
                        if manual.get(field):
                            item[field] = manual[field]

    except Exception as e:
        log(f"BROADCAST FILE ERROR: {e}")


# ---------------- FINALIZE ----------------

def finalize(matches):
    unique = {}

    for item in matches:
        if not item.get("home") or not item.get("away"):
            continue

        if not item.get("date"):
            item["date"] = datetime.now(TZ).date().isoformat()

        if not item.get("match_date"):
            item["match_date"] = item["date"]

        if not item.get("team1"):
            item["team1"] = item["home"]

        if not item.get("team2"):
            item["team2"] = item["away"]

        if not item.get("time"):
            item["time"] = item.get("hour", "")

        key = match_id(item)

        if key not in unique:
            unique[key] = item
        else:
            old = unique[key]

            for field in [
                "channel", "commentator",
                "streamUrl", "home_img", "away_img"
            ]:
                if item.get(field) and not old.get(field):
                    old[field] = item[field]

    return list(unique.values())


def main():
    start = datetime.now(TZ)

    log("=" * 55)
    log("YALLA KORA V11 START")
    log(f"TIME: {start.isoformat()}")
    log("=" * 55)

    # 1. Main match database.
    matches = fotmob_matches()

    # 2. Broadcast source.
    as_goal = parse_as_goal()

    # 3. Additional match cards.
    talknow = parse_talknow()

    # 4. Match detail pages.
    filgoal = parse_filgoal()

    # 5. Supplied Original TV page.
    original = parse_original()

    # 6. Dated article.
    almashhad = parse_almashhad()

    # Merge only records with identifiable teams.
    matches = merge_matches(matches, as_goal)
    matches = merge_matches(matches, talknow)
    matches = merge_matches(matches, filgoal)

    # Original TV supplied page has no reliable team names
    # in the indexed page, so do not attach it to random games.

    apply_broadcasts(matches)

    matches = finalize(matches)

    today = datetime.now(TZ).date()
    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=1)

    today_matches = [
        m for m in matches
        if m.get("date") == today.isoformat()
    ]

    yesterday_matches = [
        m for m in matches
        if m.get("date") == yesterday.isoformat()
    ]

    tomorrow_matches = [
        m for m in matches
        if m.get("date") == tomorrow.isoformat()
    ]

    with_channel = sum(
        1 for m in matches if m.get("channel")
    )

    with_commentator = sum(
        1 for m in matches if m.get("commentator")
    )

    output = {
        "version": "V11",
        "updated_at": datetime.now(TZ).isoformat(),
        "timezone": "Asia/Baghdad",
        "source": "Yalla Kora Multi Source Engine",
        "matches": matches,
        "today": today_matches,
        "yesterday": yesterday_matches,
        "tomorrow": tomorrow_matches,
        "counts": {
            "total": len(matches),
            "today": len(today_matches),
            "yesterday": len(yesterday_matches),
            "tomorrow": len(tomorrow_matches),
            "with_channel": with_channel,
            "with_commentator": with_commentator,
        },
        "sources": stats,
    }

    temp_file = OUTPUT_FILE + ".tmp"

    with open(
        temp_file,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            output,
            f,
            ensure_ascii=False,
            indent=2
        )

    os.replace(temp_file, OUTPUT_FILE)

    log("=" * 55)
    log("V11 FINISHED")
    log(f"TODAY: {len(today_matches)}")
    log(f"YESTERDAY: {len(yesterday_matches)}")
    log(f"TOMORROW: {len(tomorrow_matches)}")
    log(f"TOTAL: {len(matches)}")
    log(f"WITH CHANNEL: {with_channel}")
    log(f"WITH COMMENTATOR: {with_commentator}")
    log(f"SOURCE STATS: {json.dumps(stats, ensure_ascii=False)}")
    log(f"OUTPUT: {OUTPUT_FILE}")
    log("=" * 55)


if __name__ == "__main__":
    main()
