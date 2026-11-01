
import os
import re
import sys
import json
import time
import tempfile
import requests

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup


# =========================
# الإعدادات
# =========================

BASE_URL = "https://shot.wiki"
OUTPUT = "matches.json"

TIMEZONE = ZoneInfo("Asia/Baghdad")

MAX_PAGES = 70
REQUEST_DELAY = 0.3

SITEMAP_URLS = [
    BASE_URL + "/sitemap.xml",
    BASE_URL + "/sitemap_index.xml",
    BASE_URL + "/wp-sitemap.xml",
]

LISTING_URLS = [
    BASE_URL,
    BASE_URL + "/matches/",
]

SAMPLE_MATCH_URL = (
    "https://shot.wiki/matches/"
    "%d9%85%d8%a8%d8%a7%d8%b1%d8%a7%d8%a9-"
    "%d8%b3%d8%a8%d9%88%d8%b1%d8%aa%d9%8a%d9%86%d8%ac-"
    "%d8%a8%d8%b1%d8%a7%d8%ba%d8%a7-"
    "%d9%88-%d9%81%d8%a7%d9%85%d8%a7%d9%84%d9%8a%d9%83%d8%a7%d9%88/"
)


# =========================
# الاتصال بالموقع
# =========================

session = requests.Session()

session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 10) "
        "AppleWebKit/537.36 Chrome/120.0 Mobile Safari/537.36"
    ),
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
})


def get_page(url):
    try:
        response = session.get(url, timeout=20)
        response.raise_for_status()

        if "text/html" not in response.headers.get(
            "Content-Type", ""
        ) and not url.endswith(".xml"):
            return None

        response.encoding = response.apparent_encoding
        return response.text

    except requests.RequestException as error:
        print("تعذر فتح:", url, error)
        return None


# =========================
# اكتشاف روابط المباريات
# =========================

def valid_match_url(url):
    parsed = urlparse(url)

    if parsed.netloc and parsed.netloc != urlparse(BASE_URL).netloc:
        return False

    return "/matches/" in parsed.path and parsed.path != "/matches/"


def collect_sitemap_links():
    found = set()

    for sitemap_url in SITEMAP_URLS:
        xml = get_page(sitemap_url)

        if not xml:
            continue

        soup = BeautifulSoup(xml, "html.parser")

        for loc in soup.find_all("loc"):
            link = loc.get_text(strip=True)

            if link.endswith(".xml"):
                child_xml = get_page(link)

                if child_xml:
                    child_soup = BeautifulSoup(child_xml, "html.parser")

                    for child_loc in child_soup.find_all("loc"):
                        child_link = child_loc.get_text(strip=True)

                        if valid_match_url(child_link):
                            found.add(child_link)

            elif valid_match_url(link):
                found.add(link)

    return found


def collect_listing_links():
    found = set()

    for listing_url in LISTING_URLS:
        html = get_page(listing_url)

        if not html:
            continue

        soup = BeautifulSoup(html, "html.parser")

        for tag in soup.find_all("a", href=True):
            link = urljoin(BASE_URL, tag["href"]).split("#")[0]

            if valid_match_url(link):
                found.add(link)

    return found


def collect_links():
    print("أبحث عن روابط المباريات...")

    links = set()

    links.update(collect_listing_links())
    links.update(collect_sitemap_links())

    # رابط المثال للفحص فقط، وليس بيانات مضمونة لمباراة اليوم
    links.add(SAMPLE_MATCH_URL)

    links = sorted(links)

    print("الروابط المكتشفة:", len(links))

    return links[:MAX_PAGES]


# =========================
# قراءة البيانات المنظمة
# =========================

def walk_json(data):
    if isinstance(data, dict):
        yield data

        graph = data.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                yield from walk_json(item)

        for value in data.values():
            if isinstance(value, (dict, list)):
                yield from walk_json(value)

    elif isinstance(data, list):
        for item in data:
            yield from walk_json(item)


def read_structured_data(soup):
    events = []

    for script in soup.find_all(
        "script",
        type="application/ld+json"
    ):
        raw = script.string or script.get_text()

        try:
            data = json.loads(raw)

            for item in walk_json(data):
                item_type = item.get("@type", "")

                if isinstance(item_type, list):
                    item_type = " ".join(item_type)

                if (
                    "SportsEvent" in item_type
                    or "Event" in item_type
                ):
                    events.append(item)

        except (ValueError, TypeError):
            continue

    return events


