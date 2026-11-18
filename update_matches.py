#!/usr/bin/env python3
# YALLA KORA V24 - MULTI SOURCE + ARABIC METADATA
# Existing JSON fields preserved.
# No guessed channels, commentators, or unsafe match joins.

import json
import re
import time
import html
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from difflib import SequenceMatcher

import requests
from bs4 import BeautifulSoup

TZ = ZoneInfo("Asia/Baghdad")
NOW = datetime.now(TZ)
DATES = [NOW.date() + timedelta(days=i) for i in (-1, 0, 1)]
DATE_SET = {d.isoformat() for d in DATES}

OUTPUT = Path("matches.json")
TIMEOUT = 25

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 10) "
        "AppleWebKit/537.36 Chrome/130.0.0.0 Mobile Safari/537.36"
    ),
    "Accept": "text/html,application/json,*/*",
    "Accept-Language": "ar,en-US;q=0.9",
}

session = requests.Session()
session.headers.update(HEADERS)

ESPN_LEAGUES = [
    "eng.1", "eng.2", "eng.3", "esp.1", "ger.1",
    "ita.1", "fra.1", "ned.1", "por.1", "bel.1",
    "tur.1", "sco.1", "usa.1", "mex.1", "arg.1",
    "bra.1", "aus.1", "ksa.1", "uefa.champions",
    "uefa.europa", "uefa.europa.conf",
    "uefa.nations", "fifa.world", "fifa.friendly",
]

ARABIC_SOURCES = [
    "https://elgoal.net/broadcasting-channels-today-matches/",
    "https://almaghrebsport.com/commentators/",
]

STATS = {
    "espn": {"ok": 0, "failed": 0},
    "fotmob": {"ok": 0, "failed": 0},
    "arabic_sources": {"checked": 0, "rows": 0, "matched": 0},
    "broadcast": {"found": 0},
    "commentators": {"found": 0},
    "localization": {"teams": 0, "leagues": 0},
    "errors": [],
}


# ---------------------------------------------------------
# Arabic names and aliases
# Add more teams here without changing the app.
# ---------------------------------------------------------

