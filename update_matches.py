
import os
import re
import sys
import json
import time
import tempfile
import requests

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urljoin, urlparse, unquote
from bs4 import BeautifulSoup

# =====================================
# SETTINGS
# =====================================

BASE_URL = "https://shot.wiki"
OUTPUT = "matches.json"
TZ = ZoneInfo("Asia/Baghdad")

PAGES = {
    "today": BASE_URL + "/matches-today/",
    "yesterday": BASE_URL + "/matches-yesterday/",
    "tomorrow": BASE_URL + "/matches-tomorrow/",
}

MAX_MATCHES_PER_DAY = 100
DELAY = 0.25

session = requests.Session()
session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 10) "
        "AppleWebKit/537.36 Chrome/120.0 Mobile Safari/537.36"
    ),
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
})


# =====================================
# GENERAL
# =====================================

def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def get_page(url):
    try:
        response = session.get(url, timeout=25)
        response.raise_for_status()
        response.encoding = response.apparent_encoding
        return response.text
    except requests.RequestException as e:
        print("Page error:", url, e)
        return None


def get_soup(url):
    html = get_page(url)
    return BeautifulSoup(html, "html.parser") if html else None


def unique(items):
    result = []
    seen = set()

    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)

    return result


def valid_url(url):
    p = urlparse(url)
    return (
        p.netloc.endswith("shot.wiki")
        and "/matches/" in p.path
        and p.path.rstrip("/") != "/matches"
    )


def image_url(value):
    if isinstance(value, dict):
        value = (
            value.get("url")
            or value.get("contentUrl")
            or value.get("@id")
        )

    if isinstance(value, list):
        for item in value:
            result = image_url(item)
            if result:
                return result
        return ""

    value = str(value or "").strip()

    if value.startswith("//"):
        value = "https:" + value

    if value.startswith("http"):
        return value

    return ""


# =====================================
# JSON-LD DATA
# =====================================

def read_jsonld(soup):
    results = []

    for tag in soup.find_all(
        "script",
        type="application/ld+json"
    ):
        raw = tag.string or tag.get_text()

        try:
            data = json.loads(raw)
        except Exception:
            continue

        def walk(obj):
            if isinstance(obj, list):
                for item in obj:
                    walk(item)

            elif isinstance(obj, dict):
                results.append(obj)

                graph = obj.get("@graph")
                if graph:
                    walk(graph)

        walk(data)

    return results


def find_event(items):
    for item in items:
        types = item.get("@type", [])

        if isinstance(types, str):
            types = [types]

        if any(
            x.lower() in ("sportsevent", "event")
            for x in types
        ):
            return item

    return {}


def team_info(value):
    if isinstance(value, list):
        value = value[0] if value else {}

    if isinstance(value, str):
        return clean(value), ""

    if not isinstance(value, dict):
        return "", ""

    name = clean(
        value.get("name")
        or value.get("alternateName")
    )

    logo = image_url(
        value.get("logo")
        or value.get("image")
    )

    return name, logo


# =====================================
# MATCH LINKS
# =====================================

def collect_links(soup):
    links = []

    for a in soup.find_all("a", href=True):
        url = urljoin(BASE_URL, a["href"]).split("#")[0]

        if valid_url(url):
            links.append(url)

    return unique(links)[:MAX_MATCHES_PER_DAY]


# =====================================
# MATCH CARD
# =====================================

def find_card(soup, match_url):
    for a in soup.find_all("a", href=True):
        url = urljoin(BASE_URL, a["href"]).split("#")[0]

        if url == match_url:
            current = a

            for _ in range(7):
                if not current:
                    break

                text = clean(current.get_text(" ", strip=True))

                if len(text) > 10 and len(text) < 1800:
                    return current

                current = current.parent

    return None


def card_text(card):
    if not card:
        return ""

    return clean(card.get_text(" ", strip=True))


# =====================================
# TEAMS
# =====================================

