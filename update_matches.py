
# ============================================================
# YALLA KORA - SMART EXTRACTION ENGINE V19
# Same 5 sources | Same matches.json structure
# Timezone: Asia/Baghdad
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

SOURCES = {
    "asgoal": "https://as-goal.net/",
    "filgoal": "https://www.filgoal.com/",
    "talknow": "https://talknow.online/",
    "original": "https://originalpro.online/",
    "almashhad": "https://www.almashhad.com/"
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 10; Mobile) "
        "AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8"
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

STATS = {
    name: 0 for name in SOURCES
}
STATS.update({
    "channels": 0,
    "commentators": 0,
    "with_home_image": 0,
    "with_away_image": 0,
    "errors": 0,
    "rejected_cards": 0,
    "status_updates": 0,
    "score_updates": 0
})

MONTHS = {
    "يناير": 1, "فبراير": 2, "مارس": 3,
    "أبريل": 4, "ابريل": 4, "مايو": 5,
    "يونيو": 6, "يوليو": 7, "أغسطس": 8,
    "اغسطس": 8, "سبتمبر": 9, "أكتوبر": 10,
    "اكتوبر": 10, "نوفمبر": 11, "ديسمبر": 12
}


def log(message):
    print(message, flush=True)


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
        log("FETCH ERROR: " + url + " | " + str(exc))
        return ""


def parse_date(value, default=None):
    text = clean(value)

    patterns = [
        (r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", "dmy"),
        (r"\b(\d{4})[/-](\d{1,2})[/-](\d{1,2})\b", "ymd")
    ]

    for pattern, mode in patterns:
        match = re.search(pattern, text)

        if match:
            try:
                if mode == "dmy":
                    result = datetime(
                        int(match.group(3)),
                        int(match.group(2)),
                        int(match.group(1))
                    )
                else:
                    result = datetime(
                        int(match.group(1)),
                        int(match.group(2)),
                        int(match.group(3))
                    )

                return result.date().isoformat()
            except ValueError:
                pass

    month_pattern = (
        r"(\d{1,2})\s+("
        + "|".join(MONTHS)
        + r")\s+(\d{4})"
    )

    match = re.search(month_pattern, text)

    if match:
        try:
            return datetime(
                int(match.group(3)),
                MONTHS[match.group(2)],
                int(match.group(1))
            ).date().isoformat()
        except ValueError:
            pass

    if hasattr(default, "isoformat"):
        return default.isoformat()

    return default or ""


def parse_time(value):
    match = re.search(
        r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)",
        clean(value)
    )

    if match:
        return f"{int(match.group(1)):02d}:{match.group(2)}"

    return ""


def valid_score(value):
    match = re.fullmatch(
        r"\s*(\d{1,2})\s*[-–:]\s*(\d{1,2})\s*",
        clean(value)
    )

    if not match:
        return ""

    a, b = int(match.group(1)), int(match.group(2))

    if a <= 15 and b <= 15:
        return f"{a} - {b}"

    return ""


def extract_score(text):
    patterns = [
        r"(?:النتيجة|نتيجة المباراة|score|result)"
        r"\s*[:：]?\s*(\d{1,2})\s*[-–:]\s*(\d{1,2})",
        r"\b(\d{1,2})\s*[-–]\s*(\d{1,2})\b"
    ]

    for pattern in patterns:
        match = re.search(pattern, clean(text), re.I)

        if match:
            score = valid_score(
                match.group(1) + "-" + match.group(2)
            )
            if score:
                return score

    return ""


def status_value(value):
    text = norm(value)

    if any(x in text for x in (
        "مباشر", "live", "جاريهالان",
        "الشوطالاول", "الشوطالثاني",
        "استراحه", "firsthalf", "secondhalf"
    )):
        return "live"

    if any(x in text for x in (
        "انتهت", "نهايهالمباراه",
        "fulltime", "finished", "ended"
    )):
        return "ended"

    if any(x in text for x in (
        "تاجلت", "مؤجله", "postponed",
        "cancelled", "ملغاه"
    )):
        return "postponed"

    if any(x in text for x in (
        "لمتبدا", "لمتبدأ", "upcoming",
        "scheduled", "لم تبدأ"
    )):
        return "upcoming"

    return ""


def valid_team(name):
    name = clean(name)
    key = norm(name)

    invalid = {
        "", "جدولالمباريات", "مبارياتاليوم",
        "مبارياتالامس", "مبارياتالغد",
        "لمتبدا", "مباشر", "انتهت",
        "home", "away", "vs", "كرةالقدم"
    }

    if key in invalid or len(name) < 2 or len(name) > 55:
        return False

    if re.search(r"\d{1,2}:\d{2}|https?://", name):
        return False

    return True