TEAM_GROUPS = {
    "الهلال": [
        "al hilal", "al-hilal", "hilal", "الهلال",
    ],
    "النصر": [
        "al nassr", "al-nassr", "alnasr", "النصر",
    ],
    "الاتحاد": [
        "al ittihad", "al-itihad", "ittihad", "الاتحاد",
    ],
    "الأهلي": [
        "al ahli", "al-ahli", "alahli", "الأهلي",
    ],
    "الشباب": [
        "al shabab", "al-shabab", "الشباب",
    ],
    "العين": [
        "al ain", "al-ain", "العين",
    ],
    "السد": [
        "al sadd", "al-sadd", "السد",
    ],
    "الدحيل": [
        "al duhail", "al-duhail", "الدحيل",
    ],
    "الشرطة": [
        "al shorta", "al-shorta", "الشرطة",
    ],
    "القوة الجوية": [
        "al quwa al jawiya", "al quwa", "القوة الجوية",
    ],
    "الزوراء": [
        "al zawraa", "al-zawraa", "الزوراء",
    ],
    "الطلبة": [
        "al talab", "al-talaba", "الطلبة",
    ],
    "أربيل": [
        "erbil", "arbil", "اربيل", "أربيل",
    ],
    "برشلونة": [
        "barcelona", "fc barcelona", "برشلونة",
    ],
    "ريال مدريد": [
        "real madrid", "ريال مدريد",
    ],
    "أتلتيكو مدريد": [
        "atletico madrid", "atlético madrid", "اتلتيكو مدريد",
    ],
    "مانشستر سيتي": [
        "manchester city", "man city", "مانشستر سيتي",
    ],
    "مانشستر يونايتد": [
        "manchester united", "man utd", "مانشستر يونايتد",
    ],
    "ليفربول": [
        "liverpool", "ليفربول",
    ],
    "أرسنال": [
        "arsenal", "ارسنال", "أرسنال",
    ],
    "تشيلسي": [
        "chelsea", "تشيلسي",
    ],
    "توتنهام": [
        "tottenham", "tottenham hotspur", "توتنهام",
    ],
    "بايرن ميونخ": [
        "bayern munich", "bayern", "بايرن ميونخ",
    ],
    "بوروسيا دورتموند": [
        "borussia dortmund", "dortmund", "بوروسيا دورتموند",
    ],
    "باريس سان جيرمان": [
        "paris saint germain", "paris sg", "psg",
        "باريس سان جيرمان",
    ],
    "يوفنتوس": [
        "juventus", "يوفنتوس",
    ],
    "إنتر ميلان": [
        "inter milan", "internazionale", "انتر ميلان",
    ],
    "ميلان": [
        "ac milan", "milan", "ميلان",
    ],
    "روما": [
        "as roma", "roma", "روما",
    ],
    "نابولي": [
        "napoli", "نابولي",
    ],
    "أياكس": [
        "ajax", "اياكس", "أياكس",
    ],
    "بنفيكا": [
        "benfica", "بنفيكا",
    ],
    "بورتو": [
        "porto", "بورتو",
    ],
    "سبورتينغ لشبونة": [
        "sporting cp", "sporting lisbon", "سبورتينغ لشبونة",
    ],
    "منتخب العراق": [
        "iraq", "iraq national team", "العراق", "منتخب العراق",
    ],
    "منتخب السعودية": [
        "saudi arabia", "saudi arabia national team", "السعودية",
    ],
    "منتخب قطر": [
        "qatar", "qatar national team", "قطر",
    ],
    "منتخب الإمارات": [
        "uae", "united arab emirates", "الامارات", "الإمارات",
    ],
    "منتخب مصر": [
        "egypt", "egypt national team", "مصر",
    ],
    "منتخب المغرب": [
        "morocco", "morocco national team", "المغرب",
    ],
    "منتخب الجزائر": [
        "algeria", "algeria national team", "الجزائر",
    ],
    "منتخب تونس": [
        "tunisia", "tunisia national team", "تونس",
    ],
    "منتخب الأردن": [
        "jordan", "jordan national team", "الاردن", "الأردن",
    ],
    "منتخب اليابان": [
        "japan", "japan national team", "اليابان",
    ],
    "منتخب كوريا الجنوبية": [
        "south korea", "korea republic", "كوريا الجنوبية",
    ],
    "منتخب البرازيل": [
        "brazil", "brazil national team", "البرازيل",
    ],
    "منتخب الأرجنتين": [
        "argentina", "argentina national team", "الأرجنتين",
    ],
    "منتخب فرنسا": [
        "france", "france national team", "فرنسا",
    ],
    "منتخب إنجلترا": [
        "england", "england national team", "إنجلترا",
    ],
    "منتخب إسبانيا": [
        "spain", "spain national team", "اسبانيا", "إسبانيا",
    ],
    "منتخب ألمانيا": [
        "germany", "germany national team", "ألمانيا",
    ],
}

TEAM_LOOKUP = {}

for arabic_name, aliases in TEAM_GROUPS.items():
    for alias in aliases + [arabic_name]:
        TEAM_LOOKUP[alias] = arabic_name


LEAGUE_MAP = [
    (("premier league", "english premier"), "الدوري الإنجليزي الممتاز"),
    (("la liga", "laliga", "spanish primera"), "الدوري الإسباني"),
    (("bundesliga",), "الدوري الألماني"),
    (("serie a", "italian serie"), "الدوري الإيطالي"),
    (("ligue 1",), "الدوري الفرنسي"),
    (("eredivisie",), "الدوري الهولندي"),
    (("champions league",), "دوري أبطال أوروبا"),
    (("europa league",), "الدوري الأوروبي"),
    (("conference league",), "دوري المؤتمر الأوروبي"),
    (("saudi pro league", "saudi league"), "الدوري السعودي"),
    (("iraqi stars league", "iraq stars league"), "دوري نجوم العراق"),
    (("iraqi premier", "iraq premier"), "الدوري العراقي"),
    (("qatar stars league",), "الدوري القطري"),
    (("egyptian premier", "egypt league"), "الدوري المصري"),
    (("world cup",), "كأس العالم"),
    (("africa cup of nations",), "كأس أمم أفريقيا"),
    (("friendly", "friendlies"), "مباريات ودية"),
]


