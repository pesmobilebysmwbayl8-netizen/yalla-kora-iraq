# ============================================================
# YALLA KORA - FIVE SOURCES DYNAMIC ENGINE
# Dynamic pages discovery + match refresh
# Timezone: Asia/Baghdad
# Output: matches.json
# ============================================================

import json
import os
import re
import html
import unicodedata
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urljoin, urlparse
from difflib import SequenceMatcher

import requests
from bs4 import BeautifulSoup

TZ = ZoneInfo("Asia/Baghdad")
NOW = datetime.now(TZ)
TODAY = NOW.date()
OUTPUT = "matches.json"

# المصادر الخمسة نفسها، بدون إضافة API
SOURCES = {
    "asgoal": "https://as-goal.net/",
    "filgoal": "https://www.filgoal.com/",
    "talknow": "https://talknow.online/",
    "original": "https://originalpro.online/",
    "almashhad": "https://www.almashhad.com/"
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 10) "
        "AppleWebKit/537.36 Chrome/130.0 Mobile Safari/537.36"
    ),
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8"
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

STATS = {
    "asgoal": 0,
    "filgoal": 0,
    "talknow": 0,
    "original": 0,
    "almashhad": 0,
    "channels": 0,
    "commentators": 0,
    "with_home_image": 0,
    "with_away_image": 0,
    "errors": 0,
    "rejected_cards": 0,
    "status_updates": 0,
    "score_updates": 0
}

MONTHS = {
    "يناير": 1, "فبراير": 2, "مارس": 3,
    "أبريل": 4, "ابريل": 4, "مايو": 5,
    "يونيو": 6, "يوليو": 7, "أغسطس": 8,
    "اغسطس": 8, "سبتمبر": 9, "أكتوبر": 10,
    "اكتوبر": 10, "نوفمبر": 11, "ديسمبر": 12
}


def log(text):
    print(text, flush=True)


def clean(value):
    value = html.unescape(str(value or ""))
    value = unicodedata.normalize("NFKC", value)
    value = value.replace("ـ", "")
    return re.sub(r"\s+", " ", value).strip(" \t\r\n|:-–—")


def norm(value):
    value = clean(value).lower()

    for a, b in {
        "أ": "ا", "إ": "ا", "آ": "ا",
        "ى": "ي", "ة": "ه"
    }.items():
        value = value.replace(a, b)

    return re.sub(r"[^a-z0-9\u0600-\u06ff]", "", value)


def fetch(url):
    try:
        response = SESSION.get(url, timeout=25)
        response.raise_for_status()

        if not response.encoding or response.encoding.lower() == "iso-8859-1":
            response.encoding = response.apparent_encoding

        return response.text

    except Exception as exc:
        STATS["errors"] += 1
        log(f"FETCH ERROR: {url} | {exc}")
        return ""


def parse_date(text, default=None):
    text = clean(text)

    patterns = [
        r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b",
        r"\b(\d{4})[/-](\d{1,2})[/-](\d{1,2})\b"
    ]

    m = re.search(patterns[0], text)

    if m:
        try:
            return datetime(
                int(m.group(3)),
                int(m.group(2)),
                int(m.group(1))
            ).date().isoformat()
        except ValueError:
            pass

    m = re.search(patterns[1], text)

    if m:
        try:
            return datetime(
                int(m.group(1)),
                int(m.group(2)),
                int(m.group(3))
            ).date().isoformat()
        except ValueError:
            pass

    m = re.search(
        r"(\d{1,2})\s+("
        + "|".join(MONTHS.keys())
        + r")\s+(\d{4})",
        text
    )

    if m:
        try:
            return datetime(
                int(m.group(3)),
                MONTHS[m.group(2)],
                int(m.group(1))
            ).date().isoformat()
        except ValueError:
            pass

    return default.isoformat() if hasattr(default, "isoformat") else (
        default or ""
    )


def parse_time(text):
    m = re.search(
        r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)",
        clean(text)
    )

    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}"

    return ""


