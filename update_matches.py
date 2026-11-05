# -*- coding: utf-8 -*-
# YALLA KORA MULTI SEARCH ENGINE V7
# Requirements: pip install requests

import json
import os
import re
import sys
import time
import html
import tempfile
import unicodedata
import xml.etree.ElementTree as ET

from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from html.parser import HTMLParser
from urllib.parse import urlparse

import requests


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "matches.json"
BROADCASTS_FILE = ROOT / "broadcasts.json"

BASE_URL = "https://www.fotmob.com/api/data"
TZ = ZoneInfo("Asia/Baghdad")
COUNTRY_CODE = "IRQ"

DAYS = (-1, 0, 1)
TIMEOUT = 30
SEARCH_LIMIT = 5
DELAY = 1.0

SOURCES = [
    "https://www.satzone.net/?id=2026&view=home",
    "https://go11.io/channels",
]

session = requests.Session()

session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 10) "
        "AppleWebKit/537.36 Chrome/120.0 Mobile Safari/537.36"
    ),
    "Accept": "text/html,application/json,application/rss+xml,*/*",
    "Accept-Language": "ar-IQ,ar;q=0.9,en;q=0.5"
})


TEAM_AR = {
    "manchester city": "مانشستر سيتي",
    "manchester united": "مانشستر يونايتد",
    "liverpool": "ليفربول",
    "arsenal": "أرسنال",
    "chelsea": "تشيلسي",
    "tottenham": "توتنهام",
    "newcastle": "نيوكاسل",
    "real madrid": "ريال مدريد",
    "barcelona": "برشلونة",
    "atletico madrid": "أتلتيكو مدريد",
    "bayern munich": "بايرن ميونخ",
    "borussia dortmund": "بوروسيا دورتموند",
    "paris saint-germain": "باريس سان جيرمان",
    "psg": "باريس سان جيرمان",
    "inter milan": "إنتر ميلان",
    "ac milan": "ميلان",
    "juventus": "يوفنتوس",
    "napoli": "نابولي",
    "al hilal": "الهلال",
    "al nassr": "النصر",
    "al ittihad": "الاتحاد",
    "al ahli": "الأهلي",
    "al shabab": "الشباب",
    "al sadd": "السد",
    "al duhail": "الدحيل",
    "al shorta": "الشرطة",
    "al quwa al jawiya": "القوة الجوية",
    "al zawraa": "الزوراء",
    "iraqi stars league": "دوري نجوم العراق",
    "saudi pro league": "دوري روشن السعودي",
    "premier league": "الدوري الإنجليزي الممتاز",
    "la liga": "الدوري الإسباني",
    "serie a": "الدوري الإيطالي",
    "bundesliga": "الدوري الألماني",
    "ligue 1": "الدوري الفرنسي",
    "champions league": "دوري أبطال أوروبا",
    "europa league": "الدوري الأوروبي",
}


CHANNEL_AR = {
    "bein sports": "بي إن سبورتس",
    "bein": "بي إن سبورتس",
    "ssc": "إس إس سي",
    "alkass": "قنوات الكأس",
    "al kass": "قنوات الكأس",
    "abu dhabi sports": "أبوظبي الرياضية",
    "iraqia sport": "العراقية الرياضية",
    "iraqia sports": "العراقية الرياضية",
    "al rabiaa": "الرابعة الرياضية",
    "alrabiaa": "الرابعة الرياضية",
    "thmanyah": "ثمانية",
    "al thmanyah": "ثمانية",
    "dubai sports": "دبي الرياضية",
    "kuwait sports": "الكويت الرياضية",
    "oman sports": "عُمان الرياضية",
    "on time sports": "أون تايم سبورتس",
    "on sports": "أون سبورت",
    "shahid": "شاهد",
    "arr yadia": "الرياضية المغربية",
}


# =====================================
# GENERAL FUNCTIONS
# =====================================

def clean(value):
    if value is None or isinstance(value, (dict, list)):
        return ""

    return re.sub(
        r"\s+",
        " ",
        html.unescape(str(value))
    ).strip()


def normalize(value):
    value = unicodedata.normalize(
        "NFKC",
        clean(value)
    ).casefold()

    value = re.sub(
        r"[\u064B-\u065F\u0670ـ]",
        "",
        value
    )

    value = value.replace("أ", "ا")
    value = value.replace("إ", "ا")
    value = value.replace("آ", "ا")
    value = value.replace("ى", "ي")
    value = value.replace("ة", "ه")

    return re.sub(
        r"[^a-z0-9\u0600-\u06ff]+",
        "",
        value
    )


