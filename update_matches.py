
# -*- coding: utf-8 -*-
# YALLA KORA V9 - MATCHES + BROADCAST SEARCH
# Requirements: requests beautifulsoup4

import json
import re
import html
import time
import os
import tempfile
import unicodedata
import xml.etree.ElementTree as ET

from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from urllib.parse import urlparse, quote
from collections import defaultdict

import requests
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "matches.json"
BROADCASTS_FILE = ROOT / "broadcasts.json"

TZ = ZoneInfo("Asia/Baghdad")
BASE_URL = "https://www.fotmob.com/api/data"

DAYS = (-1, 0, 1)

TIMEOUT = 15
RETRIES = 2
SEARCH_LIMIT = 5
MAX_PAGES_PER_MATCH = 5

# حد البحث حتى لا تتجاوز دورة GitHub Actions وقت التشغيل
MAX_BROADCAST_SEARCHES = 35

COUNTRY_CODE = "IRQ"

session = requests.Session()
session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
})

SEARCH_CACHE = {}
PAGE_CACHE = {}

STATS = defaultdict(int)


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
    "sevilla": "إشبيلية",
    "alaves": "ألافيس",
    "deportivo alaves": "ألافيس",
    "bayern munich": "بايرن ميونخ",
    "borussia dortmund": "بوروسيا دورتموند",
    "psg": "باريس سان جيرمان",
    "paris saint-germain": "باريس سان جيرمان",
    "inter milan": "إنتر ميلان",
    "ac milan": "ميلان",
    "juventus": "يوفنتوس",
    "napoli": "نابولي",
    "roma": "روما",
    "lazio": "لاتسيو",
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
    "afc champions league": "دوري أبطال آسيا",
}


CHANNELS = {
    "bein sports": "بي إن سبورتس",
    "beinsports": "بي إن سبورتس",
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
    "dazn": "DAZN",
    "espn": "ESPN",
    "sky sports": "سكاي سبورتس",
    "canal+": "كانال بلس",
    "sport tv": "سبورت تي في",
    "fox sports": "فوكس سبورتس",
    "premier sports": "بريمير سبورتس",
}


BROADCAST_WORDS = (
    "القناة الناقلة",
    "القنوات الناقلة",
    "على قناة",
    "تنقل على",
    "يذاع على",
    "النقل التلفزيوني",
    "معلق المباراة",
    "المعلق",
    "broadcast",
    "tv channel",
    "watch live",
    "where to watch",
    "commentator",
    "coverage",
    "live on",
    "streaming on",
)


def clean(value):
    if value is None:
        return ""
    return re.sub(
        r"\s+", " ",
        html.unescape(str(value))
    ).strip()


def normalize(value):
    value = unicodedata.normalize("NFKC", clean(value)).casefold()
    value = re.sub(r"[\u064B-\u065F\u0670ـ]", "", value)
    value = value.replace("أ", "ا").replace("إ", "ا")
    value = value.replace("آ", "ا").replace("ى", "ي")
    value = value.replace("ة", "ه")
    return re.sub(r"[^a-z0-9\u0600-\u06ff]", "", value)


def arabic_name(value):
    value = clean(value)
    if not value:
        return ""
    if re.search(r"[\u0600-\u06ff]", value):
        return value
    return TEAM_AR.get(value.casefold(), value)


def fetch(url, params=None):
    error = None

    for attempt in range(RETRIES):
        try:
            response = session.get(
                url,
                params=params,
                timeout=TIMEOUT
            )
            response.raise_for_status()
            return response

        except requests.RequestException as exc:
            error = exc
            time.sleep(1)

    raise error


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    content = json.dumps(
        data,
        ensure_ascii=False,
        indent=2
    ) + "\n"

    temp = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=ROOT,
            delete=False
        ) as f:
            f.write(content)
            temp = f.name

        with open(temp, encoding="utf-8") as f:
            json.load(f)

        os.replace(temp, path)

    finally:
        if temp and os.path.exists(temp):
            os.remove(temp)


def parse_date(value):
    try:
        dt = datetime.fromisoformat(
            clean(value).replace("Z", "+00:00")
        )

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(TZ)

    except Exception:
        return None


def get_team(team):
    if not isinstance(team, dict):
        return "", ""

    name = (
        team.get("nameAr")
        or team.get("name_ar")
        or team.get("name")
        or team.get("shortName")
    )

    logo = (
        team.get("imageUrl")
        or team.get("logo")
        or team.get("logo_url")
        or ""
    )

    team_id = clean(team.get("id"))

    if not logo and team_id.isdigit():
        logo = (
            "https://images.fotmob.com/image_resources/"
            f"logo/teamlogo/{team_id}.png"
        )

    return arabic_name(name), clean(logo)


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