def status_value(text):
    t = norm(text)

    if any(x in t for x in (
        "مباشر", "live", "جاريهالان",
        "الشوطالاول", "الشوطالثاني", "استراحه"
    )):
        return "live"

    if any(x in t for x in (
        "انتهت", "نهايهالمباراه",
        "fulltime", "finished", "ended"
    )):
        return "ended"

    if any(x in t for x in (
        "تاجلت", "مؤجله", "postponed",
        "cancelled", "ملغاه"
    )):
        return "postponed"

    if any(x in t for x in (
        "لمتبدا", "لمتبدأ", "لم تبدأ",
        "upcoming", "scheduled"
    )):
        return "upcoming"

    return ""


def valid_score(value):
    value = clean(value)

    m = re.fullmatch(
        r"(\d{1,2})\s*[-–:]\s*(\d{1,2})",
        value
    )

    if not m:
        return ""

    a, b = int(m.group(1)), int(m.group(2))

    if 0 <= a <= 15 and 0 <= b <= 15:
        return f"{a} - {b}"

    return ""


def extract_score(text):
    m = re.search(
        r"(?:نتيجة المباراة|النتيجة|score|result)"
        r"\s*[:：]?\s*(\d{1,2})\s*[-–:]\s*(\d{1,2})",
        clean(text),
        re.I
    )

    if m:
        return valid_score(m.group(1) + " - " + m.group(2))

    return ""


def arabic_name(value):
    value = clean(value)

    aliases = [
        (r"(?i)abu\s*dhabi\s*sports?\s*premium\s*(\d+)?",
         "أبو ظبي الرياضية بريميوم"),
        (r"(?i)abu\s*dhabi\s*sports?\s*(\d+)?",
         "أبو ظبي الرياضية"),
        (r"(?i)dubai\s*sports?\s*(\d+)?",
         "دبي الرياضية"),
        (r"(?i)be\s*in\s*sports?\s*(\d+)?",
         "بي إن سبورت"),
        (r"(?i)on\s*sport\s*(\d+)?",
         "أون سبورت"),
        (r"(?i)ssc\s*(\d+)?",
         "إس إس سي"),
        (r"(?i)al[- ]?kass\s*(\d+)?",
         "الكأس"),
        (r"(?i)mbc\s*shahid",
         "إم بي سي شاهد"),
        (r"(?i)shahid",
         "شاهد"),
        (r"(?i)starz\s*play",
         "ستارز بلاي")
    ]

    for pattern, arabic in aliases:
        m = re.search(pattern, value)

        if m:
            number = m.group(1) if m.lastindex else ""
            return clean(arabic + (" " + number if number else ""))

    chunks = re.findall(
        r"[\u0600-\u06ff][\u0600-\u06ff\s.ـ'-]*",
        value
    )

    return clean(chunks[0]) if chunks else ""


def valid_team(name):
    name = clean(name)
    key = norm(name)

    invalid = {
        "", "مصر", "جدولالمباريات",
        "مبارياتاليوم", "مبارياتالامس",
        "مبارياتالغد", "لمتبدا",
        "مباشر", "انتهت", "home", "away", "vs"
    }

    if key in invalid:
        return False

    if len(name) < 2 or len(name) > 55:
        return False

    if re.search(r"(?:\d{1,2}:\d{2}|https?://)", name):
        return False

    return True


def new_match(
    home, away, date, hour="",
    league="", channel="", commentator="",
    home_img="", away_img="",
    status="", score=""
):
    home = clean(home)
    away = clean(away)

    if not valid_team(home) or not valid_team(away):
        STATS["rejected_cards"] += 1
        return None

    if norm(home) == norm(away):
        return None

    return {
        "league": clean(league),
        "home": home,
        "away": away,
        "team1": home,
        "team2": away,
        "home_img": home_img or "",
        "away_img": away_img or "",
        "hour": hour or "",
        "time": hour or "",
        "date": date or TODAY.isoformat(),
        "match_date": date or TODAY.isoformat(),
        "status": status or "upcoming",
        "score": score or "",
        "channel": clean(channel),
        "commentator": clean(commentator),
        "streamUrl": "",
        "_status_confirmed": bool(status),
        "_score_confirmed": bool(score)
    }


