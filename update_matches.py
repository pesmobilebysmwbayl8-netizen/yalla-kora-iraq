# ============================================================
# YALLA KORA - FIVE USER-PROVIDED SOURCES ONLY
# Output schema kept compatible with the existing Android app.
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
    "talknow": "https://talknow.online/",
    "filgoal": "https://www.filgoal.com/matches/379149/overview/%D9%85%D8%A8%D8%A7%D8%B1%D8%A7%D8%A9-%D8%A7%D9%84%D8%B2%D9%85%D8%A7%D9%84%D9%83-%D9%85%D8%B5%D8%B1-%D9%84%D9%84%D8%AA%D8%A3%D9%85%D9%8A%D9%86-%D9%81%D9%8A-%D9%83%D8%A3%D8%B3-%D9%85%D8%B5%D8%B1",
    "asgoal": "https://as-goal.net/commentators-channels/",
    "original": "https://originalpro.online/live?match=27094",
    "almashhad": "https://www.almashhad.com/amp/article/218257510540304-sports/563101227576063-%D8%AC%D8%AF%D9%88%D9%84-%D9%85%D9%88%D8%A7%D8%B9%D9%8A%D8%AF-%D9%85%D8%A8%D8%A7%D8%B1%D9%8A%D8%A7%D8%AA-%D8%A7%D9%84%D9%8A%D9%88%D9%85-%D8%A7%D9%84%D8%AC%D9%85%D8%B9%D8%A9-06112026-%D9%85%D8%B9-%D8%A7%D9%84%D9%82%D9%86%D9%88%D8%A7%D8%AA-%D8%A7%D9%84%D9%86%D8%A7%D9%82%D9%84%D8%A9-%D9%88%D8%A7%D9%84%D9%85%D8%B9%D9%84%D9%82%D9%8A%D9%86/"
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 Chrome/130.0 Mobile Safari/537.36",
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)
STATS = {"talknow": 0, "filgoal": 0, "asgoal": 0, "original": 0, "almashhad": 0,
         "channels": 0, "commentators": 0, "with_home_image": 0, "with_away_image": 0,
         "errors": 0, "rejected_cards": 0}

MONTHS_AR = {"يناير": 1, "فبراير": 2, "مارس": 3, "أبريل": 4, "ابريل": 4,
             "مايو": 5, "يونيو": 6, "يوليو": 7, "أغسطس": 8, "اغسطس": 8,
             "سبتمبر": 9, "أكتوبر": 10, "اكتوبر": 10, "نوفمبر": 11, "ديسمبر": 12}
