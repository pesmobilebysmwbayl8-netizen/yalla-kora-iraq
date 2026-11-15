# ============================================================
# YALLA KORA - FIVE SOURCES + MATCH STATUS REFRESH
# Keeps the existing matches.json schema and the same five sources.
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
STATS = {k: 0 for k in ("talknow", "filgoal", "asgoal", "original", "almashhad",
                         "channels", "commentators", "with_home_image", "with_away_image",
                         "errors", "rejected_cards", "status_updates", "score_updates")}
NOW = datetime.now(TZ)
TODAY = NOW.date()

MONTHS_AR = {"يناير": 1, "فبراير": 2, "مارس": 3, "أبريل": 4, "ابريل": 4,
             "مايو": 5, "يونيو": 6, "يوليو": 7, "أغسطس": 8, "اغسطس": 8,
             "سبتمبر": 9, "أكتوبر": 10, "اكتوبر": 10, "نوفمبر": 11, "ديسمبر": 12}
MONTHS_EN = {m.lower(): i for i, m in enumerate(
    ["", "January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"]) if m}


def log(msg):
    print(msg, flush=True)


def clean(value):
    value = html.unescape(str(value or ""))
    value = unicodedata.normalize("NFKC", value).replace("ـ", "")
    return re.sub(r"\s+", " ", value).strip(" \t\r\n|:-–—")


def norm(value):
    value = clean(value).lower()
    for a, b in {"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه"}.items():
        value = value.replace(a, b)
    return re.sub(r"[^a-z0-9\u0600-\u06ff]", "", value)


def fetch(url):
    try:
        r = SESSION.get(url, timeout=25)
        r.raise_for_status()
        if not r.encoding or r.encoding.lower() == "iso-8859-1":
            r.encoding = r.apparent_encoding
        return r.text
    except Exception as exc:
        STATS["errors"] += 1
        log(f"FETCH ERROR [{url}]: {exc}")
        return ""


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
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else ""


def status_value(text):
    """Return a status only when the source contains explicit status evidence."""
    t = norm(text)
    if any(x in t for x in ("مباشر", "live", "جاريهالان", "الشوطالاول", "الشوطالثاني", "استراحه")):
        return "live"
    if any(x in t for x in ("انتهت", "نهايهالمباراه", "fulltime", "finished", "ended")):
        return "ended"
    if any(x in t for x in ("تاجلت", "مؤجله", "postponed", "cancelled", "ملغاه")):
        return "postponed"
    if any(x in t for x in ("لمتبدا", "لمتبدأ", "لم تبدأ", "لم تبدأ بعد", "upcoming", "scheduled", "لم تبدأ المباراة")):
        return "upcoming"
    return ""


def extract_score(text):
    """Extract a score only when the source explicitly labels it as a result.

    Do not infer scores from numbers near live/finished text: those areas can
    contain dates, kickoff times, or other page metadata.
    """
    raw = clean(text)
    patterns = (
        r"(?:نتيجة\s*المباراة|النتيجة|score|result)\s*[:：]?\s*(\d{1,2})\s*[-–:]\s*(\d{1,2})(?!\d)",
    )
    for pattern in patterns:
        m = re.search(pattern, raw, re.I)
        if not m:
            continue
        a, b = int(m.group(1)), int(m.group(2))
        # Reject impossible football scores and date-like high numbers.
        if 0 <= a <= 15 and 0 <= b <= 15:
            return f"{a} - {b}"
    return ""