# ---------------------------------------------------------
# Common helpers
# ---------------------------------------------------------

def clean(value):
    value = html.unescape(str(value or ""))
    return re.sub(r"\s+", " ", value).strip(" \t\r\n|•·")


def norm(value):
    value = clean(value).lower()
    value = value.replace("أ", "ا").replace("إ", "ا")
    value = value.replace("آ", "ا").replace("ى", "ي")
    value = value.replace("ة", "ه")
    value = re.sub(r"[ًٌٍَُِّْـ]", "", value)
    return re.sub(r"[^a-z0-9\u0600-\u06ff]", "", value)


def unique(values):
    result = []
    seen = set()

    for value in values or []:
        value = clean(value)
        key = norm(value)

        if value and key and key not in seen:
            seen.add(key)
            result.append(value)

    return result


def get_response(url, params=None):
    response = session.get(
        url, params=params, timeout=TIMEOUT
    )
    response.raise_for_status()
    return response


def get_json(url, params=None):
    return get_response(url, params).json()


def parse_dt(value):
    if not value:
        return None

    try:
        dt = datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(TZ)

    except (TypeError, ValueError):
        return None


def arabic_team(name):
    name = clean(name)
    key = norm(name)

    if key in TEAM_LOOKUP:
        return TEAM_LOOKUP[key]

    # Do not transliterate unknown names automatically.
    return name


def arabic_league(name):
    original = clean(name)
    low = original.lower()

    for keys, arabic in LEAGUE_MAP:
        if any(k in low for k in keys):
            return arabic

    return original


def parse_status(raw="", completed=False, state=""):
    value = (clean(raw) + " " + clean(state)).lower()

    if completed or state.lower() == "post":
        return "ended"

    if any(x in value for x in (
        "final", "full time", "ended", "finished", "انتهت"
    )):
        return "ended"

    if state.lower() == "in" or any(x in value for x in (
        "in progress", "live", "half", "مباشر", "استراحة"
    )):
        return "live"

    return "upcoming"


def make_row(
    home, away, league, kickoff,
    status="upcoming", score="VS",
    home_img="", away_img="",
    event_id="", source=""
):
    home = clean(home)
    away = clean(away)

    return {
        "league": arabic_league(league),
        "home": arabic_team(home),
        "away": arabic_team(away),
        "team1": arabic_team(home),
        "team2": arabic_team(away),
        "home_img": clean(home_img),
        "away_img": clean(away_img),
        "hour": kickoff.strftime("%H:%M"),
        "time": kickoff.strftime("%H:%M"),
        "date": kickoff.date().isoformat(),
        "match_date": kickoff.date().isoformat(),
        "status": status,
        "score": clean(score) or "VS",
        "channel": "",
        "channels": [],
        "commentator": "",
        "commentators": [],
        "streamUrl": "",
        "_event_id": str(event_id or ""),
        "_source": source,
    }


# ---------------------------------------------------------
# ESPN fixtures
# ---------------------------------------------------------

