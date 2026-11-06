
# ============================================================
# YALLA KORA - FIVE SOURCES ONLY
# Sources:
# 1 TalkNow
# 2 FilGoal
# 3 AS Goal
# 4 Original TV
# 5 Al Mashhad
#
# Output: matches.json
# Timezone: Asia/Baghdad
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

TZ = ZoneInfo("Asia/Baghdad")
TODAY = datetime.now(TZ).date()

OUTPUT = "matches.json"

SOURCES = {
    "talknow": "https://talknow.online/",
    "filgoal": (
        "https://www.filgoal.com/matches/379149/overview/"
        "%D9%85%D8%A8%D8%A7%D8%B1%D8%A7%D8%A9-%D8%A7%D9%84%D8%B2%D9%85%D8%A7%D9%84%D9%83-%D9%85%D8%B5%D8%B1-%D9%84%D9%84%D8%AA%D8%A3%D9%85%D9%8A%D9%86-%D9%81%D9%8A-%D9%83%D8%A3%D8%B3-%D9%85%D8%B5%D8%B1"
    ),
    "asgoal": "https://as-goal.net/commentators-channels/",
    "original": "https://originalpro.online/live?match=27094",
    "almashhad": (
        "https://www.almashhad.com/amp/article/"
        "218257510540304-sports/"
        "563101227576063-%D8%AC%D8%AF%D9%88%D9%84-%D9%85%D9%88%D8%A7%D8%B9%D9%8A%D8%AF-%D9%85%D8%A8%D8%A7%D8%B1%D9%8A%D8%A7%D8%AA-%D8%A7%D9%84%D9%8A%D9%88%D9%85-%D8%A7%D9%84%D8%AC%D9%85%D8%B9%D8%A9-06112026-%D9%85%D8%B9-%D8%A7%D9%84%D9%82%D9%86%D9%88%D8%A7%D8%AA-%D8%A7%D9%84%D9%86%D8%A7%D9%82%D9%84%D8%A9-%D9%88%D8%A7%D9%84%D9%85%D8%B9%D9%84%D9%82%D9%8A%D9%86/"
    )
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 10) "
        "AppleWebKit/537.36 Chrome/130.0 Mobile Safari/537.36"
    ),
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
}

session = requests.Session()
session.headers.update(HEADERS)

stats = {
    "talknow": 0,
    "asgoal": 0,
    "filgoal": 0,
    "original": 0,
    "almashhad": 0,
    "channels": 0,
    "commentators": 0,
    "errors": 0,
}


# ---------------- BASIC FUNCTIONS ----------------

def log(text):
    print(text, flush=True)


def fetch(url):
    try:
        response = session.get(url, timeout=25)
        response.raise_for_status()
        response.encoding = response.apparent_encoding
        return response.text
    except Exception as e:
        stats["errors"] += 1
        log("FETCH ERROR: " + str(e))
        return ""


def clean(value):
    value = html.unescape(str(value or ""))
    value = unicodedata.normalize("NFKC", value)
    value = value.replace("ـ", "")
    return re.sub(r"\s+", " ", value).strip()


def key(value):
    value = clean(value).lower()

    for a, b in {
        "أ": "ا", "إ": "ا", "آ": "ا",
        "ى": "ي", "ة": "ه"
    }.items():
        value = value.replace(a, b)

    return re.sub(r"[^a-z0-9\u0600-\u06ff]", "", value)


def new_match():
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
        "streamUrl": ""
    }


# ---------------- CHANNEL DETECTION ----------------

CHANNELS = [
    "beIN SPORTS", "beIN Sport",
    "بي إن سبورت", "بين سبورت",
    "ON Sport Max", "ON Sport Plus",
    "ON Sport", "أون سبورت",
    "اون سبورت", "أون تايم سبورت",
    "SSC", "اس اس سي",
    "الكأس", "قنوات الكأس",
    "Al-Kass", "STARZPLAY",
    "ستارز بلاي", "MBC شاهد",
    "شاهد", "ثمانية",
    "stc tv", "المغربية الرياضية",
    "دبي الرياضية", "أبوظبي الرياضية",
    "AD Sports", "العراقية الرياضية",
    "الكويت الرياضية", "عمان الرياضية",
    "قناة الرابعة"
]

CHANNEL_PATTERN = re.compile(
    "|".join(
        re.escape(x)
        for x in sorted(CHANNELS, key=len, reverse=True)
    ),
    re.I
)


def get_channel(text):
    found = CHANNEL_PATTERN.search(clean(text))
    return found.group(0) if found else ""


def get_time(text):
    found = re.search(
        r"(?<!\d)([01]?\d|2[0-3]):[0-5]\d(?!\d)",
        text
    )
    return found.group(0) if found else ""


