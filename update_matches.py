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

# =====================================================
# YALLA KORA - MATCH DATA UPDATER
# Keeps the existing matches.json schema and day arrays.
# =====================================================

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
REQUEST_TIMEOUT = 25

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 Chrome/120.0 Mobile Safari/537.36",
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
})


def clean(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def clean_team(value):
    value = clean(value)
    value = re.sub(r"^(?:مباراة|بث مباشر|يلا شوت)\s*[:：-]?\s*", "", value, flags=re.I)
    value = re.sub(r"\s*(?:بث مباشر|يلا شوت|مشاهدة المباراة).*$", "", value, flags=re.I)
    value = re.split(r"\s+(?:بتاريخ\s+\d{4}-\d{2}-\d{2}|في دوري\s+|ضمن منافسات\s+|بطولة\s+)", value, maxsplit=1)[0]
    value = re.sub(r"\s*[-|–]\s*(?:بث مباشر|يلا شوت).*$", "", value, flags=re.I)
    return value.strip(" -|–،:")


def get_page(url):
    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        response.encoding = response.apparent_encoding or "utf-8"
        return response.text
    except requests.RequestException as exc:
        print("Page error:", url, exc)
        return None


def get_soup(url):
    html = get_page(url)
    return BeautifulSoup(html, "html.parser") if html else None


def unique(items):
    seen, result = set(), []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def valid_url(url):
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return host == "shot.wiki" and "/matches/" in parsed.path and parsed.path.rstrip("/") != "/matches"


def image_url(value):
    if isinstance(value, list):
        for item in value:
            result = image_url(item)
            if result:
                return result
        return ""
    if isinstance(value, dict):
        value = value.get("url") or value.get("contentUrl") or value.get("@id")
    value = clean(value)
    if value.startswith("//"):
        value = "https:" + value
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return ""


def read_jsonld(soup):
    found = []
    for tag in soup.find_all("script", type="application/ld+json"):
        raw = tag.string or tag.get_text()
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            continue

        def walk(obj):
            if isinstance(obj, list):
                for entry in obj:
                    walk(entry)
            elif isinstance(obj, dict):
                found.append(obj)
                graph = obj.get("@graph")
                if graph:
                    walk(graph)
        walk(data)
    return found


def find_event(items):
    for item in items:
        types = item.get("@type", [])
        if isinstance(types, str):
            types = [types]
        if any(str(kind).lower() in ("sportsevent", "event") for kind in types):
            return item
    return {}


def team_info(value):
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, str):
        return clean_team(value), ""
    if not isinstance(value, dict):
        return "", ""
    name = clean_team(value.get("name") or value.get("alternateName"))
    logo = image_url(value.get("logo") or value.get("image"))
    return name, logo


def collect_links(soup):
    links = []
    for anchor in soup.find_all("a", href=True):
        url = urljoin(BASE_URL, anchor["href"].strip()).split("#", 1)[0]
        if valid_url(url):
            links.append(url)
    return unique(links)[:MAX_MATCHES_PER_DAY]


def find_card(soup, match_url):
    for anchor in soup.find_all("a", href=True):
        url = urljoin(BASE_URL, anchor["href"].strip()).split("#", 1)[0]
        if url != match_url:
            continue
        current = anchor
        best = anchor
        for _ in range(7):
            if not current or not getattr(current, "name", None):
                break
            text = clean(current.get_text(" ", strip=True))
            if 10 <= len(text) <= 1800:
                best = current
            current = current.parent
        return best
    return None


def card_text(card):
    return clean(card.get_text(" ", strip=True)) if card else ""