def arabic_name(value):
    value = clean(value)

    # Normalize UAE sports channels separately; never map Abu Dhabi to Dubai.
    # Accept common Latin spellings and preserve the channel number.
    uae_aliases = [
        (r"(?i)(?:abu\s*dhabi|ad)\s*(?:sports?|sport)\s*premium\s*(\d+)?", "أبو ظبي الرياضية بريميوم"),
        (r"(?i)(?:abu\s*dhabi|ad)\s*(?:sports?|sport)\s*(\d+)?", "أبو ظبي الرياضية"),
        (r"(?i)dubai\s*(?:sports?|sport)\s*(\d+)?", "دبي الرياضية"),
    ]
    for pattern, arabic in uae_aliases:
        found = re.search(pattern, value)
        if found:
            number = found.group(1) if found.lastindex else ""
            return clean(arabic + (" " + number if number else ""))

    # Repair Arabic labels where the source places the number before the name.
    m = re.fullmatch(r"(\d+)\s*(دبي\s*الرياضية)", value)
    if m:
        return clean(m.group(2) + " " + m.group(1))
    m = re.fullmatch(r"(\d+)\s*(أبو\s*ظبي\s*الرياضية)", value)
    if m:
        return clean(m.group(2) + " " + m.group(1))

    aliases = [
        (r"(?i)be\s*in\s*(?:sports?)?\s*(\d+)?", "بي إن سبورت"),
        (r"(?i)on\s*sport\s*(\d+)?", "أون سبورت"),
        (r"(?i)starz\s*play", "ستارز بلاي"),
        (r"(?i)mbc\s*shahid", "إم بي سي شاهد"),
        (r"(?i)shahid", "شاهد"),
        (r"(?i)al[- ]?kass\s*(\d+)?", "الكأس"),
        (r"(?i)stc\s*tv", "إس تي سي تي في"),
        (r"(?i)ssc\s*(\d+)?", "إس إس سي"),
    ]
    for pattern, arabic in aliases:
        found = re.search(pattern, value)
        if found:
            number = found.group(1) if found.lastindex else ""
            return clean(arabic + (" " + number if number else ""))
    chunks = re.findall(r"[\u0600-\u06ff][\u0600-\u06ff\s.ـ'-]*", value)
    result = clean(chunks[0]) if chunks else ""
    if norm(result) in {"يحددلاحقا", "لاحقا", "غيرمعروف", "غيرمتوفر"}:
        return ""
    return result


def valid_team(name):
    name, key = clean(name), norm(name)
    bad = {"", "مصر", "جدولالمباريات", "مبارياتاليوم", "مبارياتالامس",
           "مبارياتالغد", "لمتبدأ", "مباشر", "انتهت", "home", "away", "vs"}
    if key in bad or len(name) < 2 or len(name) > 55:
        return False
    if any(x in key for x in ("جدولالمباريات", "مبارياتالامس", "مبارياتاليوم", "مبارياتالغد", "اضغط")):
        return False
    return not re.search(r"(?:\d{1,2}:\d{2}|https?://)", name)


def new_match(home, away, date, hour="", league="", channel="", commentator="",
              home_img="", away_img="", status="", score=""):
    home, away = clean(home), clean(away)
    if not valid_team(home) or not valid_team(away) or norm(home) == norm(away):
        STATS["rejected_cards"] += 1
        return None
    return {
        "league": clean(league), "home": home, "away": away,
        "team1": home, "team2": away,
        "home_img": home_img or "", "away_img": away_img or "",
        "hour": hour or "", "time": hour or "",
        "date": date or TODAY.isoformat(), "match_date": date or TODAY.isoformat(),
        "status": status or "upcoming", "score": score or "",
        "channel": clean(channel), "commentator": clean(commentator), "streamUrl": "",
        "_status_confirmed": bool(status), "_score_confirmed": bool(score)
    }


def image_for_team(soup, team_name):
    target = norm(team_name)
    for img in soup.find_all("img"):
        alt, title = norm(img.get("alt", "")), norm(img.get("title", ""))
        if target and (target == alt or target == title or (len(target) > 4 and (target in alt or alt in target))):
            src = img.get("src") or img.get("data-src") or img.get("data-lazy-src") or img.get("data-original")
            if src:
                absolute = urljoin(SOURCES["asgoal"], src)
                if urlparse(absolute).scheme in ("http", "https"):
                    return absolute
    return ""


def extract_label_value(text, start_label, end_label):
    m = re.search(re.escape(start_label) + r"\s*(.*?)\s*" + re.escape(end_label), text, re.I)
    return clean(m.group(1)) if m else ""