def remove_status(text):
    text = re.sub(
        r"\b(لم تبدأ بعد|لم تبدأ|مباشر الآن|مباشر|انتهت|"
        r"Full time|Live|Upcoming|تأجلت)\b",
        " ",
        text,
        flags=re.I
    )
    text = re.sub(r"\b\d+\s*-\s*\d+\b", " ", text)
    return clean(text)


def arabic_part(text):
    text = clean(text)
    found = re.findall(r"[\u0600-\u06ff][\u0600-\u06ff\s]*", text)

    if found:
        return clean(found[0])

    return text


def make_record(home, away, hour, date, channel="", commentator="", league=""):
    home = clean(home)
    away = clean(away)

    if not home or not away:
        return None

    if len(home) > 65 or len(away) > 65:
        return None

    if key(home) == key(away):
        return None

    item = new_match()
    item["home"] = home
    item["away"] = away
    item["team1"] = home
    item["team2"] = away
    item["hour"] = hour
    item["time"] = hour
    item["date"] = date
    item["match_date"] = date
    item["channel"] = clean(channel)
    item["commentator"] = clean(commentator)
    item["league"] = clean(league)

    return item


# ---------------- GENERIC MATCH CARD PARSER ----------------

def parse_card_text(text, date):
    text = clean(text)

    if len(text) < 15 or len(text) > 700:
        return None

    tm = get_time(text)
    channel_match = CHANNEL_PATTERN.search(text)

    if not tm or not channel_match:
        return None

    time_pos = text.find(tm)
    channel_pos = channel_match.start()

    if channel_pos <= time_pos:
        return None

    before = clean(text[:time_pos])
    after = clean(text[time_pos + len(tm):channel_pos])

    # Remove scores and match status from the away-team side.
    after = remove_status(after)

    # Remove common league names if they are attached to a card.
    league_words = [
        "الدوري الانجليزي", "الدوري الإنجليزي",
        "الدوري الاسباني", "الدوري الإسباني",
        "الدوري الايطالي", "الدوري الإيطالي",
        "الدوري الالماني", "الدوري الألماني",
        "الدوري الفرنسي", "الدوري القطري",
        "الدوري السعودي", "كأس مصر",
        "دوري أبطال أوروبا", "الدوري الأوروبي"
    ]

    for word in league_words:
        before = before.replace(word, "")
        after = after.replace(word, "")

    home = arabic_part(before)
    away = arabic_part(after)

    # Extract the commentator after the channel name.
    tail = clean(text[channel_match.end():])

    # Remove duplicate English channel name where present.
    tail = re.sub(
        r"\b(beIN|SPORTS|Sport|ON|Max|Plus|SSC|HD|MBC|TV|stc)\b",
        " ",
        tail,
        flags=re.I
    )

    tail = remove_status(tail)

    commentator = arabic_part(tail)

    # Do not treat a competition name as a commentator.
    if any(x in commentator for x in league_words):
        commentator = ""

    return make_record(
        home, away, tm, date,
        channel_match.group(0),
        commentator
    )


def extract_cards(soup, date):
    found = {}

    # Smallest likely match-card elements first.
    tags = soup.find_all([
        "a", "article", "li",
        "div", "tr"
    ])

    for tag in tags:
        text = clean(tag.get_text(" ", strip=True))

        item = parse_card_text(text, date)
        if not item:
            continue

        identity = (
            key(item["home"]),
            key(item["away"]),
            item["hour"],
            item["date"]
        )

        if identity not in found:
            found[identity] = item

    return list(found.values())


# ---------------- SOURCE 1: TALK NOW ----------------

def parse_talknow():
    log("SOURCE: TALK NOW")

    page = fetch(SOURCES["talknow"])
    if not page:
        return []

    soup = BeautifulSoup(page, "html.parser")

    # The homepage is the current-day match list.
    records = extract_cards(
        soup,
        TODAY.isoformat()
    )

    stats["talknow"] = len(records)
    log("TALKNOW MATCHES: " + str(len(records)))

    return records


# ---------------- SOURCE 2: AS GOAL ----------------