def match_names_present(text, home, away):
    value = normalize(text)
    h = normalize(home)
    a = normalize(away)

    if not h or not a:
        return False

    return h in value and a in value


def has_broadcast_words(text):
    value = normalize(text)

    return any(
        normalize(word) in value
        for word in BROADCAST_WORDS
    )


def google_search(query):
    key = ("google", query)

    if key in SEARCH_CACHE:
        return SEARCH_CACHE[key]

    STATS["google_searches"] += 1
    results = []

    try:
        response = fetch(
            "https://news.google.com/rss/search",
            {
                "q": query,
                "hl": "ar",
                "gl": "IQ",
                "ceid": "IQ:ar",
            }
        )

        root = ET.fromstring(response.content)

        for item in root.findall(".//item")[:SEARCH_LIMIT]:
            results.append({
                "title": clean(item.findtext("title")),
                "description": clean(item.findtext("description")),
                "link": clean(item.findtext("link")),
            })

    except Exception as exc:
        print("GOOGLE ERROR:", str(exc)[:120])

    SEARCH_CACHE[key] = results
    STATS["search_results"] += len(results)

    return results


def bing_search(query):
    key = ("bing", query)

    if key in SEARCH_CACHE:
        return SEARCH_CACHE[key]

    STATS["bing_searches"] += 1
    results = []

    try:
        response = fetch(
            "https://www.bing.com/search",
            {
                "q": query,
                "count": SEARCH_LIMIT,
                "setlang": "ar",
            }
        )

        soup = BeautifulSoup(response.text, "html.parser")

        for item in soup.select("li.b_algo")[:SEARCH_LIMIT]:
            title = item.select_one("h2")
            link = title.find("a") if title else None
            desc = item.select_one("p")

            if not link:
                continue

            results.append({
                "title": clean(title.get_text(" ", strip=True)),
                "description": clean(
                    desc.get_text(" ", strip=True) if desc else ""
                ),
                "link": clean(link.get("href")),
            })

    except Exception as exc:
        print("BING ERROR:", str(exc)[:120])

    SEARCH_CACHE[key] = results
    STATS["search_results"] += len(results)

    return results


def page_text(url):
    if url in PAGE_CACHE:
        STATS["page_cache_hits"] += 1
        return PAGE_CACHE[url]

    try:
        response = fetch(url)

        soup = BeautifulSoup(response.text, "html.parser")

        for tag in soup(
            ["script", "style", "noscript", "svg", "iframe"]
        ):
            tag.decompose()

        rows = []

        # نحافظ على كل صف في الجدول كوحدة منفصلة
        for tr in soup.find_all("tr"):
            cells = [
                clean(cell.get_text(" ", strip=True))
                for cell in tr.find_all(["td", "th"])
            ]

            cells = [x for x in cells if x]

            if cells:
                rows.append(" | ".join(cells))

        text = soup.get_text(" | ", strip=True)

        if rows:
            text += " | " + " || ".join(rows)

        text = clean(text)[:50000]

        PAGE_CACHE[url] = text
        STATS["pages_opened"] += 1

        return text

    except Exception as exc:
        STATS["page_errors"] += 1
        print("PAGE ERROR:", str(exc)[:100])
        return ""


def extract_channel(text):
    text = clean(text)

    # أولاً: البحث قرب عبارات النقل
    patterns = [
        r"(?:القناة الناقلة|القنوات الناقلة|القناة|"
        r"تنقل على|يذاع على|على قناة|broadcast(?:ing)? on|"
        r"tv channel|where to watch|available on)"
        r"\s*[:：\-]?\s*([^|؛،.!؟]{2,90})",

        r"(?:channel)\s*[:：\-]\s*([^|؛،.!?]{2,90})",
    ]

    for pattern in patterns:
        for found in re.finditer(pattern, text, re.I):
            value = clean(found.group(1))

            value = re.split(
                r"المعلق|معلق المباراة|موعد المباراة|"
                r"توقيت المباراة|commentator|kick.?off",
                value,
                flags=re.I
            )[0]

            for key, arabic in sorted(
                CHANNELS.items(),
                key=lambda x: len(x[0]),
                reverse=True
            ):
                if key in value.casefold():
                    number = re.search(r"\d+", value)

                    return (
                        arabic + (" " + number.group() if number else "")
                    )

    # ثانياً: مطابقة اسم قناة مع دليل نقل في نفس النص
    if has_broadcast_words(text):
        for key, arabic in sorted(
            CHANNELS.items(),
            key=lambda x: len(x[0]),
            reverse=True
        ):
            if key in text.casefold():
                number = re.search(
                    re.escape(key) + r"\s*(\d+)",
                    text,
                    re.I
                )

                return (
                    arabic + (" " + number.group(1) if number else "")
                )

    return ""