# ------------------------------------------------------------
# اكتشاف الصفحات المتجددة من كل موقع
# ------------------------------------------------------------

def discover_pages(source_name, homepage):
    pages = [homepage]

    base = urlparse(homepage)
    root = f"{base.scheme}://{base.netloc}"

    sitemap_urls = [
        root + "/sitemap.xml",
        root + "/sitemap_index.xml"
    ]

    for sitemap in sitemap_urls:
        xml = fetch(sitemap)

        if not xml:
            continue

        soup = BeautifulSoup(xml, "xml")

        for loc in soup.find_all("loc"):
            url = clean(loc.get_text())

            if url.startswith("http"):
                if url not in pages:
                    pages.append(url)

            if len(pages) >= 30:
                break

        if len(pages) >= 30:
            break

    # استخراج روابط صفحات المباريات من الصفحة الرئيسية
    home_html = fetch(homepage)

    if home_html:
        soup = BeautifulSoup(home_html, "html.parser")

        for a in soup.find_all("a", href=True):
            url = urljoin(homepage, a["href"])
            parsed = urlparse(url)

            if parsed.netloc != base.netloc:
                continue

            text = norm(a.get_text(" ", strip=True))
            path = norm(parsed.path)

            match_words = (
                "match", "matches", "live",
                "مباراه", "مباريات", "جدول"
            )

            if any(x in path or x in text for x in match_words):
                if url not in pages:
                    pages.append(url)

            if len(pages) >= 40:
                break

    log(f"{source_name.upper()} DISCOVERED PAGES: {len(pages)}")

    return pages[:40]


# ------------------------------------------------------------
# قراءة المباريات من JSON-LD
# ------------------------------------------------------------

def parse_json_events(page):
    soup = BeautifulSoup(page, "html.parser")
    output = []

    for script in soup.find_all(
        "script",
        type="application/ld+json"
    ):
        try:
            data = json.loads(
                script.string or script.get_text()
            )
        except Exception:
            continue

        stack = data if isinstance(data, list) else [data]

        while stack:
            obj = stack.pop()

            if isinstance(obj, list):
                stack.extend(obj)
                continue

            if not isinstance(obj, dict):
                continue

            if "@graph" in obj:
                stack.append(obj["@graph"])

            types = obj.get("@type", [])

            if isinstance(types, str):
                types = [types]

            if not any("SportsEvent" in x for x in types):
                continue

            home = obj.get("homeTeam", {})
            away = obj.get("awayTeam", {})

            if isinstance(home, list):
                home = home[0] if home else {}

            if isinstance(away, list):
                away = away[0] if away else {}

            if not isinstance(home, dict) or not isinstance(away, dict):
                continue

            start = clean(obj.get("startDate", ""))
            date = TODAY.isoformat()
            hour = ""

            if start:
                try:
                    parsed = datetime.fromisoformat(
                        start.replace("Z", "+00:00")
                    )

                    if parsed.tzinfo:
                        parsed = parsed.astimezone(TZ)

                    date = parsed.date().isoformat()
                    hour = parsed.strftime("%H:%M")

                except Exception:
                    pass

            state = status_value(
                clean(obj.get("eventStatus", "")) + " " +
                clean(obj.get("description", ""))
            )

            score = ""

            competitors = obj.get("competitor", [])

            if isinstance(competitors, list) and len(competitors) >= 2:
                values = []

                for competitor in competitors[:2]:
                    value = (
                        competitor.get("score")
                        if isinstance(competitor, dict)
                        else None
                    )

                    values.append(str(value) if value is not None else "")

                if all(x.isdigit() for x in values):
                    score = valid_score(
                        values[0] + " - " + values[1]
                    )

            item = new_match(
                home.get("name", ""),
                away.get("name", ""),
                date,
                hour,
                obj.get("sport", ""),
                status=state,
                score=score
            )

            if item:
                output.append(item)

    return output