def parse_asgoal():
    log("SOURCE: AS GOAL")

    page = fetch(SOURCES["asgoal"])
    if not page:
        return []

    soup = BeautifulSoup(page, "html.parser")

    records = []
    current_date = TODAY.isoformat()

    # Read page elements in their displayed order.
    for tag in soup.find_all([
        "h1", "h2", "h3", "h4",
        "a", "article", "li"
    ]):
        text = clean(tag.get_text(" ", strip=True))

        # Detect English date headings such as:
        # Friday 6 November 2026
        date_found = re.search(
            r"\b\d{1,2}\s+"
            r"(January|February|March|April|May|June|"
            r"July|August|September|October|November|December)"
            r"\s+\d{4}\b",
            text,
            re.I
        )

        if date_found:
            try:
                dt = datetime.strptime(
                    date_found.group(0),
                    "%d %B %Y"
                )
                current_date = dt.date().isoformat()
            except ValueError:
                pass

        item = parse_card_text(text, current_date)

        if item:
            records.append(item)

    unique = {}

    for item in records:
        identity = (
            key(item["home"]),
            key(item["away"]),
            item["hour"],
            item["date"]
        )
        unique[identity] = item

    records = list(unique.values())

    stats["asgoal"] = len(records)
    log("AS GOAL MATCHES: " + str(len(records)))

    return records


# ---------------- SOURCE 3: FILGOAL ----------------

def parse_filgoal():
    log("SOURCE: FILGOAL")

    page = fetch(SOURCES["filgoal"])
    if not page:
        return []

    soup = BeautifulSoup(page, "html.parser")
    title = clean(
        soup.title.get_text(" ", strip=True)
        if soup.title else ""
    )

    # Example title:
    # مباراة فريقي الزمالك و مصر للتأمين في بطولة كأس مصر
    teams = re.search(
        r"مباراة فريقي\s+(.+?)\s+و\s+(.+?)\s+في بطولة",
        title
    )

    if not teams:
        log("FILGOAL: team names not found")
        return []

    text = clean(soup.get_text(" ", strip=True))

    channel = get_channel(text)

    if not channel:
        log("FILGOAL: channel not found")
        return []

    # Extract the actual match date from the page.
    date = TODAY.isoformat()

    date_match = re.search(
        r"(\d{1,2})\s+"
        r"(يناير|فبراير|مارس|أبريل|مايو|يونيو|يوليو|"
        r"أغسطس|سبتمبر|أكتوبر|نوفمبر|ديسمبر)\s+(\d{4})",
        text
    )

    months = {
        "يناير": 1, "فبراير": 2, "مارس": 3,
        "أبريل": 4, "مايو": 5, "يونيو": 6,
        "يوليو": 7, "أغسطس": 8, "سبتمبر": 9,
        "أكتوبر": 10, "نوفمبر": 11, "ديسمبر": 12
    }

    if date_match:
        try:
            date = datetime(
                int(date_match.group(3)),
                months[date_match.group(2)],
                int(date_match.group(1))
            ).date().isoformat()
        except Exception:
            pass

    tm = get_time(text)

    # Do not guess between multiple commentator names.
    commentator = ""

    record = make_record(
        teams.group(1),
        teams.group(2),
        tm,
        date,
        channel,
        commentator,
        "كأس مصر"
    )

    stats["filgoal"] = 1 if record else 0
    log("FILGOAL DETAILS: " + str(stats["filgoal"]))

    return [record] if record else []


# ---------------- SOURCE 4: ORIGINAL TV ----------------

def parse_original():
    log("SOURCE: ORIGINAL TV")

    page = fetch(SOURCES["original"])
    if not page:
        return []

    soup = BeautifulSoup(page, "html.parser")
    text = clean(soup.get_text(" ", strip=True))

    # The supplied URL identifies one match only.
    # If the page does not expose real team names,
    # do not attach its channel/commentator to another match.
    channel = get_channel(text)

    commentator = ""

    found = re.search(
        r"🎙️?\s*([^🏆📺]{3,60})",
        text
    )

    if found:
        commentator = clean(found.group(1))

    home = ""
    away = ""

    # Do not accept generic placeholders.
    if "الفريق المضيف" in text or "الفريق الضيف" in text:
        log("ORIGINAL: page has generic team placeholders; skipped")
        stats["original"] = 0
        return []

    record = make_record(
        home,
        away,
        "",
        TODAY.isoformat(),
        channel,
        commentator
    )

    stats["original"] = 1 if record else 0
    return [record] if record else []


# ---------------- SOURCE 5: AL MASHHAD ----------------