def arabic_name(value):
    value = clean(value)

    if not value:
        return ""

    if re.search(r"[\u0600-\u06ff]", value):
        return value

    return TEAM_AR.get(
        value.casefold(),
        value
    )


def fetch(url, params=None):
    response = session.get(
        url,
        params=params,
        timeout=TIMEOUT,
        allow_redirects=True
    )

    response.raise_for_status()

    return response


def fetch_json(path, params=None):
    return fetch(
        f"{BASE_URL}/{path.lstrip('/')}",
        params
    ).json()


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    except FileNotFoundError:
        return default

    except Exception as error:
        print("JSON ERROR:", error)
        return default


def parse_utc(value):
    try:
        dt = datetime.fromisoformat(
            clean(value).replace("Z", "+00:00")
        )

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(TZ)

    except Exception:
        return None


# =====================================
# OLD DATA
# =====================================

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

        if match.get("streamUrl"):
            streams[key] = match["streamUrl"]

        broadcasts[key] = {
            "channel": clean(match.get("channel")),
            "commentator": clean(match.get("commentator"))
        }

    return streams, broadcasts


# =====================================
# HTML EXTRACTION
# =====================================

class PageParser(HTMLParser):

    def __init__(self):
        super().__init__()

        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):

        if tag in (
            "script",
            "style",
            "noscript",
            "svg"
        ):
            self.skip += 1

    def handle_endtag(self, tag):

        if tag in (
            "script",
            "style",
            "noscript",
            "svg"
        ):
            self.skip = max(0, self.skip - 1)

    def handle_data(self, data):

        if not self.skip:

            value = clean(data)

            if value:
                self.parts.append(value)


def extract_text(source):

    parser = PageParser()

    try:
        parser.feed(source)

        return " ".join(parser.parts)

    except Exception:
        return clean(
            re.sub(r"<[^>]+>", " ", source)
        )


# =====================================
# GOOGLE NEWS SEARCH
# =====================================

def google_news_search(query):

    url = "https://news.google.com/rss/search"

    try:

        response = fetch(
            url,
            {
                "q": query,
                "hl": "ar",
                "gl": "IQ",
                "ceid": "IQ:ar"
            }
        )

        root = ET.fromstring(response.content)

        results = []

        for item in root.findall(".//item")[:SEARCH_LIMIT]:

            results.append({
                "title": clean(item.findtext("title")),
                "description": clean(
                    item.findtext("description")
                ),
                "link": clean(item.findtext("link"))
            })

        return results

    except Exception as error:

        print("Google RSS:", error)

        return []


# =====================================
# BING RESULT PARSER
# =====================================

class BingResultsParser(HTMLParser):

    def __init__(self):

        super().__init__()

        self.results = []
        self.current = None

        self.in_h2 = False
        self.in_p = False

    def handle_starttag(self, tag, attrs):

        attrs = dict(attrs)

        classes = attrs.get(
            "class",
            ""
        ).split()

        if tag == "li" and "b_algo" in classes:

            self.current = {
                "title": "",
                "description": "",
                "link": ""
            }

            self.results.append(self.current)

        elif self.current is not None:

            if tag == "h2":

                self.in_h2 = True

            elif tag == "a" and self.in_h2:

                self.current["link"] = attrs.get(
                    "href",
                    ""
                )

            elif tag == "p":

                self.in_p = True

    def handle_endtag(self, tag):

        if tag == "h2":
            self.in_h2 = False

        elif tag == "p":
            self.in_p = False

    def handle_data(self, data):

        if self.current is None:
            return

        value = clean(data)

        if not value:
            return

        if self.in_h2:

            self.current["title"] += " " + value

        elif self.in_p:

            self.current["description"] += " " + value


def bing_search(query):

    try:

        response = fetch(
            "https://www.bing.com/search",
            {
                "q": query,
                "setlang": "ar",
                "count": SEARCH_LIMIT
            }
        )

        parser = BingResultsParser()

        parser.feed(response.text)

        results = []

        for item in parser.results[:SEARCH_LIMIT]:

            if item.get("title") or item.get("description"):

                results.append({
                    "title": clean(item["title"]),
                    "description": clean(
                        item["description"]
                    ),
                    "link": clean(item["link"])
                })

        return results

    except Exception as error:

        print("Bing:", error)

        return []