def parse_asgoal_detail(url):
    page = fetch(url)
    if not page:
        return None
    soup = BeautifulSoup(page, "html.parser")
    title = clean(soup.title.get_text(" ", strip=True) if soup.title else "")
    h1tag = soup.find("h1")
    h1 = clean(h1tag.get_text(" ", strip=True) if h1tag else title)
    m = re.search(r"مباراة\s+(.+?)\s+ضد\s+(.+?)\s+في\s+(.+?)(?:\s+20\d{2}.*)?$", h1)
    if not m:
        m = re.search(r"(.+?)\s+vs\.?\s+(.+?)\s*[-|]\s*(.+)$", h1, re.I)
    if not m:
        log("ASGOAL DETAIL: title not understood: " + h1)
        return None
    home, away, league = map(clean, m.groups())
    text = clean(soup.get_text(" ", strip=True))
    date_text = extract_label_value(text, "تاريخ المباراة Match date", "توقيت المباراة Match time")
    time_text = extract_label_value(text, "توقيت المباراة Match time", "حالة المباراة Match status")
    status_text = extract_label_value(text, "حالة المباراة Match status", "القناة الناقلة Channel")
    channel_text = extract_label_value(text, "القناة الناقلة Channel", "المعلّق Commentator")
    commentator_text = extract_label_value(text, "المعلّق Commentator", "ملعب المباراة Stadium")
    state = status_value(status_text) or status_value(text[:500])
    score = extract_score(text) if state in ("live", "ended") else ""
    return new_match(home, away, parse_date(date_text, TODAY), parse_time(time_text), league,
                     arabic_name(channel_text), arabic_name(commentator_text),
                     image_for_team(soup, home), image_for_team(soup, away), state, score)


def parse_asgoal():
    log("SOURCE: AS GOAL")
    page = fetch(SOURCES["asgoal"])
    if not page:
        return []
    soup = BeautifulSoup(page, "html.parser")
    urls = []
    for a in soup.find_all("a", href=True):
        u = urljoin(SOURCES["asgoal"], a["href"])
        if re.search(r"as-goal\.net/matches/[^/?#]+/?$", u) and u not in urls:
            urls.append(u)
    log("ASGOAL MATCH LINKS: " + str(len(urls)))
    out = []
    for i, u in enumerate(urls, 1):
        log(f"ASGOAL DETAIL [{i}/{len(urls)}]")
        item = parse_asgoal_detail(u)
        if item:
            out.append(item)
    STATS["asgoal"] = len(out)
    return out


def parse_filgoal():
    log("SOURCE: FILGOAL")
    page = fetch(SOURCES["filgoal"])
    if not page:
        return []
    soup = BeautifulSoup(page, "html.parser")
    title = clean(soup.title.get_text(" ", strip=True) if soup.title else "")
    m = re.search(r"مباراة فريقي\s+(.+?)\s+و\s+(.+?)\s+في بطولة\s+(.+?)(?:\s+-|$)", title)
    if not m:
        log("FILGOAL: title did not contain a clean match")
        return []
    home, away, league = map(clean, m.groups())
    text = clean(soup.get_text(" ", strip=True))
    date, hour = parse_date(text, TODAY), parse_time(text)
    info = re.search(r"استاد.{0,100}?\s+(\d{1,2}\s+[\u0600-\u06ff]+\s+20\d{2})\s+(\d{1,2}:\d{2})\s+(.{0,100})", text)
    channel = ""
    if info:
        date, hour = parse_date(info.group(1), date), parse_time(info.group(2)) or hour
        cm = re.search(r"(أون سبورت(?:\s+\d+)?|اون سبورت(?:\s+\d+)?|On Sport(?:\s+\d+)?)", info.group(3), re.I)
        channel = arabic_name(cm.group(1)) if cm else ""
    state = status_value(text)
    score = extract_score(text) if state in ("live", "ended") else ""
    item = new_match(home, away, date, hour, league, channel, "", image_for_team(soup, home),
                     image_for_team(soup, away), state, score)
    STATS["filgoal"] = int(bool(item))
    return [item] if item else []