def extract_teams(soup, url, event, card):
    home, home_logo = team_info(event.get("homeTeam"))
    away, away_logo = team_info(event.get("awayTeam"))

    if home and away:
        return home, away, home_logo, away_logo

    title = ""

    h1 = soup.find("h1")
    if h1:
        title = clean(h1.get_text(" ", strip=True))

    if not title:
        meta = soup.find(
            "meta",
            property="og:title"
        )
        if meta:
            title = clean(meta.get("content"))

    patterns = [
        r"(.+?)\s+(?:Vs|vs|VS)\s+(.+)",
        r"مباراة\s+(.+?)\s+و\s+(.+)",
    ]

    for pattern in patterns:
        m = re.search(pattern, title)

        if m:
            first = clean(m.group(1))
            second = clean(m.group(2))

            first = re.sub(
                r"^(بث مباشر|يلا شوت)\s*",
                "",
                first
            )

            second = re.sub(
                r"\s*(بث مباشر|يلا شوت)$",
                "",
                second
            )

            if first and second:
                return first, second, home_logo, away_logo

    slug = unquote(
        urlparse(url).path.rstrip("/").split("/")[-1]
    )

    slug = slug.replace("مباراة-", "").replace("-", " ")

    if " و " in slug:
        parts = slug.split(" و ", 1)

        if len(parts) == 2:
            return (
                clean(parts[0]),
                clean(parts[1]),
                home_logo,
                away_logo
            )

    return home, away, home_logo, away_logo


# =====================================
# TEAM LOGOS
# =====================================

def find_logo_by_team(card, team_name):
    if not card or not team_name:
        return ""

    team_normal = clean(team_name).lower()

    for img in card.find_all("img"):
        labels = " ".join([
            str(img.get("alt", "")),
            str(img.get("title", "")),
            str(img.get("data-team", "")),
            str(img.get("class", "")),
        ]).lower()

        if team_normal in labels:
            src = (
                img.get("data-src")
                or img.get("data-lazy-src")
                or img.get("data-original")
                or img.get("src")
            )

            return image_url(src)

    return ""


def extract_logos(card, home, away, home_logo, away_logo):
    if not home_logo:
        home_logo = find_logo_by_team(card, home)

    if not away_logo:
        away_logo = find_logo_by_team(card, away)

    return home_logo, away_logo


# =====================================
# DATE AND TIME
# =====================================

def parse_iso_datetime(value):
    if not value:
        return None

    value = str(value).strip()

    try:
        dt = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        # إذا المصدر أعطى توقيتاً مع منطقة زمنية،
        # نحوله إلى توقيت بغداد.
        if dt.tzinfo is not None:
            return dt.astimezone(TZ)

        # إذا لم يذكر المصدر المنطقة الزمنية،
        # نحافظ على الساعة كما هي دون إضافة ساعة.
        return dt.replace(tzinfo=TZ)

    except Exception:
        return None


def extract_datetime(soup, event, fallback_day, card):
    # أولاً: التاريخ من بيانات المباراة المنظمة
    start = event.get("startDate")

    dt = parse_iso_datetime(start)

    if dt:
        return dt

    # ثانياً: عناصر الوقت والتاريخ في الصفحة
    for tag in soup.find_all(
        ["time"],
        attrs={"datetime": True}
    ):
        dt = parse_iso_datetime(tag.get("datetime"))

        if dt:
            return dt

    for tag in soup.select(
        '[itemprop="startDate"], [data-start], [data-datetime]'
    ):
        value = (
            tag.get("content")
            or tag.get("datetime")
            or tag.get("data-start")
            or tag.get("data-datetime")
        )

        dt = parse_iso_datetime(value)

        if dt:
            return dt

    # ثالثاً: الوقت الظاهر في النص
    text = clean(soup.get_text(" ", strip=True))

    if not text and card:
        text = card_text(card)

    time_match = re.search(
        r"(?:الساعة\s*)?(\d{1,2}):(\d{2})\s*(AM|PM)?",
        text,
        re.I
    )

    if not time_match:
        return None

    hour = int(time_match.group(1))
    minute = int(time_match.group(2))
    period = (time_match.group(3) or "").upper()

    if period == "PM" and hour != 12:
        hour += 12
    elif period == "AM" and hour == 12:
        hour = 0

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None

    # تاريخ اليوم حسب صفحة المباريات
    today = datetime.now(TZ).date()

    offsets = {
        "today": 0,
        "yesterday": -1,
        "tomorrow": 1,
    }

    match_date = today + timedelta(
        days=offsets[fallback_day]
    )

    # لا نضيف أي ساعة من عندنا.
    return datetime(
        match_date.year,
        match_date.month,
        match_date.day,
        hour,
        minute,
        tzinfo=TZ
    )