def parse_espn(day, league_id):
    url = (
        "https://site.api.espn.com/apis/site/v2/"
        f"sports/soccer/{league_id}/scoreboard"
    )

    data = get_json(url, {
        "dates": day.strftime("%Y%m%d"),
        "limit": 500,
    })

    rows = []
    league_name = (
        (data.get("leagues") or [{}])[0].get("name")
        or league_id
    )

    for event in data.get("events", []):
        kickoff = parse_dt(event.get("date"))
        competitions = event.get("competitions") or []
        comp = competitions[0] if competitions else {}
        teams = comp.get("competitors") or []

        home = next(
            (x for x in teams if x.get("homeAway") == "home"),
            None,
        )
        away = next(
            (x for x in teams if x.get("homeAway") == "away"),
            None,
        )

        if (not home or not away) and len(teams) >= 2:
            home, away = teams[0], teams[1]

        if not kickoff or not home or not away:
            continue

        ht = home.get("team") or {}
        at = away.get("team") or {}

        home_name = ht.get("displayName") or ht.get("name")
        away_name = at.get("displayName") or at.get("name")

        if not home_name or not away_name:
            continue

        status = comp.get("status") or event.get("status") or {}
        typ = status.get("type") or {}

        hs = home.get("score")
        aws = away.get("score")
        score = (
            f"{hs} - {aws}"
            if hs not in (None, "") and aws not in (None, "")
            else "VS"
        )

        rows.append(make_row(
            home_name,
            away_name,
            league_name,
            kickoff,
            parse_status(
                typ.get("description"),
                typ.get("completed", False),
                typ.get("state", ""),
            ),
            score,
            ht.get("logo", ""),
            at.get("logo", ""),
            event.get("id", ""),
            "espn",
        ))

    return rows


# ---------------------------------------------------------
# FotMob fixtures
# ---------------------------------------------------------

def parse_fotmob(day):
    urls = [
        "https://www.fotmob.com/api/data/matches",
        "https://www.fotmob.com/api/matches",
    ]

    data = None

    for url in urls:
        try:
            data = get_json(url, {
                "date": day.strftime("%Y%m%d"),
                "ccode3": "IRQ",
            })
            break
        except Exception:
            continue

    if not isinstance(data, dict):
        raise RuntimeError("FotMob endpoint unavailable")

    rows = []

    for league in data.get("leagues", []):
        for match in league.get("matches", []):
            home = match.get("home") or {}
            away = match.get("away") or {}
            status = match.get("status") or {}

            kickoff = parse_dt(
                status.get("utcTime")
                or match.get("utcTime")
                or match.get("kickoff")
            )

            home_name = home.get("name") or home.get("shortName")
            away_name = away.get("name") or away.get("shortName")

            if not kickoff or not home_name or not away_name:
                continue

            hs = home.get("score")
            aws = away.get("score")
            score = (
                f"{hs} - {aws}"
                if hs is not None and aws is not None
                else "VS"
            )

            home_id = home.get("id")
            away_id = away.get("id")

            home_img = (
                f"https://images.fotmob.com/image_resources/"
                f"logo/teamlogo/{home_id}.png"
                if home_id else ""
            )
            away_img = (
                f"https://images.fotmob.com/image_resources/"
                f"logo/teamlogo/{away_id}.png"
                if away_id else ""
            )

            rows.append(make_row(
                home_name,
                away_name,
                league.get("name") or league.get("title"),
                kickoff,
                parse_status(
                    status.get("reason") or status.get("description"),
                    status.get("finished", False),
                    status.get("state", ""),
                ),
                score,
                home_img,
                away_img,
                match.get("id", ""),
                "fotmob",
            ))

    return rows


# ---------------------------------------------------------
# Arabic source parsing
# ---------------------------------------------------------

def parse_source_time(value, day):
    value = clean(value)
    value = value.translate(str.maketrans(
        "٠١٢٣٤٥٦٧٨٩", "0123456789"
    ))

    match = re.search(
        r"(\d{1,2})\s*[:٫.]\s*(\d{2})\s*([ممصص])?",
        value,
    )

    if not match:
        return None

    hour = int(match.group(1))
    minute = int(match.group(2))
    marker = match.group(3) or ""

    if hour > 23 or minute > 59:
        return None

    if marker in ("م", "م"):
        if hour < 12:
            hour += 12
    elif marker in ("ص", "ص"):
        if hour == 12:
            hour = 0

    hour %= 24

    return datetime(
        day.year, day.month, day.day,
        hour, minute, tzinfo=TZ,
    )