# ------------------------------------------------------------
# قراءة بطاقات المباريات من HTML
# ------------------------------------------------------------

def parse_html_cards(page, source_url):
    soup = BeautifulSoup(page, "html.parser")
    output = []

    selectors = [
        "[class*='match']",
        "[class*='fixture']",
        "[class*='event']",
        "[class*='game']",
        "[class*='match-card']"
    ]

    found = []

    for selector in selectors:
        try:
            found.extend(soup.select(selector))
        except Exception:
            pass

    seen = set()

    for card in found:
        try:
            text = clean(card.get_text(" ", strip=True))

            if not text or len(text) > 1500:
                continue

            key = norm(text)

            if key in seen:
                continue

            seen.add(key)

            # استخراج أسماء الفرق من العناوين أو العناصر
            team_names = []

            for selector in [
                "[class*='team-name']",
                "[class*='team']",
                "[class*='club']",
                "[class*='participant']"
            ]:
                for element in card.select(selector):
                    name = clean(element.get_text(" ", strip=True))

                    if valid_team(name) and norm(name) not in [
                        norm(x) for x in team_names
                    ]:
                        team_names.append(name)

            # احتياط: استخراج اسمين من النص عند وجود VS أو ضد
            if len(team_names) < 2:
                m = re.search(
                    r"(.{2,45}?)\s+(?:vs\.?|ضد)\s+(.{2,45})",
                    text,
                    re.I
                )

                if m:
                    team_names = [
                        clean(m.group(1)),
                        clean(m.group(2))
                    ]

            if len(team_names) < 2:
                continue

            date = parse_date(text, TODAY)
            hour = parse_time(text)
            state = status_value(text)
            score = extract_score(text)

            league = ""

            league_element = card.select_one(
                "[class*='league'], [class*='competition']"
            )

            if league_element:
                league = clean(
                    league_element.get_text(" ", strip=True)
                )

            images = card.find_all("img")
            image_urls = []

            for img in images[:2]:
                src = (
                    img.get("src") or
                    img.get("data-src") or
                    img.get("data-lazy-src")
                )

                if src:
                    image_urls.append(urljoin(source_url, src))

            home_img = image_urls[0] if len(image_urls) > 0 else ""
            away_img = image_urls[1] if len(image_urls) > 1 else ""

            item = new_match(
                team_names[0],
                team_names[1],
                date,
                hour,
                league,
                home_img=home_img,
                away_img=away_img,
                status=state,
                score=score
            )

            if item:
                output.append(item)

        except Exception:
            continue

    return output


# ------------------------------------------------------------
# استخراج القناة والمعلق من صفحات AS GOAL
# ------------------------------------------------------------

def parse_asgoal_detail(url):
    page = fetch(url)

    if not page:
        return None

    soup = BeautifulSoup(page, "html.parser")

    title = clean(
        soup.title.get_text(" ", strip=True)
        if soup.title else ""
    )

    h1 = soup.find("h1")

    heading = clean(
        h1.get_text(" ", strip=True)
        if h1 else title
    )

    patterns = [
        r"مباراة\s+(.+?)\s+ضد\s+(.+?)\s+في\s+(.+)",
        r"(.+?)\s+vs\.?\s+(.+?)\s*[-|]\s*(.+)"
    ]

    match = None

    for pattern in patterns:
        match = re.search(pattern, heading, re.I)

        if match:
            break

    if not match:
        return None

    home, away, league = map(clean, match.groups())
    text = clean(soup.get_text(" ", strip=True))

    date = parse_date(text, TODAY)
    hour = parse_time(text)
    state = status_value(text)

    score = (
        extract_score(text)
        if state in ("live", "ended")
        else ""
    )

    channel = ""
    commentator = ""

    labels = [
        r"(?:القناة الناقلة|Channel)\s*[:：]?\s*(.{2,60})",
        r"(?:المعلّق|المعلق|Commentator)\s*[:：]?\s*(.{2,60})"
    ]

    m = re.search(labels[0], text, re.I)

    if m:
        channel = arabic_name(m.group(1).split("المعل")[0])

    m = re.search(labels[1], text, re.I)

    if m:
        commentator = arabic_name(m.group(1).split("ملعب")[0])

    return new_match(
        home,
        away,
        date,
        hour,
        league,
        channel,
        commentator,
        status=state,
        score=score
    )