def image_url(element, base_url):
    if not element:
        return ""

    if element.name == "img":
        candidates = [
            element.get("data-src"),
            element.get("data-lazy-src"),
            element.get("data-original"),
            element.get("data-image"),
            element.get("src")
        ]

        srcset = element.get("srcset")

        if srcset:
            candidates.insert(
                0,
                srcset.split(",")[0].strip().split(" ")[0]
            )

        for src in candidates:
            if src and not src.startswith("data:"):
                return urljoin(base_url, src)

    for img in element.find_all("img"):
        result = image_url(img, base_url)

        if result:
            return result

    return ""


def find_team_image(card, team_element, team_name, base_url):
    # الصورة المرتبطة بعنصر الفريق نفسه أولاً
    result = image_url(team_element, base_url)

    if result:
        return result

    # البحث عن صورة تحمل اسم الفريق في alt أو title
    target = norm(team_name)

    for img in card.find_all("img"):
        label = norm(
            img.get("alt", "") + " " +
            img.get("title", "")
        )

        if target and (
            target in label or label in target
        ):
            result = image_url(img, base_url)

            if result:
                return result

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
        (r"(?i)mbc\s*shahid", "إم بي سي شاهد"),
        (r"(?i)shahid", "شاهد"),
        (r"(?i)starz\s*play", "ستارز بلاي")
    ]

    for pattern, arabic in aliases:
        match = re.search(pattern, value)

        if match:
            number = match.group(1) if match.lastindex else ""
            return clean(arabic + (" " + number if number else ""))

    chunks = re.findall(
        r"[\u0600-\u06ff][\u0600-\u06ff\s.ـ'-]*",
        value
    )

    return clean(chunks[0]) if chunks else ""