# =====================================
# DIRECT SOURCE PAGES
# =====================================

def fetch_source_pages():

    pages = []

    for url in SOURCES:

        try:

            response = fetch(url)

            text = extract_text(response.text)

            pages.append({
                "name": urlparse(url).netloc,
                "text": text,
                "url": url
            })

            print(
                "SOURCE OK:",
                urlparse(url).netloc
            )

        except Exception as error:

            print(
                "SOURCE ERROR:",
                url,
                error
            )

    return pages


# =====================================
# MATCH VERIFICATION
# =====================================

def match_found(text, home, away):

    text_norm = normalize(text)

    h = normalize(home)
    a = normalize(away)

    return bool(
        h and a and
        h in text_norm and
        a in text_norm
    )


# =====================================
# CHANNEL EXTRACTION
# =====================================

def find_channel(text):

    text = clean(text)

    low = text.casefold()

    patterns = [

        r"(?:القناة الناقلة|القنوات الناقلة|على قناة|تنقل على|تنقلها|القناة)\s*[:：\-]?\s*([^،؛|.]{2,65})",

        r"(?:broadcast(?:ing)? on|tv channel|channel)\s*[:：\-]?\s*([A-Za-z0-9 .&'-]{2,55})"

    ]

    for pattern in patterns:

        found = re.search(
            pattern,
            text,
            re.I
        )

        if not found:
            continue

        value = clean(found.group(1))

        value = re.split(
            r"المعلق|معلق المباراة|موعد المباراة|توقيت المباراة|الملعب|commentator|kick.?off",
            value,
            flags=re.I
        )[0].strip(" :-")

        for key, arabic in sorted(
            CHANNEL_AR.items(),
            key=lambda x: len(x[0]),
            reverse=True
        ):

            if key in value.casefold():

                number = re.search(
                    r"\d+",
                    value
                )

                return arabic + (
                    " " + number.group()
                    if number else ""
                )

        if (
            re.search(r"[\u0600-\u06ff]", value)
            and len(value) <= 55
        ):
            return value

    # البحث عن أسماء القنوات المعروفة داخل نص المقال

    for key in sorted(
        CHANNEL_AR,
        key=len,
        reverse=True
    ):

        if key in low:

            number = re.search(
                re.escape(key) + r"[^0-9]{0,12}(\d+)",
                low
            )

            return CHANNEL_AR[key] + (
                " " + number.group(1)
                if number else ""
            )

    return ""


# =====================================
# COMMENTATOR EXTRACTION
# =====================================

def find_commentator(text):

    patterns = [

        r"(?:المعلق|معلق المباراة|التعليق|بصوت|المعلق الصوتي)\s*[:：\-]?\s*([\u0600-\u06ffA-Za-z .'-]{3,45})",

        r"(?:commentator|commentary by|voice)\s*[:：\-]?\s*([A-Za-z .'-]{3,45})"

    ]

    for pattern in patterns:

        found = re.search(
            pattern,
            text,
            re.I
        )

        if not found:
            continue

        name = clean(found.group(1))

        name = re.split(
            r"القناة|موعد|توقيت|الملعب|بطولة|channel|broadcast|kick.?off|date",
            name,
            flags=re.I
        )[0].strip(" :-")

        if (
            3 <= len(name) <= 45
            and not re.search(r"\d", name)
        ):

            if normalize(name) not in {
                "match",
                "live",
                "sports",
                "football",
                "مباراه"
            }:

                return name

    return ""


# =====================================
# BROADCAST SEARCH ENGINE
# =====================================