# ------------------------------------------------------------
# تشغيل مصدر واحد واكتشاف صفحاته تلقائياً
# ------------------------------------------------------------

def run_source(name):
    log("=" * 45)
    log("SOURCE: " + name.upper())

    homepage = SOURCES[name]
    pages = discover_pages(name, homepage)

    output = []
    detail_urls = []

    for page_url in pages:
        page = fetch(page_url)

        if not page:
            continue

        # المباريات المنظمة
        output.extend(parse_json_events(page))

        # بطاقات المباريات
        output.extend(parse_html_cards(page, page_url))

        # روابط صفحات المباريات
        if name == "asgoal":
            soup = BeautifulSoup(page, "html.parser")

            for a in soup.find_all("a", href=True):
                url = urljoin(page_url, a["href"])

                if urlparse(url).netloc != urlparse(homepage).netloc:
                    continue

                if re.search(
                    r"/matches/[^/?#]+",
                    url
                ):
                    if url not in detail_urls:
                        detail_urls.append(url)

    if name == "asgoal":
        for index, url in enumerate(detail_urls[:60], 1):
            log(f"ASGOAL DETAIL {index}/{min(len(detail_urls), 60)}")

            item = parse_asgoal_detail(url)

            if item:
                output.append(item)

    # إزالة التكرار داخل المصدر
    unique = []

    for item in output:
        if not item:
            continue

        if not any(matches_same(item, old) for old in unique):
            unique.append(item)

    STATS[name] = len(unique)

    log(
        f"{name.upper()} MATCHES FOUND: {len(unique)}"
    )

    return unique


# ------------------------------------------------------------
# دمج المباريات ومنع التكرار
# ------------------------------------------------------------

def matches_same(a, b):
    if a.get("date") != b.get("date"):
        return False

    ah, aa, bh, ba = map(
        norm,
        (
            a.get("home"),
            a.get("away"),
            b.get("home"),
            b.get("away")
        )
    )

    if not all((ah, aa, bh, ba)):
        return False

    sim = lambda x, y: (
        SequenceMatcher(None, x, y).ratio() >= 0.88
    )

    return (
        sim(ah, bh) and sim(aa, ba)
    ) or (
        sim(ah, ba) and sim(aa, bh)
    )


def merge(records, incoming):
    for item in incoming:
        if not item:
            continue

        existing = next(
            (
                old for old in records
                if matches_same(old, item)
            ),
            None
        )

        if existing is None:
            records.append(item)
            continue

        for field in (
            "league", "channel", "commentator",
            "home_img", "away_img", "streamUrl"
        ):
            if item.get(field) and not existing.get(field):
                existing[field] = item[field]

        if item.get("_status_confirmed"):
            if existing.get("status") != item["status"]:
                existing["status"] = item["status"]
                STATS["status_updates"] += 1

        if item.get("_score_confirmed") and item.get("score"):
            if existing.get("score") != item["score"]:
                existing["score"] = item["score"]
                STATS["score_updates"] += 1

        if item.get("hour") and not existing.get("hour"):
            existing["hour"] = item["hour"]
            existing["time"] = item["hour"]

    return records


def remove_internal_fields(records):
    for item in records:
        item.pop("_status_confirmed", None)
        item.pop("_score_confirmed", None)

    return records


# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------