def extract_teams(soup, url, event, card):
    home, home_logo = team_info(event.get("homeTeam"))
    away, away_logo = team_info(event.get("awayTeam"))
    if home and away and home.lower() != away.lower():
        return home, away, home_logo, away_logo

    titles = []
    h1 = soup.find("h1")
    if h1:
        titles.append(clean(h1.get_text(" ", strip=True)))
    og = soup.find("meta", property="og:title")
    if og:
        titles.append(clean(og.get("content")))
    if card:
        titles.append(card_text(card))

    patterns = (
        r"(.+?)\s+(?:vs\.?|v\.?|VS|Vs)\s+(.+)",
        r"مباراة\s+(.+?)\s+(?:ضد|و)\s+(.+)",
        r"(.+?)\s+ضد\s+(.+)",
    )
    for title in titles:
        for pattern in patterns:
            match = re.search(pattern, title, re.I)
            if not match:
                continue
            first, second = clean_team(match.group(1)), clean_team(match.group(2))
            if first and second and first.lower() != second.lower() and len(first) <= 70 and len(second) <= 70:
                return home or first, away or second, home_logo, away_logo

    slug = unquote(urlparse(url).path.rstrip("/").split("/")[-1])
    slug = re.sub(r"^(?:مباراة-)?", "", slug)
    slug = slug.replace("-vs-", "|vs|").replace("-vs", "|vs").replace("vs-", "vs|")
    slug = slug.replace("-", " ")
    match = re.search(r"(.+?)\s*\|vs\|\s*(.+)", slug, re.I)
    if match:
        first, second = clean_team(match.group(1)), clean_team(match.group(2))
        if first and second:
            return home or first, away or second, home_logo, away_logo
    return home, away, home_logo, away_logo


def find_logo_by_team(card, team_name):
    if not card or not team_name:
        return ""
    target = re.sub(r"[^\w\u0600-\u06FF]", "", team_name).lower()
    for img in card.find_all("img"):
        labels = " ".join(str(img.get(key, "")) for key in ("alt", "title", "data-team", "class"))
        normalized = re.sub(r"[^\w\u0600-\u06FF]", "", labels).lower()
        if target and (target in normalized or normalized in target):
            src = img.get("data-src") or img.get("data-lazy-src") or img.get("data-original") or img.get("src")
            return image_url(src)
    return ""


def extract_logos(card, home, away, home_logo, away_logo):
    if not home_logo:
        home_logo = find_logo_by_team(card, home)
    if not away_logo:
        away_logo = find_logo_by_team(card, away)
    return home_logo, away_logo


def parse_iso_datetime(value):
    value = clean(value)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=TZ)
        return parsed.astimezone(TZ)
    except (ValueError, TypeError):
        return None


def time_from_text(text):
    text = clean(text)
    match = re.search(r"(?<!\d)(\d{1,2}):(\d{2})(?:\s*(AM|PM))?(?!\d)", text, re.I)
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    period = (match.group(3) or "").upper()
    if period == "PM" and hour != 12:
        hour += 12
    elif period == "AM" and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour, minute


def extract_datetime(soup, event, fallback_day, card):
    # Prefer the match's own structured startDate.
    dt = parse_iso_datetime(event.get("startDate"))
    if dt:
        return dt

    # Only inspect the match card, not every time element on the whole page.
    scopes = [card] if card else []
    for scope in scopes:
        for tag in scope.find_all(["time", "meta"], attrs={"datetime": True}) + scope.find_all(attrs={"itemprop": "startDate"}):
            value = tag.get("datetime") or tag.get("content") or tag.get("data-start")
            dt = parse_iso_datetime(value)
            if dt:
                return dt
        for tag in scope.select("[data-start], [data-datetime], [itemprop='startDate']"):
            value = tag.get("data-start") or tag.get("data-datetime") or tag.get("content") or tag.get("datetime")
            dt = parse_iso_datetime(value)
            if dt:
                return dt

    # Last fallback: time displayed in the listing card + known page day.
    time_value = time_from_text(card_text(card)) if card else None
    if not time_value:
        return None
    offsets = {"yesterday": -1, "today": 0, "tomorrow": 1}
    match_date = datetime.now(TZ).date() + timedelta(days=offsets[fallback_day])
    hour, minute = time_value
    return datetime(match_date.year, match_date.month, match_date.day, hour, minute, tzinfo=TZ)