# =====================================
# SCORE
# =====================================

def extract_score(soup, event, card):
    # نتيجة صريحة من بيانات المباراة
    for key in [
        "score",
        "result",
    ]:
        value = event.get(key)

        if isinstance(value, str):
            m = re.search(
                r"(\d{1,2})\s*[-–]\s*(\d{1,2})",
                value
            )

            if m:
                return m.group(1) + "-" + m.group(2)

    # نبحث عن عناصر تحمل أسماء خاصة بالنتيجة
    selectors = [
        ".match-score",
        ".score",
        ".result",
        ".team-score",
        "[data-score]",
        "[itemprop='score']",
    ]

    for selector in selectors:
        for tag in soup.select(selector):
            value = clean(
                tag.get("data-score")
                or tag.get_text(" ", strip=True)
            )

            m = re.fullmatch(
                r"(\d{1,2})\s*[-–]\s*(\d{1,2})",
                value
            )

            if m:
                return m.group(1) + "-" + m.group(2)

    # لا نستخدم النقطتين هنا أبداً؛
    # حتى لا يتحول 17:30 إلى 7-30.
    if card:
        for tag in card.select(
            ".score, .match-score, .result, [data-score]"
        ):
            value = clean(
                tag.get("data-score")
                or tag.get_text(" ", strip=True)
            )

            m = re.fullmatch(
                r"(\d{1,2})\s*[-–]\s*(\d{1,2})",
                value
            )

            if m:
                return m.group(1) + "-" + m.group(2)

    return ""


# =====================================
# STATUS
# =====================================

def extract_status(text, score):
    text = clean(text)

    if any(x in text for x in [
        "انتهت",
        "نهاية المباراة",
        "مباراة انتهت",
    ]):
        return "ended"

    if any(x in text for x in [
        "مباشر",
        "جارية",
        "الشوط الأول",
        "الشوط الثاني",
    ]):
        return "live"

    return "upcoming"


# =====================================
# CHANNEL / COMMENTATOR / LEAGUE
# =====================================

def extract_channel(text):
    patterns = [
        r"القناة المدرجة في بيانات المباراة هي\s*(.+?)(?:\.|،|$)",
        r"اسم القناة\s*[:：]?\s*(.+?)(?:\s+المعلق|\s+البطولة|$)",
        r"القناة الناقلة\s*[:：]?\s*(.+?)(?:\s+المعلق|$)",
    ]

    for pattern in patterns:
        m = re.search(pattern, text, re.I)

        if m:
            return clean(m.group(1)).strip(" .،")

    return ""


def extract_commentator(text):
    patterns = [
        r"يتولى\s+(.+?)\s+التعليق",
        r"المعلق\s*[:：]?\s*(.+?)(?:\s+البطولة|$)",
        r"المعلق الصوتي\s*[:：]?\s*(.+?)(?:\s+البطولة|$)",
    ]

    for pattern in patterns:
        m = re.search(pattern, text, re.I)

        if m:
            return clean(m.group(1)).strip(" .،")

    return ""


def extract_league(text):
    patterns = [
        r"ضمن منافسات\s*(.+?)(?:\.|،|$)",
        r"بطولة\s+(.+?)(?:\.|،|$)",
        r"البطولة\s*(.+?)(?:\s+تاريخ المباراة|$)",
    ]

    for pattern in patterns:
        m = re.search(pattern, text, re.I)

        if m:
            value = clean(m.group(1)).strip(" .،")

            if len(value) < 120:
                return value

    return ""