def main():
    log("=" * 55)
    log("YALLA KORA - DYNAMIC FIVE SOURCES")
    log("NOW: " + NOW.isoformat())
    log("=" * 55)

    matches = []

    # الاحتفاظ بالمباريات السابقة عند تعطل مصدر مؤقتاً
    if os.path.exists(OUTPUT):
        try:
            with open(OUTPUT, "r", encoding="utf-8") as file:
                previous = json.load(file)

            old_matches = previous.get("matches", [])

            if isinstance(old_matches, list):
                for old in old_matches:
                    if not isinstance(old, dict):
                        continue

                    if not old.get("home") or not old.get("away"):
                        continue

                    old = dict(old)
                    old["score"] = valid_score(old.get("score", ""))

                    old["_status_confirmed"] = False
                    old["_score_confirmed"] = False

                    matches.append(old)

            log(
                "PREVIOUS MATCHES RESTORED: "
                + str(len(matches))
            )

        except Exception as exc:
            log("PREVIOUS JSON WARNING: " + str(exc))

    # المصادر الخمسة
    for source in (
        "asgoal",
        "filgoal",
        "talknow",
        "original",
        "almashhad"
    ):
        try:
            incoming = run_source(source)
            merge(matches, incoming)

        except Exception as exc:
            STATS["errors"] += 1
            log(f"SOURCE ERROR [{source}]: {exc}")

    yesterday = (TODAY - timedelta(days=1)).isoformat()
    today = TODAY.isoformat()
    tomorrow = (TODAY + timedelta(days=1)).isoformat()

    # الاحتفاظ بالأمس واليوم والغد
    matches = [
        item for item in matches
        if item.get("date") in (
            yesterday,
            today,
            tomorrow
        )
    ]

    matches.sort(
        key=lambda item: (
            item.get("date", ""),
            item.get("hour", ""),
            norm(item.get("home", ""))
        )
    )

    # VS إذا لم توجد نتيجة صحيحة
    for item in matches:
        item["score"] = (
            valid_score(item.get("score", ""))
            or "VS"
        )

    remove_internal_fields(matches)

    today_list = [
        x for x in matches
        if x.get("date") == today
    ]

    yesterday_list = [
        x for x in matches
        if x.get("date") == yesterday
    ]

    tomorrow_list = [
        x for x in matches
        if x.get("date") == tomorrow
    ]

    STATS["channels"] = sum(
        bool(x.get("channel")) for x in matches
    )

    STATS["commentators"] = sum(
        bool(x.get("commentator")) for x in matches
    )

    STATS["with_home_image"] = sum(
        bool(x.get("home_img")) for x in matches
    )

    STATS["with_away_image"] = sum(
        bool(x.get("away_img")) for x in matches
    )

    output = {
        "version": "V18-DYNAMIC-FIVE-SOURCES",
        "updated_at": datetime.now(TZ).isoformat(),
        "timezone": "Asia/Baghdad",
        "matches": matches,
        "today": today_list,
        "yesterday": yesterday_list,
        "tomorrow": tomorrow_list,
        "counts": {
            "total": len(matches),
            "today": len(today_list),
            "yesterday": len(yesterday_list),
            "tomorrow": len(tomorrow_list),
            "with_channel": STATS["channels"],
            "with_commentator": STATS["commentators"],
            "with_home_image": STATS["with_home_image"],
            "with_away_image": STATS["with_away_image"]
        },
        "sources": STATS
    }

    temp_file = OUTPUT + ".tmp"

    with open(temp_file, "w", encoding="utf-8") as file:
        json.dump(
            output,
            file,
            ensure_ascii=False,
            indent=2
        )

    os.replace(temp_file, OUTPUT)

    log("=" * 55)
    log("FINISHED")
    log(
        "COUNTS: "
        + json.dumps(output["counts"], ensure_ascii=False)
    )
    log(
        "SOURCE STATS: "
        + json.dumps(STATS, ensure_ascii=False)
    )
    log("=" * 55)


if __name__ == "__main__":
    main()