def make_match(
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

    date = date or TODAY.isoformat()

    return {
        "league": clean(league) or "كرة القدم",
        "home": home,
        "away": away,
        "team1": home,
        "team2": away,
        "home_img": home_img or "",
        "away_img": away_img or "",
        "hour": hour or "",
        "time": hour or "",
        "date": date,
        "match_date": date,
        "status": status or "upcoming",
        "score": score or "",
        "channel": clean(channel),
        "commentator": clean(commentator),
        "streamUrl": "",
        "_status_confirmed": bool(status),
        "_score_confirmed": bool(score)
    }


def discover_pages(homepage):
    pages = [homepage]
    root = urlparse(homepage)
    domain = root.netloc

    for path in ("/sitemap.xml", "/sitemap_index.xml"):
        data = fetch(urljoin(homepage, path))

        if not data:
            continue

        soup = BeautifulSoup(data, "xml")

        for loc in soup.find_all("loc"):
            url = clean(loc.get_text())

            if url.startswith("http") and urlparse(url).netloc == domain:
                if url not in pages:
                    pages.append(url)

            if len(pages) >= 25:
                break

        if len(pages) >= 25:
            break

    page = fetch(homepage)

    if page:
        soup = BeautifulSoup(page, "html.parser")

        for link in soup.find_all("a", href=True):
            url = urljoin(homepage, link["href"])
            parsed = urlparse(url)

            if parsed.netloc != domain:
                continue

            text = norm(link.get_text(" ", strip=True))
            path = norm(parsed.path)

            if any(word in path or word in text for word in (
                "match", "matches", "live",
                "مباراه", "مباريات", "جدول"
            )):
                if url not in pages:
                    pages.append(url)

            if len(pages) >= 40:
                break

    return pages[:40]


# ------------------------------------------------------------
# قراءة البيانات المنظمة والبيانات المضمّنة
# ------------------------------------------------------------

def walk_json(data):
    if isinstance(data, list):
        for item in data:
            yield from walk_json(item)

    elif isinstance(data, dict):
        yield data

        for value in data.values():
            if isinstance(value, (dict, list)):
                yield from walk_json(value)


def json_objects(soup):
    objects = []

    for script in soup.find_all("script"):
        script_type = clean(script.get("type", "")).lower()
        script_id = clean(script.get("id", "")).lower()

        if (
            "ld+json" in script_type
            or script_id == "__next_data__"
            or "application/json" in script_type
        ):
            raw = script.string or script.get_text()

            if not raw:
                continue

            try:
                data = json.loads(raw)
                objects.extend(walk_json(data))
            except Exception:
                continue

    return objects


def team_data(value):
    if isinstance(value, list):
        value = value[0] if value else {}

    if isinstance(value, str):
        return clean(value), ""

    if not isinstance(value, dict):
        return "", ""

    name = (
        value.get("name")
        or value.get("alternateName")
        or value.get("shortName")
        or ""
    )

    logo = value.get("logo") or value.get("image") or ""

    if isinstance(logo, dict):
        logo = logo.get("url", "")

    if isinstance(logo, list):
        logo = logo[0] if logo else ""

    if isinstance(logo, dict):
        logo = logo.get("url", "")

    return clean(name), clean(logo)


def parse_structured(page):
    soup = BeautifulSoup(page, "html.parser")
    output = []

    for obj in json_objects(soup):
        home_value = (
            obj.get("homeTeam")
            or obj.get("home_team")
            or obj.get("localTeam")
        )

        away_value = (
            obj.get("awayTeam")
            or obj.get("away_team")
            or obj.get("visitorTeam")
        )

        if not home_value or not away_value:
            continue

        home, home_logo = team_data(home_value)
        away, away_logo = team_data(away_value)

        if not valid_team(home) or not valid_team(away):
            continue

        start = clean(
            obj.get("startDate")
            or obj.get("start_time")
            or obj.get("date")
            or ""
        )

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
                date = parse_date(start, TODAY)
                hour = parse_time(start)

        state_text = (
            clean(obj.get("eventStatus", "")) + " " +
            clean(obj.get("status", "")) + " " +
            clean(obj.get("description", ""))
        )

        state = status_value(state_text)

        score = ""

        competitors = obj.get("competitor", [])

        if isinstance(competitors, list) and len(competitors) >= 2:
            values = []

            for competitor in competitors[:2]:
                if isinstance(competitor, dict):
                    values.append(str(competitor.get("score", "")))
                else:
                    values.append("")

            if all(x.isdigit() for x in values):
                score = valid_score(values[0] + "-" + values[1])

        if not score:
            score = valid_score(
                str(obj.get("homeScore", "")) + "-" +
                str(obj.get("awayScore", ""))
            )

        league = obj.get("name") or obj.get("sport") or ""

        item = make_match(
            home, away, date, hour,
            league=league,
            home_img=home_logo,
            away_img=away_logo,
            status=state,
            score=score
        )

        if item:
            output.append(item)

    return output


# ------------------------------------------------------------
# استخراج بطاقة المباراة بشكل منفصل
# ------------------------------------------------------------

TEAM_SELECTORS = [
    "[class*='team-name']",
    "[class*='team_name']",
    "[class*='participant']",
    "[class*='club-name']",
    "[class*='home-team']",
    "[class*='away-team']",
    "[class*='team']"
]

CARD_SELECTORS = [
    "[class*='match-card']",
    "[class*='match_item']",
    "[class*='match-item']",
    "[class*='fixture']",
    "[class*='event-card']",
    "[class*='match']"
]


def extract_team_elements(card):
    found = []

    for selector in TEAM_SELECTORS:
        try:
            elements = card.select(selector)
        except Exception:
            continue

        for element in elements:
            name = clean(element.get_text(" ", strip=True))

            if valid_team(name):
                if not any(
                    norm(name) == norm(old[0])
                    for old in found
                ):
                    found.append((name, element))

    return found[:2]


def extract_vs(text):
    match = re.search(
        r"([\u0600-\u06ffA-Za-z0-9 .'-]{2,45}?)"
        r"\s+(?:vs\.?|ضد)\s+"
        r"([\u0600-\u06ffA-Za-z0-9 .'-]{2,45})",
        clean(text),
        re.I
    )

    if not match:
        return "", ""

    home = clean(match.group(1))
    away = clean(match.group(2))

    if valid_team(home) and valid_team(away):
        return home, away

    return "", ""


def extract_channel(text):
    patterns = [
        r"(?:القناة الناقلة|القناة|Channel)"
        r"\s*[:：]?\s*([^|،]{2,55})",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.I)

        if match:
            return arabic_name(match.group(1))

    return ""


def extract_commentator(text):
    patterns = [
        r"(?:المعلق|المعلّق|Commentator)"
        r"\s*[:：]?\s*([^|،]{2,55})"
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.I)

        if match:
            return arabic_name(match.group(1))

    return ""


def parse_cards(page, source_url):
    soup = BeautifulSoup(page, "html.parser")
    output = []
    seen = set()

    for selector in CARD_SELECTORS:
        try:
            cards = soup.select(selector)
        except Exception:
            continue

        for card in cards:
            text = clean(card.get_text(" ", strip=True))

            if not text or len(text) > 1000:
                continue

            teams = extract_team_elements(card)

            if len(teams) >= 2:
                home, home_element = teams[0]
                away, away_element = teams[1]
            else:
                home, away = extract_vs(text)
                home_element = None
                away_element = None

            if not valid_team(home) or not valid_team(away):
                continue

            key = norm(home) + "|" + norm(away) + "|" + text[:100]

            if key in seen:
                continue

            seen.add(key)

            date = parse_date(text, TODAY)
            hour = parse_time(text)
            state = status_value(text)
            score = extract_score(text)

            league_element = card.select_one(
                "[class*='league'], [class*='competition'], "
                "[class*='tournament']"
            )

            league = (
                clean(league_element.get_text(" ", strip=True))
                if league_element else "كرة القدم"
            )

            home_img = find_team_image(
                card, home_element, home, source_url
            )

            away_img = find_team_image(
                card, away_element, away, source_url
            )

            item = make_match(
                home, away, date, hour,
                league=league,
                channel=extract_channel(text),
                commentator=extract_commentator(text),
                home_img=home_img,
                away_img=away_img,
                status=state,
                score=score
            )

            if item:
                output.append(item)

    return output


# ------------------------------------------------------------
# AS GOAL: قراءة صفحات تفاصيل المباريات
# ------------------------------------------------------------

def parse_asgoal_detail(url):
    page = fetch(url)

    if not page:
        return None

    soup = BeautifulSoup(page, "html.parser")
    title = clean(soup.title.get_text(" ", strip=True)) if soup.title else ""

    heading = soup.find("h1")
    heading = clean(heading.get_text(" ", strip=True)) if heading else title

    match = re.search(
        r"مباراة\s+(.+?)\s+ضد\s+(.+?)\s+في\s+(.+)",
        heading
    )

    if not match:
        match = re.search(
            r"(.+?)\s+vs\.?\s+(.+?)\s*[-|]\s*(.+)",
            heading,
            re.I
        )

    if not match:
        return None

    home, away, league = map(clean, match.groups())
    text = clean(soup.get_text(" ", strip=True))

    date = parse_date(text, TODAY)
    hour = parse_time(text)
    state = status_value(text)
    score = extract_score(text)

    return make_match(
        home, away, date, hour,
        league=league,
        channel=extract_channel(text),
        commentator=extract_commentator(text),
        status=state,
        score=score
    )


# ------------------------------------------------------------
# تشغيل المصادر
# ------------------------------------------------------------

def run_source(name):
    log("=" * 45)
    log("SOURCE: " + name.upper())

    homepage = SOURCES[name]
    pages = discover_pages(homepage)

    output = []
    detail_urls = []

    for index, page_url in enumerate(pages, 1):
        log(f"{name.upper()} PAGE {index}/{len(pages)}")

        page = fetch(page_url)

        if not page:
            continue

        output.extend(parse_structured(page))
        output.extend(parse_cards(page, page_url))

        if name == "asgoal":
            soup = BeautifulSoup(page, "html.parser")

            for link in soup.find_all("a", href=True):
                url = urljoin(page_url, link["href"])

                if urlparse(url).netloc != urlparse(homepage).netloc:
                    continue

                if re.search(r"/matches/[^/?#]+", url):
                    if url not in detail_urls:
                        detail_urls.append(url)

    if name == "asgoal":
        for index, url in enumerate(detail_urls[:50], 1):
            log(f"ASGOAL DETAIL {index}/{min(len(detail_urls), 50)}")

            item = parse_asgoal_detail(url)

            if item:
                output.append(item)

    unique = []

    for item in output:
        if item and not any(
            matches_same(item, old) for old in unique
        ):
            unique.append(item)

    STATS[name] = len(unique)

    log(f"{name.upper()} MATCHES: {len(unique)}")

    return unique


# ------------------------------------------------------------
# مطابقة المباريات ودمج البيانات
# ------------------------------------------------------------

def matches_same(a, b):
    if a.get("date") != b.get("date"):
        return False

    ah, aa, bh, ba = map(
        norm,
        (
            a.get("home", ""),
            a.get("away", ""),
            b.get("home", ""),
            b.get("away", "")
        )
    )

    if not all((ah, aa, bh, ba)):
        return False

    def similar(x, y):
        return SequenceMatcher(None, x, y).ratio() >= 0.86

    return (
        similar(ah, bh) and similar(aa, ba)
    ) or (
        similar(ah, ba) and similar(aa, bh)
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

        # المعلومات الناقصة تُستكمل من المصدر الآخر
        for field in (
            "league", "channel", "commentator",
            "home_img", "away_img", "streamUrl",
            "hour", "time"
        ):
            if item.get(field) and (
                not existing.get(field)
                or (
                    field == "league"
                    and existing.get(field) == "كرة القدم"
                )
            ):
                existing[field] = item[field]

        # لا نستبدل الحالة إلا إذا المصدر أكدها
        if item.get("_status_confirmed"):
            if existing.get("status") != item["status"]:
                existing["status"] = item["status"]
                STATS["status_updates"] += 1

        if item.get("_score_confirmed") and item.get("score"):
            if existing.get("score") != item["score"]:
                existing["score"] = item["score"]
                STATS["score_updates"] += 1

    return records


# ------------------------------------------------------------
# معالجة الحالات القديمة
# ------------------------------------------------------------

def fix_old_status(item):
    if item.get("status") != "live":
        return

    date = item.get("date") or item.get("match_date")
    hour = item.get("hour") or item.get("time")

    try:
        if not date or not hour:
            return

        kickoff = datetime.fromisoformat(
            date + "T" + hour
        ).replace(tzinfo=TZ)

        # إذا مضت 5 ساعات على بداية المباراة
        # ولا يوجد تحديث مباشر جديد، لا نتركها معلقة.
        if NOW - kickoff > timedelta(hours=5):
            item["status"] = "ended"

    except Exception:
        return


def clean_old_record(item):
    item = dict(item)

    item.setdefault("home", item.get("team1", ""))
    item.setdefault("away", item.get("team2", ""))

    item["home"] = clean(item.get("home"))
    item["away"] = clean(item.get("away"))

    item["team1"] = item["home"]
    item["team2"] = item["away"]

    item["league"] = clean(item.get("league")) or "كرة القدم"

    item["home_img"] = item.get("home_img") or ""
    item["away_img"] = item.get("away_img") or ""

    item["hour"] = item.get("hour") or item.get("time") or ""
    item["time"] = item["hour"]

    item["date"] = (
        item.get("date")
        or item.get("match_date")
        or TODAY.isoformat()
    )

    item["match_date"] = item["date"]
    item["score"] = valid_score(item.get("score", "")) or ""

    item["_status_confirmed"] = False
    item["_score_confirmed"] = False

    fix_old_status(item)

    return item


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
    log("YALLA KORA - SMART EXTRACTION ENGINE V19")
    log("NOW: " + NOW.isoformat())
    log("=" * 55)

    matches = []

    # استرجاع البيانات السابقة للمحافظة على معلومات القنوات
    if os.path.exists(OUTPUT):
        try:
            with open(OUTPUT, "r", encoding="utf-8") as file:
                previous = json.load(file)

            old_matches = previous.get("matches", [])

            if isinstance(old_matches, list):
                for old in old_matches:
                    if not isinstance(old, dict):
                        continue

                    record = clean_old_record(old)

                    if valid_team(record["home"]) and valid_team(record["away"]):
                        matches.append(record)

            log("PREVIOUS MATCHES RESTORED: " + str(len(matches)))

        except Exception as exc:
            log("PREVIOUS JSON WARNING: " + str(exc))

    # المصادر الخمسة نفسها
    for source in SOURCES:
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
            yesterday, today, tomorrow
        )
    ]

    for item in matches:
        item["league"] = clean(item.get("league")) or "كرة القدم"

        item["home"] = clean(item.get("home"))
        item["away"] = clean(item.get("away"))

        item["team1"] = item["home"]
        item["team2"] = item["away"]

        item["score"] = valid_score(item.get("score")) or "VS"

        item["hour"] = item.get("hour") or item.get("time") or ""
        item["time"] = item["hour"]

        item["match_date"] = item.get("date", "")

    matches.sort(
        key=lambda item: (
            item.get("date", ""),
            item.get("hour", ""),
            norm(item.get("home", ""))
        )
    )

    remove_internal_fields(matches)

    today_list = [
        x for x in matches if x.get("date") == today
    ]

    yesterday_list = [
        x for x in matches if x.get("date") == yesterday
    ]

    tomorrow_list = [
        x for x in matches if x.get("date") == tomorrow
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
        "version": "V19-SMART-EXTRACTION",
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
    log("COUNTS: " + json.dumps(
        output["counts"], ensure_ascii=False
    ))
    log("SOURCE STATS: " + json.dumps(
        STATS, ensure_ascii=False
    ))
    log("=" * 55)


if __name__ == "__main__":
    main()