def parse_almashhad():
    log("SOURCE: AL MASHHAD")
    page = fetch(SOURCES["almashhad"])
    if not page:
        return []
    soup = BeautifulSoup(page, "html.parser")
    d = re.search(r"(\d{2})(\d{2})(\d{4})", SOURCES["almashhad"])
    article_date = TODAY.isoformat()
    if d:
        try:
            article_date = datetime(int(d.group(3)), int(d.group(2)), int(d.group(1))).date().isoformat()
        except ValueError:
            pass
    out = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        for row in rows[1:]:
            cells = [clean(c.get_text(" ", strip=True)) for c in row.find_all(["td", "th"])]
            if len(cells) < 7:
                continue
            league, match_text = cells[0], cells[1]
            saudi_time, channel_text, commentator_text = cells[3], cells[5], cells[6]
            teams = re.split(r"\s+(?:-|–|—|vs\.?|ضد)\s+", match_text, maxsplit=1, flags=re.I)
            if len(teams) != 2:
                continue
            item = new_match(teams[0], teams[1], article_date, parse_time(saudi_time), league,
                             arabic_name(channel_text), arabic_name(commentator_text))
            if item:
                out.append(item)
    STATS["almashhad"] = len(out)
    return out


def parse_structured_events(page):
    soup = BeautifulSoup(page, "html.parser")
    out = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text())
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
            if obj.get("@type") != "SportsEvent":
                continue
            home, away = obj.get("homeTeam", {}), obj.get("awayTeam", {})
            if isinstance(home, list): home = home[0] if home else {}
            if isinstance(away, list): away = away[0] if away else {}
            start = clean(obj.get("startDate", ""))
            dt, hour = "", ""
            if start:
                try:
                    parsed = datetime.fromisoformat(start.replace("Z", "+00:00"))
                    if parsed.tzinfo:
                        parsed = parsed.astimezone(TZ)
                    dt, hour = parsed.date().isoformat(), parsed.strftime("%H:%M")
                except Exception:
                    pass
            event_state = clean(obj.get("eventStatus", ""))
            state = status_value(event_state)
            if not state:
                state = status_value(clean(obj.get("description", "")))
            score = ""
            result = obj.get("competitor", [])
            if isinstance(result, list) and len(result) >= 2:
                vals = []
                for c in result[:2]:
                    val = c.get("score") if isinstance(c, dict) else None
                    vals.append(str(val) if val is not None else "")
                if all(v.isdigit() for v in vals):
                    score = f"{vals[0]} - {vals[1]}"
            hn = home.get("name", "") if isinstance(home, dict) else ""
            an = away.get("name", "") if isinstance(away, dict) else ""
            hi = (home.get("image") or home.get("logo") or "") if isinstance(home, dict) else ""
            ai = (away.get("image") or away.get("logo") or "") if isinstance(away, dict) else ""
            if isinstance(hi, dict): hi = hi.get("url", "")
            if isinstance(ai, dict): ai = ai.get("url", "")
            item = new_match(hn, an, dt or TODAY.isoformat(), hour, "",
                             home_img=hi, away_img=ai, status=state, score=score)
            if item:
                out.append(item)
    return out


def parse_talknow():
    log("SOURCE: TALK NOW")
    page = fetch(SOURCES["talknow"])
    out = parse_structured_events(page) if page else []
    STATS["talknow"] = len(out)
    return out


def parse_original():
    log("SOURCE: ORIGINAL TV")
    page = fetch(SOURCES["original"])
    out = parse_structured_events(page) if page else []
    STATS["original"] = len(out)
    return out


def matches_same(a, b):
    if a.get("date") != b.get("date"):
        return False
    ah, aa, bh, ba = map(norm, (a.get("home"), a.get("away"), b.get("home"), b.get("away")))
    if not all((ah, aa, bh, ba)):
        return False
    sim = lambda x, y: SequenceMatcher(None, x, y).ratio() >= 0.90
    return (sim(ah, bh) and sim(aa, ba)) or (sim(ah, ba) and sim(aa, bh))