MONTHS_EN = {m.lower(): i for i, m in enumerate(
    ["", "January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
) if m}


def log(message):
    print(message, flush=True)


def fetch(url):
    try:
        response = SESSION.get(url, timeout=25)
        response.raise_for_status()
        if not response.encoding or response.encoding.lower() == "iso-8859-1":
            response.encoding = response.apparent_encoding
        return response.text
    except Exception as exc:
        STATS["errors"] += 1
        log(f"FETCH ERROR [{url}]: {exc}")
        return ""


def clean(value):
    value = html.unescape(str(value or ""))
    value = unicodedata.normalize("NFKC", value).replace("ـ", "")
    return re.sub(r"\s+", " ", value).strip(" \t\r\n|:-–—")


def norm(value):
    value = clean(value).lower()
    for a, b in {"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه"}.items():
        value = value.replace(a, b)
    return re.sub(r"[^a-z0-9\u0600-\u06ff]", "", value)


def arabic_name(value):
    value = clean(value)
    # Keep channel labels in Arabic even when a source publishes only its Latin brand.
    channel_aliases = [
        (r"(?i)be\s*in\s*(?:sports?)?\s*(\d+)?", "بي إن سبورت"),
        (r"(?i)on\s*sport\s*(\d+)?", "أون سبورت"),
        (r"(?i)starz\s*play", "ستارز بلاي"),
        (r"(?i)mbc\s*shahid", "إم بي سي شاهد"),
        (r"(?i)shahid", "شاهد"),
        (r"(?i)al[- ]?kass\s*(\d+)?", "الكأس"),
        (r"(?i)stc\s*tv", "إس تي سي تي في"),
        (r"(?i)ssc\s*(\d+)?", "إس إس سي"),
    ]
    for pattern, arabic in channel_aliases:
        found = re.search(pattern, value)
        if found:
            number = found.group(1) if found.lastindex else ""
            return clean(arabic + (" " + number if number else ""))
    value = re.sub(r"(?i)\b(?:beIN|sports?|on sport|ssc|starzplay|mbc|shahid|channel)\b.*$", "", value)
    chunks = re.findall(r"[\u0600-\u06ff][\u0600-\u06ff\s.ـ'-]*", value)
    result = clean(chunks[0]) if chunks else ""
    result = re.sub(r"\s+(?:مباشر|انتهت|لم تبدأ|يحدد لاحقاً).*$", "", result)
    if norm(result) in {"يحددلاحقا", "لاحقا", "غيرمعروف", "غيرمتوفر", "معلقتركي"}:
        return "" if norm(result) != "معلقتركي" else "معلق تركي"
    return clean(result)


def parse_date(text, default=None):
    text = clean(text)
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", text)
    if m:
        try:
            return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1))).date().isoformat()
        except ValueError:
            pass
    m = re.search(r"(\d{1,2})\s+(يناير|فبراير|مارس|أبريل|ابريل|مايو|يونيو|يوليو|أغسطس|اغسطس|سبتمبر|أكتوبر|اكتوبر|نوفمبر|ديسمبر)\s+(\d{4})", text)
    if m:
        try:
            return datetime(int(m.group(3)), MONTHS_AR[m.group(2)], int(m.group(1))).date().isoformat()
        except (ValueError, KeyError):
            pass
    m = re.search(r"\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})\b", text, re.I)
    if m:
        try:
            return datetime(int(m.group(3)), MONTHS_EN[m.group(2).lower()], int(m.group(1))).date().isoformat()
        except (ValueError, KeyError):
            pass
    return default.isoformat() if hasattr(default, "isoformat") else (default or "")


def parse_time(text):
    m = re.search(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)", clean(text))
    if not m:
        return ""
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def status_value(text):
    t = norm(text)
    if any(x in t for x in ("مباشر", "live", "جاريةالان")):
        return "live"
    if any(x in t for x in ("انتهت", "fulltime", "finished", "ended")):
        return "ended"
    if any(x in t for x in ("تاجلت", "مؤجله", "postponed", "cancelled")):
        return "postponed"
    return "upcoming"


def valid_team(name):
    name = clean(name)
    k = norm(name)
    bad = {"", "مصر", "جدولالمباريات", "مبارياتاليوم", "مبارياتالامس", "مبارياتالغد",
           "لمتبدأ", "مباشر", "انتهت", "الفريقالاول", "الفريقالثاني", "home", "away", "vs"}
    if k in bad or len(name) < 2 or len(name) > 55:
        return False
    if any(x in k for x in ("جدولالمباريات", "مبارياتالامس", "مبارياتاليوم", "مبارياتالغد", "اضغط", "الرئيسيه")):
        return False
    if re.search(r"(?:\d{1,2}:\d{2}|https?://)", name):
        return False
    return True


def new_match(home, away, date, hour="", league="", channel="", commentator="", home_img="", away_img="", status="upcoming", score=""):
    home, away = clean(home), clean(away)
    if not valid_team(home) or not valid_team(away) or norm(home) == norm(away):
        STATS["rejected_cards"] += 1
        return None
    item = {
        "league": clean(league), "home": home, "away": away,
        "team1": home, "team2": away,
        "home_img": home_img or "", "away_img": away_img or "",
        "hour": hour or "", "time": hour or "",
        "date": date or TODAY.isoformat(), "match_date": date or TODAY.isoformat(),
        "status": status or "upcoming", "score": score or "",
        "channel": clean(channel), "commentator": clean(commentator), "streamUrl": ""
    }
    return item


def image_for_team(soup, team_name):
    target = norm(team_name)
    for img in soup.find_all("img"):
        alt = norm(img.get("alt", ""))
        title = norm(img.get("title", ""))
        if target and (target == alt or target == title or (len(target) > 4 and (target in alt or alt in target))):
            src = img.get("src") or img.get("data-src") or img.get("data-lazy-src") or img.get("data-original")
            if src:
                absolute = urljoin("https://as-goal.net/", src)
                if urlparse(absolute).scheme in ("http", "https"):
                    return absolute
    return ""