def parse_almashhad():
    log("SOURCE: AL MASHHAD")

    page = fetch(SOURCES["almashhad"])
    if not page:
        return []

    soup = BeautifulSoup(page, "html.parser")

    # The URL/article is dated 06-11-2026.
    date = TODAY.isoformat()

    date_in_url = re.search(
        r"(\d{2})(\d{2})(\d{4})",
        SOURCES["almashhad"]
    )

    if date_in_url:
        try:
            date = datetime(
                int(date_in_url.group(3)),
                int(date_in_url.group(2)),
                int(date_in_url.group(1))
            ).date().isoformat()
        except Exception:
            pass

    records = []

    for row in soup.find_all("tr"):
        cells = [
            clean(cell.get_text(" ", strip=True))
            for cell in row.find_all(["td", "th"])
        ]

        if len(cells) < 7:
            continue

        # Expected columns:
        # competition, match, Egypt time, Saudi time,
        # UAE time, channel, commentator
        league = cells[0]
        match_text = cells[1]
        saudi_time = cells[3]
        channel = cells[5]
        commentator = cells[6]

        teams = re.split(
            r"\s+(?:-|–|—|vs\.?)\s+",
            match_text,
            maxsplit=1,
            flags=re.I
        )

        if len(teams) != 2:
            continue

        tm = get_time(saudi_time)

        if not tm:
            continue

        if commentator in ["-", "—", ""]:
            commentator = ""

        record = make_record(
            teams[0],
            teams[1],
            tm,
            date,
            channel,
            commentator,
            league
        )

        if record:
            records.append(record)

    stats["almashhad"] = len(records)
    log("AL MASHHAD MATCHES: " + str(len(records)))

    return records


# ---------------- MATCH MATCHING ----------------

def same_match(a, b):
    if a["date"] != b["date"]:
        return False

    ah, aa = key(a["home"]), key(a["away"])
    bh, ba = key(b["home"]), key(b["away"])

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


def merge(records, extra):
    for item in extra:
        if not item.get("home") or not item.get("away"):
            continue

        existing = None

        for current in records:
            if same_match(current, item):
                existing = current
                break

        if existing:
            for field in [
                "channel",
                "commentator",
                "league",
                "home_img",
                "away_img"
            ]:
                if item.get(field) and not existing.get(field):
                    existing[field] = item[field]

            if item.get("hour"):
                existing["hour"] = item["hour"]
                existing["time"] = item["hour"]

        else:
            records.append(item)

    return records


# ---------------- MAIN ----------------

def main():
    log("=" * 50)
    log("YALLA KORA - FIVE SOURCES")
    log("TIME: " + datetime.now(TZ).isoformat())
    log("=" * 50)

    # Daily match lists.
    talknow = parse_talknow()
    asgoal = parse_asgoal()

    # Specific match details / dated article.
    filgoal = parse_filgoal()
    original = parse_original()
    almashhad = parse_almashhad()

    # Start with the two daily sources.
    matches = []

    matches = merge(matches, talknow)
    matches = merge(matches, asgoal)

    # Enrich matching games only.
    matches = merge(matches, filgoal)
    matches = merge(matches, original)
    matches = merge(matches, almashhad)

    # Sort by date and kickoff time.
    matches.sort(
        key=lambda x: (
            x.get("date", ""),
            x.get("hour", "")
        )
    )

    today = TODAY.isoformat()
    yesterday = (TODAY - timedelta(days=1)).isoformat()
    tomorrow = (TODAY + timedelta(days=1)).isoformat()

    today_matches = [
        x for x in matches if x["date"] == today
    ]

    yesterday_matches = [
        x for x in matches if x["date"] == yesterday
    ]

    tomorrow_matches = [
        x for x in matches if x["date"] == tomorrow
    ]

    stats["channels"] = sum(
        1 for x in matches if x.get("channel")
    )

    stats["commentators"] = sum(
        1 for x in matches if x.get("commentator")
    )

    output = {
        "version": "V11-FIVE-SOURCES",
        "updated_at": datetime.now(TZ).isoformat(),
        "timezone": "Asia/Baghdad",
        "matches": matches,
        "today": today_matches,
        "yesterday": yesterday_matches,
        "tomorrow": tomorrow_matches,
        "counts": {
            "total": len(matches),
            "today": len(today_matches),
            "yesterday": len(yesterday_matches),
            "tomorrow": len(tomorrow_matches),
            "with_channel": stats["channels"],
            "with_commentator": stats["commentators"]
        },
        "sources": stats
    }

    temp = OUTPUT + ".tmp"

    with open(temp, "w", encoding="utf-8") as f:
        json.dump(
            output,
            f,
            ensure_ascii=False,
            indent=2
        )

    os.replace(temp, OUTPUT)

    log("=" * 50)
    log("FINISHED")
    log("TODAY: " + str(len(today_matches)))
    log("YESTERDAY: " + str(len(yesterday_matches)))
    log("TOMORROW: " + str(len(tomorrow_matches)))
    log("TOTAL: " + str(len(matches)))
    log("WITH CHANNEL: " + str(stats["channels"]))
    log("WITH COMMENTATOR: " + str(stats["commentators"]))
    log("SOURCE STATS: " + json.dumps(stats, ensure_ascii=False))
    log("=" * 50)


if __name__ == "__main__":
    main()