def extract_score(soup, event, card):
    for key in ("score", "result"):
        value = event.get(key)
        if isinstance(value, str):
            match = re.fullmatch(r"\s*(\d{1,2})\s*[-–]\s*(\d{1,2})\s*", value)
            if match:
                return f"{match.group(1)}-{match.group(2)}"

    selectors = (".match-score", ".score", ".result", ".team-score", "[data-score]", "[itemprop='score']")
    scopes = [card, soup] if card else [soup]
    for scope in scopes:
        for selector in selectors:
            for tag in scope.select(selector):
                value = clean(tag.get("data-score") or tag.get_text(" ", strip=True))
                match = re.fullmatch(r"(\d{1,2})\s*[-–]\s*(\d{1,2})", value)
                if match:
                    return f"{match.group(1)}-{match.group(2)}"
    return ""


def extract_status(card_text_value, event, dt, score):
    # Structured event status is more reliable than generic page text.
    event_status = clean(event.get("eventStatus")).lower()
    if any(token in event_status for token in ("eventcanceled", "eventcancelled", "eventpostponed")):
        return "ended"
    if "eventcompleted" in event_status:
        return "ended"

    text = clean(card_text_value).lower()
    if any(token in text for token in ("انتهت المباراة", "نهاية المباراة", "انتهت", "full time", "ft")):
        return "ended"
    if any(token in text for token in ("الشوط الأول", "الشوط الثاني", "الوقت بدل الضائع", "مباشر الآن", "جارية الآن", "live")):
        return "live"

    now = datetime.now(TZ)
    if dt > now + timedelta(minutes=5):
        return "upcoming"
    if dt.date() > now.date():
        return "upcoming"
    if dt.date() < now.date():
        return "ended"
    if dt - timedelta(minutes=5) <= now <= dt + timedelta(hours=4, minutes=30):
        return "live"
    if now > dt + timedelta(hours=4, minutes=30):
        return "ended"
    return "upcoming"


def plausible_field(value, max_length=70):
    value = clean(value).strip(" .،:؛-|")
    if not value or len(value) > max_length:
        return ""
    junk = (
        "المعلق الرياضي وصف", "المعلق الصوتي", "يتولى المعلق", "بيانات البث",
        "القناة المدرجة", "وفقًا لبيانات", "أحداث المواجهة", "غير معروف",
    )
    if any(item in value for item in junk):
        return ""
    return value


def extract_channel(text):
    patterns = (
        r"القناة الناقلة\s*[:：-]\s*([^،؛|.]{2,60})",
        r"القناة\s*[:：-]\s*([^،؛|.]{2,60})",
    )
    for pattern in patterns:
        match = re.search(pattern, clean(text), re.I)
        if match:
            value = plausible_field(match.group(1), 60)
            if value:
                return value
    return ""


def extract_commentator(text):
    patterns = (
        r"المعلق\s*[:：-]\s*([^،؛|.]{2,50})",
        r"بصوت\s+([^،؛|.]{2,50})",
    )
    for pattern in patterns:
        match = re.search(pattern, clean(text), re.I)
        if match:
            value = plausible_field(match.group(1), 50)
            if value and not any(word in value for word in ("الرياضي", "المباراة", "المواجهة", "بيانات")):
                return value
    return ""


def extract_league(text):
    patterns = (
        r"(?:البطولة|الدوري|المسابقة)\s*[:：-]\s*([^،؛|.]{2,100})",
        r"ضمن منافسات\s+([^،؛|.]{2,100})",
    )
    for pattern in patterns:
        match = re.search(pattern, clean(text), re.I)
        if match:
            value = plausible_field(match.group(1), 100)
            if value:
                return value
    return ""