def search_match_broadcast(
    home,
    away,
    league,
    date,
    source_pages
):

    query_ar = (
        f'"{home}" "{away}" {league} '
        f'القناة الناقلة المعلق {date}'
    )

    query_en = (
        f'"{home}" "{away}" {league} '
        f'broadcast channel commentator {date}'
    )

    print(
        "  SEARCH:",
        home,
        "-",
        away
    )

    candidates = []

    seen_links = set()

    def inspect_result(source_name, result):

        title = clean(
            result.get("title", "")
        )

        snippet = clean(
            result.get("description", "")
        )

        link = clean(
            result.get("link", "")
        )

        page_text = ""

        if (
            link.startswith(("http://", "https://"))
            and link not in seen_links
        ):

            seen_links.add(link)

            try:

                page = fetch(link)

                page_text = extract_text(
                    page.text
                )[:18000]

            except Exception as error:

                print(
                    "  PAGE ERROR:",
                    urlparse(link).netloc,
                    str(error)[:120]
                )

        combined = clean(
            title + " " +
            snippet + " " +
            page_text
        )

        if match_found(
            combined,
            home,
            away
        ):

            candidates.append((
                source_name,
                combined
            ))

    # Google News

    for result in google_news_search(query_ar):

        inspect_result(
            "Google News",
            result
        )

        time.sleep(0.25)

    # Bing بالعربي والإنجليزي

    for query in (
        query_ar,
        query_en
    ):

        for result in bing_search(query):

            inspect_result(
                "Bing",
                result
            )

            time.sleep(0.25)

    # المواقع الرياضية المباشرة

    for source in source_pages:

        if match_found(
            source["text"],
            home,
            away
        ):

            candidates.append((
                source["name"],
                source["text"]
            ))

    channels = {}
    commentators = {}

    for source_name, text in candidates:

        channel = find_channel(text)

        commentator = find_commentator(text)

        if channel:

            channels[channel] = (
                channels.get(channel, 0) + 1
            )

        if commentator:

            commentators[commentator] = (
                commentators.get(commentator, 0) + 1
            )

        print(
            "  MATCHED SOURCE:",
            source_name,
            "| CHANNEL:",
            channel or "غير موجود",
            "| COMMENTATOR:",
            commentator or "غير موجود"
        )

    channel = (
        max(channels, key=channels.get)
        if channels else ""
    )

    commentator = (
        max(commentators, key=commentators.get)
        if commentators else ""
    )

    return channel, commentator


# =====================================
# BROADCAST DATA
# =====================================

def load_broadcasts():

    data = load_json(
        BROADCASTS_FILE,
        {}
    )

    return data if isinstance(data, dict) else {}


