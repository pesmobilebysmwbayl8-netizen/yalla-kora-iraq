
#!/usr/bin/env python3
# YALLA KORA V25 - Arabic Multi-Source Engine
# Safe metadata matching. Never invent channels or commentators.

import json
import re
import html
import time
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

TZ = ZoneInfo("Asia/Baghdad")
NOW = datetime.now(TZ)
DAYS = [NOW.date() + timedelta(days=n) for n in (-1, 0, 1)]
DATE_SET = {d.isoformat() for d in DAYS}

OUT = Path("matches.json")
TIMEOUT = 22

HEADERS = {
    "User-Agent": "Mozilla/5.0 Chrome/128 Safari/537.36",
    "Accept": "text/html,application/json,*/*",
    "Accept-Language": "ar,en-US;q=0.9",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

ESPN_LEAGUES = [
    "eng.1", "eng.2", "esp.1", "ger.1", "ita.1",
    "fra.1", "ned.1", "por.1", "bel.1", "tur.1",
    "sco.1", "usa.1", "mex.1", "arg.1", "bra.1",
    "aus.1", "ksa.1", "uefa.champions",
    "uefa.europa", "uefa.europa.conf",
    "uefa.nations", "fifa.world", "fifa.friendly",
]

ARABIC_SOURCES = [
    "https://elgoal.net/commentators/",
]

NEWS_QUERIES = [
    "جدول مباريات اليوم القنوات الناقلة المعلقين site:winwin.com",
    "جدول مباريات اليوم القنوات الناقلة المعلقين site:kooora.com",
    "جدول مباريات اليوم القنوات الناقلة المعلقين site:elgoal.net",
    "جدول مباريات اليوم القنوات الناقلة المعلقين site:goal.com",
]

ALLOWED_HOSTS = (
    "winwin.com",
    "kooora.com",
    "elgoal.net",
    "goal.com",
)

STATS = {
    "fixtures": {"fotmob": 0, "espn": 0},
    "arabic_sources": {
        "checked": 0,
        "pages_ok": 0,
        "rows": 0,
        "matched": 0,
    },
    "metadata": {
        "with_channel": 0,
        "with_commentator": 0,
    },
    "errors": [],
}

TEAM_ALIASES = {
    "الهلال": ["al hilal", "hilal"],
    "النصر": ["al nassr", "al nasr", "nassr"],
    "الاتحاد": ["al ittihad", "ittihad"],
    "الأهلي": ["al ahli", "ahli"],
    "الشباب": ["al shabab", "shabab"],
    "القادسية": ["al qadsiah", "qadsiah"],
    "العين": ["al ain"],
    "السد": ["al sadd", "sadd"],
    "الدحيل": ["al duhail", "duhail"],
    "الريان": ["al rayyan", "rayyan"],
    "الغرافة": ["al gharafa", "gharafa"],
    "الشرطة": ["al shorta", "al shurta", "shorta"],
    "القوة الجوية": ["al quwa al jawiya", "air force"],
    "الزوراء": ["al zawraa", "zawraa"],
    "الطلبة": ["al talab", "talaba"],
    "أربيل": ["erbil", "arbil"],
    "دهوك": ["duhok", "dohuk"],
    "برشلونة": ["barcelona", "fc barcelona"],
    "ريال مدريد": ["real madrid"],
    "أتلتيكو مدريد": ["atletico madrid"],
    "مانشستر سيتي": ["manchester city", "man city"],
    "مانشستر يونايتد": ["manchester united", "man utd"],
    "ليفربول": ["liverpool"],
    "أرسنال": ["arsenal"],
    "تشيلسي": ["chelsea"],
    "توتنهام": ["tottenham"],
    "بايرن ميونخ": ["bayern munich", "bayern"],
    "بوروسيا دورتموند": ["borussia dortmund", "dortmund"],
    "باريس سان جيرمان": ["paris saint germain", "psg"],
    "يوفنتوس": ["juventus"],
    "إنتر": ["inter milan", "internazionale"],
    "ميلان": ["ac milan", "milan"],
    "روما": ["as roma"],
    "نابولي": ["napoli"],
    "أياكس": ["ajax"],
    "بنفيكا": ["benfica"],
    "بورتو": ["porto"],
    "منتخب العراق": ["iraq", "iraq national team"],
    "منتخب السعودية": ["saudi arabia"],
    "منتخب قطر": ["qatar"],
    "منتخب الإمارات": ["uae", "united arab emirates"],
    "منتخب مصر": ["egypt"],
    "منتخب المغرب": ["morocco"],
    "منتخب الجزائر": ["algeria"],
    "منتخب تونس": ["tunisia"],
    "منتخب الأردن": ["jordan"],
    "منتخب اليابان": ["japan"],
    "منتخب كوريا الجنوبية": ["south korea"],
    "منتخب البرازيل": ["brazil"],
    "منتخب الأرجنتين": ["argentina"],
    "منتخب فرنسا": ["france"],
    "منتخب إنجلترا": ["england"],
    "منتخب إسبانيا": ["spain"],
    "منتخب ألمانيا": ["germany"],
    "منتخب البرتغال": ["portugal"],
    "منتخب هولندا": ["netherlands", "holland"],
    "منتخب إيطاليا": ["italy"],
    "منتخب إيران": ["iran"],
    "منتخب الكويت": ["kuwait"],
    "منتخب البحرين": ["bahrain"],
    "منتخب سوريا": ["syria"],
    "منتخب فلسطين": ["palestine"],
    "منتخب لبنان": ["lebanon"],
    "منتخب أوزبكستان": ["uzbekistan"],
}

def clean(value):
    return re.sub(
        r"\s+",
        " ",
        html.unescape(str(value or ""))
    ).strip(" \t\r\n|•·")

def norm(value):
    value = clean(value).lower()
    value = value.translate(
        str.maketrans("أإآىة", "اااه")
    )
    value = re.sub(r"[ًٌٍَُِّْـ]", "", value)
    return re.sub(
        r"[^a-z0-9\u0600-\u06ff]",
        "",
        value
    )

ALIAS_TO_AR = {}

for arabic, aliases in TEAM_ALIASES.items():
    ALIAS_TO_AR[norm(arabic)] = arabic
    for alias in aliases:
        ALIAS_TO_AR[norm(alias)] = arabic

LEAGUES = [
    (("premier league",), "الدوري الإنجليزي الممتاز"),
    (("la liga", "laliga"), "الدوري الإسباني"),
    (("bundesliga",), "الدوري الألماني"),
    (("serie a",), "الدوري الإيطالي"),
    (("ligue 1",), "الدوري الفرنسي"),
    (("eredivisie",), "الدوري الهولندي"),
    (("champions league",), "دوري أبطال أوروبا"),
    (("europa league",), "الدوري الأوروبي"),
    (("conference league",), "دوري المؤتمر الأوروبي"),
    (("saudi pro league", "saudi league"), "الدوري السعودي"),
    (("iraqi stars league", "iraq stars league"), "دوري نجوم العراق"),
    (("iraqi premier",), "الدوري العراقي"),
    (("qatar stars league",), "الدوري القطري"),
    (("egyptian premier",), "الدوري المصري"),
    (("friendly", "friendlies"), "مباريات ودية"),
    (("world cup",), "كأس العالم"),
]

CHANNEL_WORDS = (
    "bein", "ssc", "on sport", "on time",
    "abu dhabi", "thmanyah", "sports",
    "الكأس", "الكاس", "أون", "اون",
    "أبوظبي", "ابوظبي", "العراقية",
    "الرابعة", "السعودية الرياضية",
    "الأردن الرياضية", "الكويت الرياضية",
    "الشارقة الرياضية", "دبي الرياضية",
    "stc tv", "شاهد",
)

EMPTY_WORDS = (
    "يعلن لاحقا", "لم يعلن", "غير معلن",
    "tba", "unknown", "—", "-"
)

def get(url, params=None):
    response = SESSION.get(
        url,
        params=params,
        timeout=TIMEOUT
    )
    response.raise_for_status()
    return response

def canonical_team(name):
    return ALIAS_TO_AR.get(norm(name), "")

def arabic_league(name):
    low = clean(name).lower()
    for keys, arabic in LEAGUES:
        if any(key in low for key in keys):
            return arabic
    return clean(name)

def parse_dt(value):
    try:
        dt = datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(TZ)
    except Exception:
        return None

def match_status(description="", state="", completed=False):
    value = (
        clean(description) + " " + clean(state)
    ).lower()

    if completed or any(x in value for x in (
        "final", "full time", "ended", "finished", "انتهت"
    )):
        return "ended"

    if any(x in value for x in (
        "in progress", "live", "half",
        "مباشر", "استراحة"
    )):
        return "live"

    return "upcoming"

def make_fixture(
    home, away, league, kickoff,
    status="upcoming", score="VS",
    home_img="", away_img="", source=""
):
    h_ar = canonical_team(home)
    a_ar = canonical_team(away)

    h = h_ar or clean(home)
    a = a_ar or clean(away)

    return {
        "league": arabic_league(league),
        "home": h,
        "away": a,
        "team1": h,
        "team2": a,
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
        "_source": source,
    }

def fetch_fotmob(day):
    data = get(
        "https://www.fotmob.com/api/data/matches",
        {
            "date": day.strftime("%Y%m%d"),
            "ccode3": "IRQ"
        }
    ).json()

    if not isinstance(data, dict):
        raise RuntimeError("FotMob returned invalid data")

    output = []

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

            home_img = (
                "https://images.fotmob.com/image_resources/logo/teamlogo/"
                + str(home.get("id")) + ".png"
                if home.get("id") else ""
            )

            away_img = (
                "https://images.fotmob.com/image_resources/logo/teamlogo/"
                + str(away.get("id")) + ".png"
                if away.get("id") else ""
            )

            output.append(make_fixture(
                home_name,
                away_name,
                league.get("name") or league.get("title"),
                kickoff,
                match_status(
                    status.get("reason") or status.get("description"),
                    status.get("state"),
                    status.get("finished", False)
                ),
                score,
                home_img,
                away_img,
                "fotmob"
            ))

    return output

def fetch_espn(day, league_id):
    url = (
        "https://site.api.espn.com/apis/site/v2/sports/"
        f"soccer/{league_id}/scoreboard"
    )

    data = get(
        url,
        {
            "dates": day.strftime("%Y%m%d"),
            "limit": 500
        }
    ).json()

    league = (
        (data.get("leagues") or [{}])[0].get("name")
        or league_id
    )

    output = []

    for event in data.get("events", []):
        kickoff = parse_dt(event.get("date"))
        competitions = event.get("competitions") or []
        competition = competitions[0] if competitions else {}
        teams = competition.get("competitors") or []

        home = next(
            (x for x in teams if x.get("homeAway") == "home"),
            None
        )
        away = next(
            (x for x in teams if x.get("homeAway") == "away"),
            None
        )

        if (not home or not away) and len(teams) >= 2:
            home, away = teams[0], teams[1]

        if not kickoff or not home or not away:
            continue

        ht = home.get("team") or {}
        at = away.get("team") or {}

        hn = ht.get("displayName") or ht.get("name")
        an = at.get("displayName") or at.get("name")

        if not hn or not an:
            continue

        status = competition.get("status") or event.get("status") or {}
        status_type = status.get("type") or {}

        hs = home.get("score")
        aws = away.get("score")

        score = (
            f"{hs} - {aws}"
            if hs not in (None, "") and aws not in (None, "")
            else "VS"
        )

        output.append(make_fixture(
            hn,
            an,
            league,
            kickoff,
            match_status(
                status_type.get("description"),
                status_type.get("state"),
                status_type.get("completed", False)
            ),
            score,
            ht.get("logo", ""),
            at.get("logo", ""),
            "espn"
        ))

    return output
