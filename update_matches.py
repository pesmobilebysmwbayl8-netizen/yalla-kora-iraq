
# -*- coding: utf-8 -*-
import json
import os
import re
import sys
import time
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "matches.json"
BROADCASTS_FILE = ROOT / "broadcasts.json"

BASE_URL = "https://www.fotmob.com/api/data"
TZ = ZoneInfo("Asia/Baghdad")
COUNTRY_CODE = "IRQ"
DAYS = (-1, 0, 1)
TIMEOUT = 20

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 YallaKoraSearchEngine/5.0",
    "Accept": "application/json,text/html,application/rss+xml,*/*",
    "Accept-Language": "ar-IQ,ar;q=0.9,en;q=0.5"
})

TEAM_AR = {
    "manchester city": "مانشستر سيتي",
    "manchester united": "مانشستر يونايتد",
    "liverpool": "ليفربول",
    "arsenal": "أرسنال",
    "chelsea": "تشيلسي",
    "real madrid": "ريال مدريد",
    "barcelona": "برشلونة",
    "atletico madrid": "أتلتيكو مدريد",
    "bayern munich": "بايرن ميونخ",
    "paris saint-germain": "باريس سان جيرمان",
    "inter milan": "إنتر ميلان",
    "ac milan": "ميلان",
    "juventus": "يوفنتوس",
    "napoli": "نابولي",
    "al hilal": "الهلال",
    "al nassr": "النصر",
    "al ittihad": "الاتحاد",
    "al ahli": "الأهلي",
    "al sadd": "السد",
    "al duhail": "الدحيل",
    "al shorta": "الشرطة",
    "al quwa al jawiya": "القوة الجوية",
    "al zawraa": "الزوراء",
    "iraqi stars league": "دوري نجوم العراق",
    "iraq stars league": "دوري نجوم العراق",
    "saudi pro league": "دوري روشن السعودي",
    "premier league": "الدوري الإنجليزي الممتاز",
    "la liga": "الدوري الإسباني",
    "serie a": "الدوري الإيطالي",
    "bundesliga": "الدوري الألماني",
    "ligue 1": "الدوري الفرنسي",
    "champions league": "دوري أبطال أوروبا",
    "europa league": "الدوري الأوروبي"
}

CHANNEL_AR = {
    "bein sports": "بي إن سبورتس",
    "ssc": "إس إس سي",
    "alkass": "قنوات الكأس",
    "al kass": "قنوات الكأس",
    "abu dhabi sports": "أبوظبي الرياضية",
    "iraqia sports": "العراقية الرياضية",
    "al rabiaa": "الرابعة الرياضية",
    "alrabiaa": "الرابعة الرياضية",
    "thmanyah": "ثمانية",
    "dubai sports": "دبي الرياضية",
    "kuwait sports": "الكويت الرياضية",
    "on time sports": "أون تايم سبورتس"
}


def clean(value):
    if value is None or isinstance(value, (dict, list)):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def normalize(value):
    value = unicodedata.normalize("NFKC", clean(value)).casefold()
    value = re.sub(r"[\u064B-\u065F\u0670ـ]", "", value)
    value = value.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    value = value.replace("ى", "ي").replace("ة", "ه")
    return re.sub(r"[^a-z0-9\u0600-\u06ff]+", "", value)


def arabic_name(value):
    value = clean(value)
    if not value or re.search(r"[\u0600-\u06ff]", value):
        return value
    return TEAM_AR.get(value.casefold(), value)


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
    except (ValueError, TypeError):
        return None


def old_data_maps():
    old = load_json(OUTPUT, {})
    streams, broadcasts = {}, {}

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

    return arabic_name(name), logo


def match_status(status):
    if isinstance(status, dict):
        if status.get("cancelled") or status.get("finished"):
            return "ended"
        if status.get("started"):
            return "live"

        reason = clean(status.get("reason")).lower()

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
        h, a = home.get("score"), away.get("score")
        if h is not None and a is not None:
            return f"{h}-{a}"

    return ""


# ==============================
# INTERNET SEARCH
# ==============================

def google_search(home, away, league, date):
    query = (
        f'"{home}" "{away}" "{league}" '
        f'القناة الناقلة المعلق {date}'
    )

    url = "https://news.google.com/rss/search"

    params = {
        "q": query,
        "hl": "ar",
        "gl": "IQ",
        "ceid": "IQ:ar"
    }

    try:
        response = session.get(
            url, params=params, timeout=TIMEOUT
        )
        response.raise_for_status()

        root = ET.fromstring(response.content)
        results = []

        for item in root.findall(".//item")[:5]:
            title = clean(item.findtext("title"))
            description = clean(item.findtext("description"))
            link = clean(item.findtext("link"))

            results.append({
                "title": title,
                "description": description,
                "link": link
            })

        return results

    except Exception as error:
        print("SEARCH ERROR:", error)
        return []


def get_page_text(url):
    try:
        response = session.get(
            url, timeout=TIMEOUT,
            allow_redirects=True
        )
        response.raise_for_status()

        text = re.sub(
            r"<(script|style|noscript).*?>.*?</\1>",
            " ", response.text,
            flags=re.I | re.S
        )

        text = re.sub(r"<[^>]+>", " ", text)

        return clean(
            re.sub(r"&(?:nbsp|amp|quot);", " ", text)
        )[:30000]

    except Exception:
        return ""