def extract_label_value(text, start_label, end_label):
    pattern = re.escape(start_label) + r"\s*(.*?)\s*" + re.escape(end_label)
    m = re.search(pattern, text, re.I)
    return clean(m.group(1)) if m else ""


def parse_asgoal_detail(url):
    page = fetch(url)
    if not page:
        return None
    soup = BeautifulSoup(page, "html.parser")
    title = clean(soup.title.get_text(" ", strip=True) if soup.title else "")
    h1 = clean(soup.find("h1").get_text(" ", strip=True) if soup.find("h1") else title)
    m = re.search(r"مباراة\s+(.+?)\s+ضد\s+(.+?)\s+في\s+(.+?)(?:\s+20\d{2}.*)?$", h1)
    if not m:
        m = re.search(r"(.+?)\s+vs\.?\s+(.+?)\s*[-|]\s*(.+)$", h1, re.I)
    if not m:
        log("ASGOAL DETAIL: team title not understood: " + h1)
        return None
    home, away, league = map(clean, m.groups())
    text = clean(soup.get_text(" ", strip=True))
    date_text = extract_label_value(text, "تاريخ المباراة Match date", "توقيت المباراة Match time")
    time_text = extract_label_value(text, "توقيت المباراة Match time", "حالة المباراة Match status")
    status_text = extract_label_value(text, "حالة المباراة Match status", "القناة الناقلة Channel")
    channel_text = extract_label_value(text, "القناة الناقلة Channel", "المعلّق Commentator")
    commentator_text = extract_label_value(text, "المعلّق Commentator", "ملعب المباراة Stadium")
    date = parse_date(date_text, TODAY)
    hour = parse_time(time_text)
    channel = arabic_name(channel_text)
    commentator = arabic_name(commentator_text)
    status = status_value(status_text)
    home_img = image_for_team(soup, home)
    away_img = image_for_team(soup, away)
    score = ""
    if status in ("live", "ended"):
        sm = re.search(r"\b(\d{1,2})\s*[-–]\s*(\d{1,2})\b", text)
        if sm:
            score = f"{sm.group(1)} - {sm.group(2)}"
    return new_match(home, away, date, hour, league, channel, commentator, home_img, away_img, status, score)


def parse_asgoal():
    log("SOURCE: AS GOAL")
    page = fetch(SOURCES["asgoal"])
    if not page:
        return []
    soup = BeautifulSoup(page, "html.parser")
    urls = []
    for a in soup.find_all("a", href=True):
        href = urljoin(SOURCES["asgoal"], a["href"])
        if re.search(r"as-goal\.net/matches/[^/?#]+/?$", href):
            if href not in urls:
                urls.append(href)
    log("ASGOAL MATCH LINKS: " + str(len(urls)))
    records = []
    for i, url in enumerate(urls, 1):
        log(f"ASGOAL DETAIL [{i}/{len(urls)}]: {url}")
        item = parse_asgoal_detail(url)
        if item:
            records.append(item)
    STATS["asgoal"] = len(records)
    return records


def parse_filgoal():
    log("SOURCE: FILGOAL")
    page = fetch(SOURCES["filgoal"])
    if not page:
        return []
    soup = BeautifulSoup(page, "html.parser")
    title = clean(soup.title.get_text(" ", strip=True) if soup.title else "")
    m = re.search(r"مباراة فريقي\s+(.+?)\s+و\s+(.+?)\s+في بطولة\s+(.+?)(?:\s+-|$)", title)
    if not m:
        log("FILGOAL: title did not contain a clean two-team match")
        return []
    home, away, league = map(clean, m.groups())
    text = clean(soup.get_text(" ", strip=True))
    date = parse_date(text, TODAY)
    hour = parse_time(text)
    # Read channel only from the match information line, not the whole page header/footer.
    info = re.search(r"استاد.{0,100}?\s+(\d{1,2}\s+[\u0600-\u06ff]+\s+20\d{2})\s+(\d{1,2}:\d{2})\s+(.{0,100})", text)
    channel, commentator = "", ""
    if info:
        date = parse_date(info.group(1), date)
        hour = parse_time(info.group(2)) or hour
        tail = clean(info.group(3))
        cm = re.search(r"(أون سبورت(?:\s+\d+)?|اون سبورت(?:\s+\d+)?|On Sport(?:\s+\d+)?)", tail, re.I)
        channel = arabic_name(cm.group(1)) if cm else ""
    # The page lists multiple commentator names without a reliable single primary label;
    # don't guess which one should be displayed.
    home_img = image_for_team(soup, home)
    away_img = image_for_team(soup, away)
    status = status_value(text[:500])
    item = new_match(home, away, date, hour, league, channel, commentator, home_img, away_img, status)
    STATS["filgoal"] = 1 if item else 0
    return [item] if item else []