# =====================================
# PARSE MATCH
# =====================================

def parse_match(url, day, listing_soup):
    soup = get_soup(url)

    if not soup:
        return None

    card = find_card(listing_soup, url)
    text = clean(soup.get_text(" ", strip=True))
    ctext = card_text(card)

    structured = read_jsonld(soup)
    event = find_event(structured)

    home, away, home_logo, away_logo = extract_teams(
        soup,
        url,
        event,
        card
    )

    if not home or not away:
        print("Team names missing:", url)
        return None

    dt = extract_datetime(
        soup,
        event,
        day,
        card
    )

    if not dt:
        print("Match time missing:", home, away)
        return None

    home_logo, away_logo = extract_logos(
        card,
        home,
        away,
        home_logo,
        away_logo
    )

    score = extract_score(
        soup,
        event,
        card
    )

    status = extract_status(
        ctext or text,
        score
    )

    channel = extract_channel(text)
    commentator = extract_commentator(text)
    league = extract_league(text)

    if not channel:
        channel = extract_channel(ctext)

    if not league:
        league = extract_league(ctext)

    return {
        "league": league,
        "home": home,
        "away": away,
        "team1": home,
        "team2": away,
        "home_img": home_logo,
        "away_img": away_logo,
        "hour": dt.strftime("%H:%M"),
        "time": dt.strftime("%H:%M"),
        "date": dt.strftime("%Y-%m-%d"),
        "match_date": dt.strftime("%Y-%m-%d"),
        "status": status,
        "score": score,
        "channel": channel,
        "commentator": commentator,
        "streamUrl": ""
    }


# =====================================
# SAVE JSON SAFELY
# =====================================

def save_json(data):
    content = json.dumps(
        data,
        ensure_ascii=False,
        indent=2
    ) + "\n"

    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=".",
            delete=False
        ) as f:
            f.write(content)
            temp_path = f.name

        os.replace(temp_path, OUTPUT)

    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


# =====================================
# MAIN
# =====================================

def main():
    print("=" * 45)
    print("YALLA KORA - SHOT WIKI")
    print("=" * 45)

    all_matches = {}

    for day in [
        "yesterday",
        "today",
        "tomorrow"
    ]:
        print("\nLoading:", day)

        listing_soup = get_soup(PAGES[day])

        if not listing_soup:
            print("Could not load:", day)
            continue

        links = collect_links(listing_soup)

        print("Matches found:", len(links))

        for index, url in enumerate(links, 1):
            print(f"Checking {index}/{len(links)}")

            try:
                match = parse_match(
                    url,
                    day,
                    listing_soup
                )

                if match:
                    key = (
                        match["date"],
                        match["home"],
                        match["away"]
                    )

                    all_matches[key] = match

                    print(
                        "OK:",
                        match["home"],
                        "-",
                        match["away"],
                        match["hour"],
                        "Score:",
                        match["score"]
                    )

            except Exception as e:
                print("Match error:", e)

            time.sleep(DELAY)

    matches = list(all_matches.values())

    today_date = datetime.now(TZ).date()

    today = [
        m for m in matches
        if m["date"] == today_date.isoformat()
    ]

    yesterday_date = (
        today_date - timedelta(days=1)
    ).isoformat()

    tomorrow_date = (
        today_date + timedelta(days=1)
    ).isoformat()

    yesterday = [
        m for m in matches
        if m["date"] == yesterday_date
    ]

    tomorrow = [
        m for m in matches
        if m["date"] == tomorrow_date
    ]

    if not today:
        raise RuntimeError(
            "No matches for today. "
            "Old matches.json was preserved."
        )

    now = datetime.now(TZ)

    data = {
        "success": True,
        "updated_at": now.isoformat(),
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

    save_json(data)

    print("\n" + "=" * 45)
    print("UPDATE COMPLETE")
    print("Today:", len(today))
    print("Yesterday:", len(yesterday))
    print("Tomorrow:", len(tomorrow))
    print("=" * 45)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("\nUPDATE FAILED:", e)
        sys.exit(1)
    