def find_channel(text):
    patterns = [
        r"(?:القناة الناقلة|على قناة|تنقلها|القناة)\s*[:：\-]?\s*"
        r"([^،؛|.]{2,60})",
        r"(?:beIN\s*SPORTS|SSC|Alkass|Al Kass|"
        r"Abu Dhabi Sports|thmanyah|"
        r"قنوات الكأس|الرابعة الرياضية|ثمانية)"
        r"(?:\s*(?:HD|4K)?\s*\d*)"
    ]

    for pattern in patterns:
        found = re.search(pattern, text, re.I)

        if not found:
            continue

        channel = clean(
            found.group(1) if found.lastindex
            else found.group(0)
        )

        channel = re.split(
            r"المعلق|معلق المباراة|موعد المباراة",
            channel
        )[0].strip(" :-")

        for english, arabic in CHANNEL_AR.items():
            if english in channel.casefold():
                number = re.search(r"\d+", channel)
                return arabic + (
                    " " + number.group()
                    if number else ""
                )

        if re.search(r"[\u0600-\u06ff]", channel):
            return channel

    return ""


def find_commentator(text):
    patterns = [
        r"(?:المعلق|معلق المباراة|بصوت)\s*[:：\-]?\s*"
        r"([\u0600-\u06ffA-Za-z .'-]{3,45})"
    ]

    for pattern in patterns:
        found = re.search(pattern, text, re.I)

        if found:
            name = clean(found.group(1))
            name = re.split(
                r"القناة|موعد|توقيت|الملعب|بطولة",
                name
            )[0].strip(" :-")

            if 3 <= len(name) <= 45:
                return name

    return ""


def search_broadcast(home, away, league, date):
    results = google_search(home, away, league, date)

    channel_votes = {}
    commentator_votes = {}

    for result in results[:3]:
        text = (
            result["title"] + " " +
            result["description"]
        )

        # افتح صفحة النتيجة إذا لم تكفِ بيانات RSS
        if not (
            normalize(home) in normalize(text)
            and normalize(away) in normalize(text)
        ):
            text += " " + get_page_text(result["link"])
            time.sleep(0.7)

        # لا تعتمد نتيجة لا تتطابق مع الفريقين
        normalized = normalize(text)

        if (
            normalize(home) not in normalized
            or normalize(away) not in normalized
        ):
            continue

        channel = find_channel(text)
        commentator = find_commentator(text)

        if channel:
            channel_votes[channel] = (
                channel_votes.get(channel, 0) + 1
            )

        if commentator:
            commentator_votes[commentator] = (
                commentator_votes.get(commentator, 0) + 1
            )

    channel = (
        max(channel_votes, key=channel_votes.get)
        if channel_votes else ""
    )

    commentator = (
        max(commentator_votes, key=commentator_votes.get)
        if commentator_votes else ""
    )

    return channel, commentator


# ==============================
# BROADCAST DATA
# ==============================

def load_broadcasts():
    data = load_json(BROADCASTS_FILE, {})
    return data if isinstance(data, dict) else {}


def get_broadcast(
    item, date, home, away,
    old_broadcasts, overrides, league
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
        override = overrides.get("|".join(key), {})
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
        print("  البحث عن القناة والمعلق:", home, "-", away)

        found_channel, found_commentator = search_broadcast(
            home, away, league, date
        )

        channel = channel or found_channel
        commentator = commentator or found_commentator

    return channel, commentator


# ==============================
# CONVERT MATCH
# ==============================

def convert_match(item, streams, old_broadcasts, overrides):
    if not isinstance(item, dict):
        return None

    home, home_img = team_info(item.get("home"))
    away, away_img = team_info(item.get("away"))

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
            item.get("utcTime") or item.get("startTime")
        )

    if kickoff is None:
        return None

    date = kickoff.strftime("%Y-%m-%d")
    hour = kickoff.strftime("%H:%M")

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

    league = arabic_name(league_raw)

    channel, commentator = get_broadcast(
        item, date, home, away,
        old_broadcasts, overrides, league
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


# ==============================
# FETCH MATCHES
# ==============================

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

    print("جلب مباريات:", day)

    payload = fetch_json(
        "matches",
        {
            "date": day,
            "timezone": TZ.key,
            "ccode3": COUNTRY_CODE
        }
    )

    return extract_matches(payload)


# ==============================
# SAFE SAVE
# ==============================

def save_matches(data):
    content = json.dumps(
        data, ensure_ascii=False, indent=2
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


# ==============================
# MAIN
# ==============================

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
                    match_id or json.dumps(
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
            "تعذر جلب مباريات اليوم؛ الملف القديم محفوظ."
        )

    if not collected:
        raise RuntimeError("لم تصل أي مباريات.")

    converted = []

    for index, item in enumerate(collected.values(), 1):
        print(
            f"\n[{index}/{len(collected)}] معالجة المباراة"
        )

        match = convert_match(
            item, streams, old_broadcasts, overrides
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
            "لا توجد مباريات اليوم؛ الملف القديم محفوظ."
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

    print("\n===== YALLA KORA SEARCH ENGINE V5 =====")
    print("توقيت العراق:", TZ.key)
    print("مباريات اليوم:", len(today))
    print("مباريات الأمس:", len(yesterday))
    print("مباريات الغد:", len(tomorrow))
    print("الإجمالي:", len(matches))

    print(
        "المباريات مع قناة:",
        sum(bool(m["channel"]) for m in matches)
    )

    print(
        "المباريات مع معلق:",
        sum(bool(m["commentator"]) for m in matches)
    )

    print(
        "روابط البث المحفوظة:",
        sum(bool(m["streamUrl"]) for m in matches)
    )

    print("أخطاء الجلب:", errors or "لا يوجد")
    print("=======================================")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("فشل التحديث:", error)
        sys.exit(1)