def extract_commentator(text):
    text = clean(text)

    patterns = [
        r"(?:المعلق|معلق المباراة|التعليق|بصوت|"
        r"المعلق الصوتي)\s*[:：\-]?\s*"
        r"([\u0600-\u06ffA-Za-z .'-]{3,45})",

        r"(?:commentator|commentary by|voice)"
        r"\s*[:：\-]?\s*([A-Za-z .'-]{3,45})",
    ]

    for pattern in patterns:
        found = re.search(pattern, text, re.I)

        if not found:
            continue

        name = clean(found.group(1))

        name = re.split(
            r"القناة|القنوات|موعد|توقيت|الملعب|"
            r"بطولة|channel|broadcast|kick.?off",
            name,
            flags=re.I
        )[0].strip(" :-")

        if 3 <= len(name) <= 45 and not re.search(r"\d", name):
            if normalize(name) not in (
                "match", "live", "sports", "football", "مباراه"
            ):
                return name

    return ""


def search_broadcast(home, away, league, date):
    print("  BROADCAST SEARCH:", home, "-", away)

    query_ar = (
        f'"{home}" "{away}" '
        f'{league} القناة الناقلة المعلق {date}'
    )

    query_en = (
        f'"{home}" "{away}" '
        f'{league} TV channel commentator broadcast {date}'
    )

    queries = [query_ar, query_en]

    candidates = []
    seen = set()
    opened = 0

    for query in queries:
        results = google_search(query) + bing_search(query)

        for result in results:
            title = clean(result.get("title"))
            desc = clean(result.get("description"))
            link = clean(result.get("link"))

            preview = title + " " + desc

            # لا نفتح إلا النتائج التي لها علاقة واضحة بالمباراة
            if not match_names_present(preview, home, away):
                continue

            if not link.startswith(("http://", "https://")):
                continue

            if link in seen:
                continue

            seen.add(link)

            text = preview

            if opened < MAX_PAGES_PER_MATCH:
                opened += 1
                text += " " + page_text(link)

            # نسمح باستخراج القناة والمعلق كل على حدة
            if match_names_present(text, home, away):
                candidates.append({
                    "text": text,
                    "domain": urlparse(link).netloc,
                })

    # جمع الأدلة المستقلة
    channel_sources = defaultdict(set)
    commentator_sources = defaultdict(set)

    for candidate in candidates:
        text = candidate["text"]
        domain = candidate["domain"]

        channel = extract_channel(text)
        commentator = extract_commentator(text)

        if channel:
            channel_sources[channel].add(domain)

        if commentator:
            commentator_sources[commentator].add(domain)

        print(
            "  SOURCE:", domain,
            "| CHANNEL:", channel or "-",
            "| COMMENTATOR:", commentator or "-"
        )

    # الأفضلية للمعلومة التي ظهرت في أكثر من نطاق مستقل
    channel = ""
    commentator = ""

    if channel_sources:
        channel = max(
            channel_sources,
            key=lambda x: len(channel_sources[x])
        )

    if commentator_sources:
        commentator = max(
            commentator_sources,
            key=lambda x: len(commentator_sources[x])
        )

    if channel:
        STATS["channels_found"] += 1

    if commentator:
        STATS["commentators_found"] += 1

    return channel, commentator


def old_data_maps():
    old = load_json(OUTPUT, {})

    streams = {}
    broadcasts = {}

    if not isinstance(old, dict):
        return streams, broadcasts

    for match in old.get("matches", []):
        if not isinstance(match, dict):
            continue

        key = (
            clean(match.get("date")),
            normalize(match.get("home")),
            normalize(match.get("away")),
        )

        if not key[1] or not key[2]:
            continue

        if match.get("streamUrl"):
            streams[key] = match["streamUrl"]

        broadcasts[key] = {
            "channel": clean(match.get("channel")),
            "commentator": clean(match.get("commentator")),
        }

    return streams, broadcasts


def load_overrides():
    data = load_json(BROADCASTS_FILE, {})

    if isinstance(data, dict):
        return data

    return {}


def get_broadcast(item, date, home, away, league, old, overrides):
    key = (
        date,
        normalize(home),
        normalize(away),
    )

    previous = old.get(key, {})

    match_id = clean(item.get("id"))

    override = {}

    if match_id:
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

    # لا نبحث من جديد عن البيانات المحفوظة بالكامل
    if channel and commentator:
        return channel, commentator

    # البحث محدود بعدد مباريات محدد لكل تشغيل
    if STATS["matches_searched"] >= MAX_BROADCAST_SEARCHES:
        return channel, commentator

    STATS["matches_searched"] += 1

    found_channel, found_commentator = search_broadcast(
        home, away, league, date
    )

    return (
        channel or found_channel,
        commentator or found_commentator,
    )


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

    raise ValueError("Invalid FotMob matches response")