def team_info(value):
    if isinstance(value, str):
        return value.strip(), ""

    if isinstance(value, dict):
        name = value.get("name", "")
        logo = value.get("logo", "")

        if isinstance(logo, dict):
            logo = logo.get("url", "")

        if isinstance(logo, list) and logo:
            logo = logo[0]

        if isinstance(logo, dict):
            logo = logo.get("url", "")

        return str(name).strip(), str(logo).strip()

    return "", ""


# =========================
# التاريخ والوقت
# =========================

def parse_date(value):
    if not value:
        return None

    value = str(value).strip()

    try:
        dt = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TIMEZONE)
        else:
            dt = dt.astimezone(TIMEZONE)

        return dt

    except ValueError:
        return None


def classify_day(dt):
    today = datetime.now(TIMEZONE).date()

    if dt.date() == today:
        return "today"

    if dt.date() == today - timedelta(days=1):
        return "yesterday"

    if dt.date() == today + timedelta(days=1):
        return "tomorrow"

    return None


# =========================
# استخراج النصوص
# =========================

def clean_text(value):
    if not value:
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(value)
    ).strip()


def find_label(soup, labels):
    for element in soup.find_all(
        ["div", "span", "p", "li", "td", "strong"]
    ):
        text = clean_text(element.get_text(" ", strip=True))

        if not text or len(text) > 120:
            continue

        for label in labels:
            if text.startswith(label):
                value = text[len(label):].strip(" :-：")

                if value:
                    return value

                sibling = element.find_next_sibling()

                if sibling:
                    value = clean_text(
                        sibling.get_text(" ", strip=True)
                    )

                    if value and len(value) < 120:
                        return value

    return ""


def extract_title(soup):
    for selector, attribute in [
        ('meta[property="og:title"]', "content"),
        ('meta[name="twitter:title"]', "content"),
    ]:
        tag = soup.select_one(selector)

        if tag and tag.get(attribute):
            return clean_text(tag.get(attribute))

    h1 = soup.find("h1")

    if h1:
        return clean_text(h1.get_text(" ", strip=True))

    if soup.title:
        return clean_text(soup.title.get_text())

    return ""


def extract_teams(title, event):
    home = ""
    away = ""
    home_img = ""
    away_img = ""

    if event:
        home, home_img = team_info(
            event.get("homeTeam")
        )

        away, away_img = team_info(
            event.get("awayTeam")
        )

        if not home or not away:
            competitors = event.get("competitor", [])

            if isinstance(competitors, dict):
                competitors = [competitors]

            names = []

            for competitor in competitors:
                name, logo = team_info(competitor)

                if name:
                    names.append((name, logo))

            if len(names) >= 2:
                home = home or names[0][0]
                away = away or names[1][0]

                home_img = home_img or names[0][1]
                away_img = away_img or names[1][1]

    if not home or not away:
        separators = [" vs ", " VS ", " - ", " – ", " و "]

        for separator in separators:
            if separator in title:
                parts = title.split(separator, 1)

                if len(parts) == 2:
                    home = home or clean_text(parts[0])
                    away = away or clean_text(parts[1])
                    break

    return home, away, home_img, away_img


# =========================
# حالة المباراة والنتيجة
# =========================

def extract_status(soup, event):
    status_text = ""

    if event:
        status_text = clean_text(
            event.get("eventStatus", "")
        )

    if not status_text:
        status_text = clean_text(
            soup.get_text(" ", strip=True)
        )[:3000]

    lowered = status_text.lower()

    if any(word in lowered for word in [
        "live", "inprogress", "مباشر", "جارية", "الشوط"
    ]):
        return "live"

    if any(word in lowered for word in [
        "ended", "finished", "completed",
        "انتهت", "نهاية المباراة"
    ]):
        return "ended"

    return "upcoming"


def extract_score(soup):
    score = find_label(
        soup,
        ["النتيجة", "نتيجة المباراة", "Score", "النتيجة:"]
    )

    if score and re.search(r"\d+\s*[-:]\s*\d+", score):
        return score

    return ""