def parse_almashhad():
    log("SOURCE: AL MASHHAD")
    page = fetch(SOURCES["almashhad"])
    if not page:
        return []
    soup = BeautifulSoup(page, "html.parser")
    date_digits = re.search(r"(\d{2})(\d{2})(\d{4})", SOURCES["almashhad"])
    article_date = TODAY.isoformat()
    if date_digits:
        try:
            article_date = datetime(int(date_digits.group(3)), int(date_digits.group(2)), int(date_digits.group(1))).date().isoformat()
        except ValueError:
            pass
    records = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        headers = [norm(c.get_text(" ", strip=True)) for c in rows[0].find_all(["th", "td"])]
        for row in rows[1:]:
            cells = [clean(c.get_text(" ", strip=True)) for c in row.find_all(["td", "th"])]
            if len(cells) < 7:
                continue
            # This article's published table order: league, match, Egypt, Saudi, UAE, channel, commentator.
            league, match_text = cells[0], cells[1]
            saudi_time, channel_text, commentator_text = cells[3], cells[5], cells[6]
            teams = re.split(r"\s+(?:-|–|—|vs\.?|ضد)\s+", match_text, maxsplit=1, flags=re.I)
            if len(teams) != 2:
                continue
            hour = parse_time(saudi_time)
            if not hour:
                continue
            channel = arabic_name(channel_text)
            commentator = arabic_name(commentator_text)
            if norm(commentator_text) in ("-", "", "يحددلاحقا"):
                commentator = ""
            item = new_match(teams[0], teams[1], article_date, hour, league, channel, commentator)
            if item:
                records.append(item)
    STATS["almashhad"] = len(records)
    log("AL MASHHAD MATCHES: " + str(len(records)))
    return records


def parse_structured_events(page, source_name):
    """Conservative fallback: accept only explicit SportsEvent JSON-LD records."""
    soup = BeautifulSoup(page, "html.parser")
    results = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text())
        except Exception:
            continue
        objects = data if isinstance(data, list) else [data]
        for obj in objects:
            if isinstance(obj, dict) and obj.get("@type") == "SportsEvent":
                home = obj.get("homeTeam", {})
                away = obj.get("awayTeam", {})
                if isinstance(home, list): home = home[0] if home else {}
                if isinstance(away, list): away = away[0] if away else {}
                hn = home.get("name", "") if isinstance(home, dict) else ""
                an = away.get("name", "") if isinstance(away, dict) else ""
                start = clean(obj.get("startDate", ""))
                dt = ""
                hour = ""
                if start:
                    try:
                        parsed = datetime.fromisoformat(start.replace("Z", "+00:00"))
                        if parsed.tzinfo:
                            parsed = parsed.astimezone(TZ)
                        dt, hour = parsed.date().isoformat(), parsed.strftime("%H:%M")
                    except Exception:
                        pass
                home_image = home.get("image") or home.get("logo") or "" if isinstance(home, dict) else ""
                away_image = away.get("image") or away.get("logo") or "" if isinstance(away, dict) else ""
                if isinstance(home_image, dict): home_image = home_image.get("url", "")
                if isinstance(away_image, dict): away_image = away_image.get("url", "")
                item = new_match(hn, an, dt or TODAY.isoformat(), hour,
                                 clean(obj.get("superEvent", {}).get("name", "")) if isinstance(obj.get("superEvent"), dict) else "",
                                 home_img=home_image, away_img=away_image)
                if item:
                    results.append(item)
    return results


def parse_talknow():
    log("SOURCE: TALK NOW")
    page = fetch(SOURCES["talknow"])
    if not page:
        return []
    # Do not parse arbitrary div/a text: it caused navigation labels to become team names.
    records = parse_structured_events(page, "talknow")
    STATS["talknow"] = len(records)
    log("TALKNOW VERIFIED STRUCTURED MATCHES: " + str(len(records)))
    return records