def get_broadcast(
    item,
    date,
    home,
    away,
    league,
    old_broadcasts,
    overrides,
    source_pages
):

    key = (
        date,
        normalize(home),
        normalize(away)
    )

    previous = old_broadcasts.get(
        key,
        {}
    )

    match_id = clean(
        item.get("id")
    )

    override = overrides.get(
        match_id,
        {}
    )

    if not isinstance(override, dict):
        override = {}

    if not override:

        override = overrides.get(
            "|".join(key),
            {}
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

    if not channel or not commentator:

        found_channel, found_commentator = (
            search_match_broadcast(
                home,
                away,
                league,
                date,
                source_pages
            )
        )

        channel = channel or found_channel

        commentator = commentator or found_commentator

    return channel, commentator


# =====================================
# MATCH STATUS
# =====================================

def team_info(team):

    if not isinstance(team, dict):
        return "", ""

    raw = (
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

    team_id = clean(
        team.get("id")
    )

    if not logo and team_id.isdigit():

        logo = (
            "https://images.fotmob.com/image_resources/"
            f"logo/teamlogo/{team_id}.png"
        )

    return arabic_name(raw), logo


def match_status(status):

    if isinstance(status, dict):

        if (
            status.get("cancelled")
            or status.get("finished")
        ):
            return "ended"

        if status.get("started"):
            return "live"

        reason = clean(
            status.get("reason")
        ).lower()

        if reason in (
            "ft",
            "aet",
            "pen",
            "finished"
        ):
            return "ended"

        if reason in (
            "ht",
            "1h",
            "2h",
            "live"
        ):
            return "live"

    raw = clean(status).lower()

    if raw in (
        "live",
        "ht",
        "1h",
        "2h"
    ):
        return "live"

    if raw in (
        "ft",
        "aet",
        "pen",
        "ended",
        "finished"
    ):
        return "ended"

    return "upcoming"


def get_score(item, status):

    if isinstance(status, dict):

        score = clean(
            status.get("scoreStr")
        )

        if score and score not in ("-", "vs"):

            return score.replace(" ", "")

    home = item.get("home", {})
    away = item.get("away", {})

    if (
        isinstance(home, dict)
        and isinstance(away, dict)
    ):

        h = home.get("score")
        a = away.get("score")

        if h is not None and a is not None:

            return f"{h}-{a}"

    return ""


# =====================================
# CONVERT MATCH
# =====================================

def convert_match(
    item,
    streams,
    old_broadcasts,
    overrides,
    source_pages
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

    status = item.get(
        "status",
        {}
    )

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
        return None

    date = kickoff.strftime(
        "%Y-%m-%d"
    )

    hour = kickoff.strftime(
        "%H:%M"
    )

    key = (
        date,
        normalize(home),
        normalize(away)
    )

    league_obj = item.get("league") or {}

    if isinstance(league_obj, dict):

        league_raw = (
            league_obj.get("name")
            or league_obj.get("localizedName")
            or ""
        )

    else:

        league_raw = league_obj

    league = arabic_name(
        league_raw
    )

    channel, commentator = get_broadcast(
        item,
        date,
        home,
        away,
        league,
        old_broadcasts,
        overrides,
        source_pages
    )

    return {
        "league": league,
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


# =====================================
# FETCH MATCHES
# =====================================

def extract_matches(payload):

    if isinstance(payload, dict):

        if isinstance(
            payload.get("matches"),
            list
        ):

            return payload["matches"]

        rows = []

        for league in payload.get(
            "leagues",
            []
        ):

            if not isinstance(league, dict):
                continue

            for match in league.get(
                "matches",
                []
            ):

                if isinstance(match, dict):

                    match = dict(match)

                    match.setdefault(
                        "league",
                        league
                    )

                    rows.append(match)

        if rows:
            return rows

    raise ValueError(
        "Invalid matches response"
    )


def fetch_day(date):

    day = date.strftime(
        "%Y%m%d"
    )

    print(
        "FETCH:",
        day
    )

    payload = fetch_json(
        "matches",
        {
            "date": day,
            "timezone": TZ.key,
            "ccode3": COUNTRY_CODE
        }
    )

    return extract_matches(payload)


# =====================================
# SAFE JSON SAVE
# =====================================

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

        with open(
            temp_path,
            encoding="utf-8"
        ) as f:

            json.load(f)

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


# =====================================
# MAIN
# =====================================

def main():

    now = datetime.now(TZ)

    today_date = now.date()

    streams, old_broadcasts = old_data_maps()

    overrides = load_broadcasts()

    print("\nتحميل مصادر النقل...")

    source_pages = fetch_source_pages()

    print(
        "المصادر المحملة:",
        len(source_pages)
    )

    collected = {}

    errors = {}

    for offset in DAYS:

        target = today_date + timedelta(
            days=offset
        )

        date_key = target.isoformat()

        try:

            for item in fetch_day(target):

                match_id = clean(
                    item.get("id")
                )

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

            print(
                "FETCH ERROR:",
                error
            )

    today_key = today_date.isoformat()

    if today_key in errors:

        raise RuntimeError(
            "فشل جلب مباريات اليوم. الملف القديم محفوظ."
        )

    if not collected:

        raise RuntimeError(
            "لم تصل أي مباريات."
        )

    converted = []

    for index, item in enumerate(
        collected.values(),
        1
    ):

        print(
            f"\n[{index}/{len(collected)}] "
            "معالجة المباراة"
        )

        match = convert_match(
            item,
            streams,
            old_broadcasts,
            overrides,
            source_pages
        )

        if match:
            converted.append(match)

        time.sleep(DELAY)

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

    matches = list(
        unique.values()
    )

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
            "لا توجد مباريات اليوم. الملف القديم محفوظ."
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

    print("\n================================")

    print(
        "YALLA KORA MULTI SEARCH V7"
    )

    print("================================")

    print(
        "مصادر النقل:",
        len(source_pages)
    )

    print(
        "مباريات اليوم:",
        len(today)
    )

    print(
        "مباريات الأمس:",
        len(yesterday)
    )

    print(
        "مباريات الغد:",
        len(tomorrow)
    )

    print(
        "إجمالي المباريات:",
        len(matches)
    )

    print(
        "المباريات مع قناة:",
        sum(bool(m["channel"]) for m in matches)
    )

    print(
        "المباريات مع معلق:",
        sum(bool(m["commentator"]) for m in matches)
    )

    print(
        "أخطاء الجلب:",
        errors or "لا يوجد"
    )

    print(
        "تم حفظ matches.json"
    )

    print("================================")


if __name__ == "__main__":

    try:

        main()

    except Exception as error:

        print(
            "\nUPDATE FAILED:",
            error
        )

        sys.exit(1)