def merge(records, incoming):
    for item in incoming:
        if not item:
            continue
        existing = next((x for x in records if matches_same(x, item)), None)
        if existing is None:
            records.append(item)
            continue
        # Metadata is filled only when missing.
        for field in ("league", "channel", "commentator", "home_img", "away_img", "streamUrl"):
            if item.get(field) and not existing.get(field):
                existing[field] = item[field]
        # A status is replaced only when the source explicitly identified it.
        if item.get("_status_confirmed"):
            old = existing.get("status", "upcoming")
            new = item["status"]
            if old != new:
                existing["status"] = new
                STATS["status_updates"] += 1
        # Never erase a known score. Update it only from an explicit score extraction.
        if item.get("_score_confirmed") and item.get("score"):
            if existing.get("score") != item["score"]:
                existing["score"] = item["score"]
                STATS["score_updates"] += 1
        if item.get("hour") and not existing.get("hour"):
            existing["hour"] = existing["time"] = item["hour"]
    return records


def clean_internal_fields(records):
    for item in records:
        item.pop("_status_confirmed", None)
        item.pop("_score_confirmed", None)
    return records


def main():
    log("=" * 58)
    log("YALLA KORA - FIVE SOURCES / STATUS REFRESH")
    log("NOW: " + NOW.isoformat())
    log("=" * 58)

    # Keep the same five sources; no new service or API is added.
    # Seed from the previous JSON so a temporary source outage does not erase
    # an already known match, score, or confirmed status.
    matches = []
    if os.path.exists(OUTPUT):
        try:
            with open(OUTPUT, "r", encoding="utf-8") as f:
                previous = json.load(f)
            old_matches = previous.get("matches", []) if isinstance(previous, dict) else []
            if isinstance(old_matches, list):
                for old in old_matches:
                    if isinstance(old, dict) and old.get("home") and old.get("away"):
                        # Internal flags are deliberately false for old records:
                        # only a fresh explicit source result can change status/score.
                        old = dict(old)
                        old["_status_confirmed"] = False
                        old["_score_confirmed"] = False
                        matches.append(old)
            log("PREVIOUS MATCHES RESTORED: " + str(len(matches)))
        except Exception as exc:
            log("PREVIOUS JSON READ WARNING: " + str(exc))

    groups = [parse_asgoal(), parse_talknow(), parse_filgoal(), parse_original(), parse_almashhad()]
    for group in groups:
        merge(matches, group)

    # Retain the same yesterday/today/tomorrow output buckets.
    yesterday = (TODAY - timedelta(days=1)).isoformat()
    today = TODAY.isoformat()
    tomorrow = (TODAY + timedelta(days=1)).isoformat()
    matches = [x for x in matches if x.get("date") in {yesterday, today, tomorrow}]
    matches.sort(key=lambda x: (x.get("date", ""), x.get("hour", ""), norm(x.get("home", ""))))

    clean_internal_fields(matches)
    today_list = [x for x in matches if x["date"] == today]
    yesterday_list = [x for x in matches if x["date"] == yesterday]
    tomorrow_list = [x for x in matches if x["date"] == tomorrow]

    STATS["channels"] = sum(bool(x.get("channel")) for x in matches)
    STATS["commentators"] = sum(bool(x.get("commentator")) for x in matches)
    STATS["with_home_image"] = sum(bool(x.get("home_img")) for x in matches)
    STATS["with_away_image"] = sum(bool(x.get("away_img")) for x in matches)

    output = {
        "version": "V15-FIVE-SOURCES-SCORE-DATE-FIX",
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

    tmp = OUTPUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    os.replace(tmp, OUTPUT)

    log("FINISHED: " + json.dumps(output["counts"], ensure_ascii=False))
    log("STATUS UPDATES: " + str(STATS["status_updates"]))
    log("SCORE UPDATES: " + str(STATS["score_updates"]))
    log("SOURCE STATS: " + json.dumps(STATS, ensure_ascii=False))


if __name__ == "__main__":
    main()