def parse_original():
    log("SOURCE: ORIGINAL TV")
    page = fetch(SOURCES["original"])
    if not page:
        return []
    # The supplied URL is a single match page. Accept only explicit structured match data.
    records = parse_structured_events(page, "original")
    STATS["original"] = len(records)
    log("ORIGINAL VERIFIED STRUCTURED MATCHES: " + str(len(records)))
    return records


def matches_same(a, b):
    if a.get("date") != b.get("date"):
        return False
    ah, aa, bh, ba = map(norm, (a.get("home"), a.get("away"), b.get("home"), b.get("away")))
    if not all((ah, aa, bh, ba)):
        return False
    direct = SequenceMatcher(None, ah, bh).ratio() >= 0.90 and SequenceMatcher(None, aa, ba).ratio() >= 0.90
    reverse = SequenceMatcher(None, ah, ba).ratio() >= 0.90 and SequenceMatcher(None, aa, bh).ratio() >= 0.90
    return direct or reverse


def merge(records, incoming):
    for item in incoming:
        if not item:
            continue
        existing = next((x for x in records if matches_same(x, item)), None)
        if existing is None:
            records.append(item)
            continue
        # Fill missing fields only; never overwrite an existing non-empty fact with a guess.
        for field in ("league", "channel", "commentator", "home_img", "away_img", "streamUrl", "score"):
            if item.get(field) and not existing.get(field):
                existing[field] = item[field]
        if item.get("status") in ("live", "ended", "postponed"):
            existing["status"] = item["status"]
        if item.get("hour") and not existing.get("hour"):
            existing["hour"] = existing["time"] = item["hour"]
    return records


def main():
    log("=" * 58)
    log("YALLA KORA - STRICT FIVE SOURCES / BAGHDAD TIMEZONE")
    log("NOW: " + NOW.isoformat())
    log("=" * 58)

    # AS Goal is the daily match list and exposes a dedicated detail page per match.
    asgoal = parse_asgoal()
    talknow = parse_talknow()
    filgoal = parse_filgoal()
    original = parse_original()
    almashhad = parse_almashhad()

    matches = []
    for group in (asgoal, talknow, filgoal, original, almashhad):
        merge(matches, group)

    # Keep only the three requested date buckets; do not relabel unknown dates as today.
    yesterday = (TODAY - timedelta(days=1)).isoformat()
    today = TODAY.isoformat()
    tomorrow = (TODAY + timedelta(days=1)).isoformat()
    matches = [x for x in matches if x.get("date") in {yesterday, today, tomorrow}]
    matches.sort(key=lambda x: (x.get("date", ""), x.get("hour", ""), norm(x.get("home", ""))))

    today_list = [x for x in matches if x["date"] == today]
    yesterday_list = [x for x in matches if x["date"] == yesterday]
    tomorrow_list = [x for x in matches if x["date"] == tomorrow]

    STATS["channels"] = sum(bool(x.get("channel")) for x in matches)
    STATS["commentators"] = sum(bool(x.get("commentator")) for x in matches)
    STATS["with_home_image"] = sum(bool(x.get("home_img")) for x in matches)
    STATS["with_away_image"] = sum(bool(x.get("away_img")) for x in matches)

    output = {
        "version": "V12-STRICT-FIVE-SOURCES",
        "updated_at": datetime.now(TZ).isoformat(),
        "timezone": "Asia/Baghdad",
        "matches": matches,
        "today": today_list,
        "yesterday": yesterday_list,
        "tomorrow": tomorrow_list,
        "counts": {
            "total": len(matches), "today": len(today_list),
            "yesterday": len(yesterday_list), "tomorrow": len(tomorrow_list),
            "with_channel": STATS["channels"], "with_commentator": STATS["commentators"],
            "with_home_image": STATS["with_home_image"], "with_away_image": STATS["with_away_image"]
        },
        "sources": STATS
    }

    temp = OUTPUT + ".tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    os.replace(temp, OUTPUT)

    log("=" * 58)
    log("FINISHED - counts below are actual non-empty fields")
    log(json.dumps(output["counts"], ensure_ascii=False))
    log("SOURCE STATS: " + json.dumps(STATS, ensure_ascii=False))
    log("=" * 58)


if __name__ == "__main__":
    main()