# =========================
# استخراج مباراة واحدة
# =========================

def parse_match(url):
    html = get_page(url)

    if not html:
        return None

    soup = BeautifulSoup(html, "html.parser")

    events = read_structured_data(soup)
    event = events[0] if events else {}

    title = extract_title(soup)

    home, away, home_img, away_img = extract_teams(
        title,
        event
    )

    # نعتمد على تاريخ بداية الحدث فقط.
    # لا نستخدم تاريخ نشر المقال لأنه قد يكون مختلفاً.
    date_value = ""

    if event:
        date_value = event.get("startDate", "")

    if not date_value:
        tag = soup.select_one(
            '[itemprop="startDate"]'
        )

        if tag:
            date_value = (
                tag.get("content")
                or tag.get("datetime")
                or tag.get_text(strip=True)
            )

    if not date_value:
        return None

    match_datetime = parse_date(date_value)

    if not match_datetime:
        return None

    day = classify_day(match_datetime)

    if not day:
        return None

    if not home or not away:
        return None

    league = find_label(
        soup,
        ["البطولة", "الدوري", "المسابقة", "League"]
    )

    channel = find_label(
        soup,
        ["القناة الناقلة", "القناة", "Channel"]
    )

    commentator = find_label(
        soup,
        ["المعلق", "المعلق الصوتي", "Commentator"]
    )

    return {
        "league": league,
        "home": home,
        "away": away,
        "team1": home,
        "team2": away,
        "home_img": home_img,
        "away_img": away_img,
        "hour": match_datetime.strftime("%H:%M"),
        "time": match_datetime.strftime("%H:%M"),
        "date": match_datetime.strftime("%Y-%m-%d"),
        "match_date": match_datetime.strftime("%Y-%m-%d"),
        "status": extract_status(soup, event),
        "score": extract_score(soup),
        "channel": channel,
        "commentator": commentator,
        "streamUrl": ""
    }


# =========================
# حفظ الملف بأمان
# =========================

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
        ) as file:
            file.write(content)
            temp_path = file.name

        os.replace(temp_path, OUTPUT)

    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


# =========================
# تشغيل التحديث
# =========================

def main():
    print("=" * 45)
    print("Yalla Kora - Shot Wiki")
    print("=" * 45)

    links = collect_links()

    if not links:
        raise RuntimeError(
            "لم يتم العثور على روابط مباريات."
        )

    results = {}
    errors = 0

    for index, url in enumerate(links, 1):
        print(
            f"فحص المباراة {index}/{len(links)}"
        )

        try:
            match = parse_match(url)

            if match:
                key = (
                    match["date"],
                    match["home"],
                    match["away"]
                )

                if key not in results:
                    results[key] = match
                else:
                    old = results[key]

                    for field in [
                        "league",
                        "channel",
                        "commentator",
                        "home_img",
                        "away_img",
                        "score"
                    ]:
                        if not old[field] and match[field]:
                            old[field] = match[field]

                print(
                    "تم العثور:",
                    match["home"],
                    "-",
                    match["away"]
                )

        except Exception as error:
            errors += 1
            print("خطأ:", error)

        time.sleep(REQUEST_DELAY)

    matches = list(results.values())

    today = [
        m for m in matches
        if classify_day(
            parse_date(m["date"])
        ) == "today"
    ]

    yesterday = [
        m for m in matches
        if classify_day(
            parse_date(m["date"])
        ) == "yesterday"
    ]

    tomorrow = [
        m for m in matches
        if classify_day(
            parse_date(m["date"])
        ) == "tomorrow"
    ]

    # لا نمسح البيانات القديمة إذا لم نجد مباريات اليوم.
    if not today:
        raise RuntimeError(
            "لم يتم العثور على مباريات اليوم. "
            "لم يتم تغيير matches.json القديم."
        )

    now = datetime.now(TIMEZONE)

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

    print("=" * 45)
    print("اكتمل تحديث matches.json")
    print("مباريات اليوم:", len(today))
    print("مباريات الأمس:", len(yesterday))
    print("مباريات الغد:", len(tomorrow))
    print("أخطاء الصفحات:", errors)
    print("=" * 45)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("فشل التحديث:", error)
        sys.exit(1)