def fetch_day(date):
    day = date.strftime("%Y%m%d")

    print("FETCH:", day)

    response = fetch(
        BASE_URL + "/matches",
        {
            "date": day,
            "timezone": TZ.key,
            "ccode3": COUNTRY_CODE,
        }
    )

    return extract_matches(response.json())


def convert_match(item, streams, old, overrides):
    if not isinstance(item, dict):
        return None

    home, home_img = get_team(item.get("home"))
    away, away_img = get_team(item.get("away"))

    if not home or not away:
        return None

    status = item.get("status", {})

    kickoff = None

    if isinstance(status, dict):
        kickoff = parse_date(status.get("utcTime"))

    if kickoff is None:
        kickoff = parse_date(
            item.get("utcTime") or item.get("startTime")
        )

    if kickoff is None:
        return None

    date = kickoff.strftime("%Y-%m-%d")
    hour = kickoff.strftime("%H:%M")

    key = (
        date,
        normalize(home),
        normalize(away),
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
        item,
        date,
        home,
        away,
        league,
        old,
        overrides
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
        "streamUrl": streams.get(key, ""),
    }


def main():
    today_date = datetime.now(TZ).date()

    streams, old = old_data_maps()
    overrides = load_overrides()

    collected = {}
    errors = {}

    print("\n========== YALLA KORA V9 ==========")
    print("TIMEZONE:", TZ.key)

    for offset in DAYS:
        target = today_date + timedelta(days=offset)
        date_key = target.isoformat()

        try:
            for item in fetch_day(target):
                match_id = clean(item.get("id"))

                stable_key = match_id or json.dumps(
                    item,
                    sort_keys=True,
                    ensure_ascii=False
                )

                collected[stable_key] = item

        except Exception as exc:
            errors[date_key] = str(exc)
            print("FETCH ERROR:", date_key, str(exc)[:150])

    today_key = today_date.isoformat()

    if today_key in errors:
        raise RuntimeError(
            "فشل جلب مباريات اليوم؛ الملف القديم لم يتغير."
        )

    if not collected:
        raise RuntimeError(
            "لم تصل أي مباريات؛ الملف القديم لم يتغير."
        )

    converted = []

    # نعطي الأولوية لمباريات اليوم ثم الغد
    items = list(collected.values())

    def sort_key(item):
        status = item.get("status", {})

        dt = None

        if isinstance(status, dict):
            dt = parse_date(status.get("utcTime"))

        if dt is None:
            dt = parse_date(
                item.get("utcTime") or item.get("startTime")
            )

        if dt is None:
            return datetime.max.replace(tzinfo=TZ)

        return dt

    items.sort(key=sort_key)

    for index, item in enumerate(items, 1):
        print(f"\n[{index}/{len(items)}]")

        match = convert_match(
            item,
            streams,
            old,
            overrides
        )

        if match:
            converted.append(match)

        time.sleep(0.05)

    yesterday_key = (
        today_date - timedelta(days=1)
    ).isoformat()

    tomorrow_key = (
        today_date + timedelta(days=1)
    ).isoformat()

    allowed = {
        yesterday_key,
        today_key,
        tomorrow_key,
    }

    unique = {}

    for match in converted:
        if match["date"] not in allowed:
            continue

        key = (
            match["date"],
            normalize(match["home"]),
            normalize(match["away"]),
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
            "لا توجد مباريات اليوم؛ الملف القديم لم يتغير."
        )

    output = {
        "success": True,
        "version": "V9",
        "updated_at": datetime.now(TZ).isoformat(),
        "timezone": TZ.key,
        "count": len(matches),
        "today_count": len(today),
        "yesterday_count": len(yesterday),
        "tomorrow_count": len(tomorrow),
        "matches": matches,
        "today": today,
        "yesterday": yesterday,
        "tomorrow": tomorrow,
    }

    save_json(OUTPUT, output)

    print("\n========== RESULTS ==========")
    print("TODAY:", len(today))
    print("YESTERDAY:", len(yesterday))
    print("TOMORROW:", len(tomorrow))
    print("TOTAL:", len(matches))

    print(
        "WITH CHANNEL:",
        sum(bool(m["channel"]) for m in matches)
    )

    print(
        "WITH COMMENTATOR:",
        sum(bool(m["commentator"]) for m in matches)
    )

    print("\n========== SEARCH DIAGNOSTICS ==========")

    for key, value in STATS.items():
        print(key, "=", value)

    print("FETCH ERRORS:", errors or "NONE")
    print("V9 FINISHED SUCCESSFULLY")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("\nUPDATE FAILED:", repr(exc))
        raise