def is_unannounced(value):
    value = norm(value)

    return (
        not value
        or "لميعن" in value
        or "لمتعلن" in value
        or "غيرمعلن" in value
        or "tba" == value
        or "unknown" == value
    )


def extract_row_from_cells(cells, day, league=""):
    values = [clean(x) for x in cells]
    values = [x for x in values if x]

    if len(values) < 4:
        return None

    time_index = None
    kickoff = None

    for i, value in enumerate(values):
        parsed = parse_source_time(value, day)
        if parsed:
            time_index = i
            kickoff = parsed
            break

    if time_index is None:
        return None

    # Most common table layout:
    # competition | home | time | away | commentator | channel
    # or home | time | away | commentator | channel
    if time_index == 2 and len(values) >= 4:
        home = values[1]
        away = values[3]
        extra = values[4:]
    elif time_index == 1 and len(values) >= 3:
        home = values[0]
        away = values[2]
        extra = values[3:]
    else:
        return None

    if not home or not away:
        return None

    commentator = ""
    channel = ""

    # Use explicit cells only. Never infer rights from league.
    if len(extra) >= 2:
        commentator = extra[0]
        channel = extra[1]
    elif len(extra) == 1:
        candidate = extra[0]
        if any(x in candidate.lower() for x in (
            "sport", "bein", "ssc", "on time", "الكأس",
            "الكاس", "أون", "ابوظبي", "أبوظبي", "ثمانية",
        )):
            channel = candidate
        else:
            commentator = candidate

    if is_unannounced(commentator):
        commentator = ""

    if is_unannounced(channel):
        channel = ""

    return {
        "home": home,
        "away": away,
        "league": clean(league),
        "kickoff": kickoff,
        "channel": channel,
        "commentator": commentator,
        "source": "arabic_web",
    }


def parse_arabic_page(url, day):
    response = get_response(url)
    soup = BeautifulSoup(response.text, "html.parser")

    found = []

    # First: real HTML tables, using each row independently.
    for table in soup.find_all("table"):
        current_league = ""

        for row in table.find_all("tr"):
            cells = [
                cell.get_text(" ", strip=True)
                for cell in row.find_all(["th", "td"])
            ]

            if not cells:
                continue

            if len(cells) == 1:
                current_league = cells[0]
                continue

            parsed = extract_row_from_cells(
                cells, day, current_league
            )

            if parsed:
                found.append(parsed)

    # Second: common match-card layouts used by WordPress themes.
    selectors = [
        ".match-row", ".match-item", ".match-card",
        ".fixture", ".fixture-row", ".event-row",
        ".match", ".game-row",
    ]

    for selector in selectors:
        for node in soup.select(selector):
            cells = [
                x.get_text(" ", strip=True)
                for x in node.find_all(
                    ["td", "span", "strong", "a", "div"],
                    recursive=True,
                )
            ]

            parsed = extract_row_from_cells(cells, day)

            if parsed:
                found.append(parsed)

    # Remove duplicates.
    unique_rows = []
    seen = set()

    for row in found:
        key = (
            norm(row["home"]),
            norm(row["away"]),
            row["kickoff"].strftime("%Y-%m-%d %H:%M"),
        )

        if key not in seen:
            seen.add(key)
            unique_rows.append(row)

    return unique_rows


def fetch_arabic_data():
    all_rows = []

    for day in [NOW.date()]:
        for url in ARABIC_SOURCES:
            STATS["arabic_sources"]["checked"] += 1

            try:
                rows = parse_arabic_page(url, day)
                all_rows.extend(rows)
                STATS["arabic_sources"]["rows"] += len(rows)

                print(
                    "ARABIC SOURCE OK:",
                    url,
                    "rows:",
                    len(rows),
                )

            except Exception as error:
                if len(STATS["errors"]) < 30:
                    STATS["errors"].append(
                        f"Arabic source {url}: {error}"
                    )

    return all_rows


# ---------------------------------------------------------
# Safe match matching