def parse_match(url, day, listing_soup):
    soup = get_soup(url)
    if not soup:
        return None

    card = find_card(listing_soup, url)
    card_text_value = card_text(card)
    page_text = clean(soup.get_text(" ", strip=True))
    structured = read_jsonld(soup)
    event = find_event(structured)

    home, away, home_logo, away_logo = extract_teams(soup, url, event, card)
    if not home or not away or home.lower() == away.lower():
        print("Team names missing/invalid:", url)
        return None

    dt = extract_datetime(soup, event, day, card)
    if not dt:
        print("Match time missing:", home, away)
        return None

    home_logo, away_logo = extract_logos(card, home, away, home_logo, away_logo)
    score = extract_score(soup, event, card)
    status = extract_status(card_text_value, event, dt, score)

    # Metadata is extracted from the match card first. Avoid generic article prose.
    channel = extract_channel(card_text_value)
    commentator = extract_commentator(card_text_value)
    league = extract_league(card_text_value)
    if not league:
        league = extract_league(page_text[:1200])

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
        "streamUrl": "",
    }


def validate_matches(matches):
    required = {
        "league", "home", "away", "team1", "team2", "home_img", "away_img",
        "hour", "time", "date", "match_date", "status", "score", "channel",
        "commentator", "streamUrl",
    }
    for index, match in enumerate(matches):
        if not isinstance(match, dict) or not required.issubset(match):
            raise ValueError(f"Invalid match structure at index {index}")
        if not match["home"] or not match["away"] or match["home"].lower() == match["away"].lower():
            raise ValueError(f"Invalid team names at index {index}")
        if re.search(r"بتاريخ\s+\d{4}-\d{2}-\d{2}|في دوري\s+", match["away"]):
            raise ValueError(f"Contaminated away team at index {index}: {match['away']}")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", match["date"]):
            raise ValueError(f"Invalid date at index {index}")
        if not re.fullmatch(r"\d{2}:\d{2}", match["hour"]):
            raise ValueError(f"Invalid time at index {index}")
        if match["status"] not in ("upcoming", "live", "ended"):
            raise ValueError(f"Invalid status at index {index}")
        if len(match["commentator"]) > 50 or "المعلق الرياضي وصف" in match["commentator"]:
            raise ValueError(f"Invalid commentator at index {index}")


def save_json(data):
    content = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=".", delete=False) as handle:
            handle.write(content)
            temp_path = handle.name
        # Verify generated JSON before replacing the existing file.
        with open(temp_path, "r", encoding="utf-8") as handle:
            json.load(handle)
        os.replace(temp_path, OUTPUT)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


def main():
    print("=" * 45)
    print("YALLA KORA - SHOT.WIKI UPDATER")
    print("=" * 45)
    all_matches = {}
    failed_days = []

    for day in ("yesterday", "today", "tomorrow"):
        print("\nLoading:", day)
        listing_soup = get_soup(PAGES[day])
        if not listing_soup:
            failed_days.append(day)
            print("Could not load:", day)
            continue

        links = collect_links(listing_soup)
        print("Matches found:", len(links))
        for index, url in enumerate(links, 1):
            print(f"Checking {index}/{len(links)}")
            try:
                match = parse_match(url, day, listing_soup)
                if match:
                    key = (match["date"], match["home"].casefold(), match["away"].casefold())
                    all_matches[key] = match
                    print("OK:", match["home"], "-", match["away"], match["hour"], match["status"])
            except Exception as exc:
                print("Match error:", url, exc)
            time.sleep(DELAY)

    matches = list(all_matches.values())
    today_date = datetime.now(TZ).date()
    today_iso = today_date.isoformat()
    yesterday_iso = (today_date - timedelta(days=1)).isoformat()
    tomorrow_iso = (today_date + timedelta(days=1)).isoformat()

    today = [m for m in matches if m["date"] == today_iso]
    yesterday = [m for m in matches if m["date"] == yesterday_iso]
    tomorrow = [m for m in matches if m["date"] == tomorrow_iso]

    # Never overwrite good data if today's page failed or returned no matches.
    if "today" in failed_days or not today:
        raise RuntimeError("Today's matches could not be verified; existing matches.json was preserved.")

    validate_matches(matches)
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
        "tomorrow": tomorrow,
    }
    save_json(data)
    print("\nUPDATE COMPLETE")
    print("Today:", len(today), "Yesterday:", len(yesterday), "Tomorrow:", len(tomorrow))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("\nUPDATE FAILED:", exc)
        sys.exit(1)
