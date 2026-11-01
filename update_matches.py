
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
# الإعدادات
# =====================================

BASE_URL = "https://shot.wiki"
OUTPUT = "matches.json"
TZ = ZoneInfo("Asia/Baghdad")

PAGES = {
    "today": BASE_URL + "/matches-today/",
    "yesterday": BASE_URL + "/matches-yesterday/",
    "tomorrow": BASE_URL + "/matches-tomorrow/",
}

DELAY = 0.25
MAX_MATCHES_PER_DAY = 100

session = requests.Session()
session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 10) "
        "AppleWebKit/537.36 Chrome/120.0 Mobile Safari/537.36"
    ),
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
})


# =====================================
# أدوات عامة
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
        print("تعذر تحميل الصفحة:", url, e)
        return None


def get_soup(url):
    html = get_page(url)
    if not html:
        return None
    return BeautifulSoup(html, "html.parser")


def valid_url(url):
    p = urlparse(url)
    return (
        p.netloc == "shot.wiki"
        and "/matches/" in p.path
        and p.path != "/matches/"
    )


def unique(items):
    result = []
    seen = set()

    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)

    return result


# =====================================
# جلب روابط المباريات من صفحات الأيام
# =====================================

def collect_day_links(day):
    print("جلب روابط:", day)

    soup = get_soup(PAGES[day])

    if not soup:
        return []

    links = []

    for a in soup.find_all("a", href=True):
        url = urljoin(BASE_URL, a["href"]).split("#")[0]

        if valid_url(url):
            links.append(url)

    links = unique(links)

    print("عدد الروابط:", len(links))

    return links[:MAX_MATCHES_PER_DAY]


# =====================================
# استخراج نص بطاقة المباراة
# =====================================

def get_card_text(anchor):
    current = anchor

    for _ in range(8):
        if not current or not getattr(current, "parent", None):
            break

        current = current.parent
        text = clean(current.get_text(" ", strip=True))

        has_time = bool(
            re.search(r"\b\d{1,2}:\d{2}\s*(?:AM|PM)?\b", text, re.I)
        )

        has_status = any(x in text for x in [
            "لم تبدأ", "انتهت", "مباشر", "الشوط"
        ])

        has_score = bool(
            re.search(r"\b\d+\s*[-:]\s*\d+\b", text)
        )

        if has_time and (has_status or has_score):
            if len(text) < 1500:
                return current, text

    return anchor.parent, clean(anchor.parent.get_text(" ", strip=True))


def find_card(soup, match_url):
    for a in soup.find_all("a", href=True):
        url = urljoin(BASE_URL, a["href"]).split("#")[0]

        if url == match_url:
            return get_card_text(a)

    return None, ""


# =====================================
# أسماء الفريقين
# =====================================

def extract_teams(soup, url, card_text=""):
    title = ""

    for selector in [
        "h1",
        'meta[property="og:title"]',
        'meta[name="twitter:title"]',
    ]:
        tag = soup.select_one(selector)

        if not tag:
            continue

        if tag.name == "meta":
            title = clean(tag.get("content"))
        else:
            title = clean(tag.get_text(" ", strip=True))

        if title:
            break

    page_text = clean(soup.get_text(" ", strip=True))

    sources = [title, page_text[:2500], card_text]

    patterns = [
        r"بطاقة المباراة\s+(.+?)\s+(?:Vs|vs|VS)\s+(.+?)(?:\s+البطولة|\s+تاريخ المباراة|$)",
        r"مباراة\s+(.+?)\s+و\s+(.+?)(?:\s+مباشر|\s+اليوم|\s+يلا شوت|$)",
    ]

    for source in sources:
        for pattern in patterns:
            match = re.search(pattern, source, re.I)

            if match:
                home = clean(match.group(1))
                away = clean(match.group(2))

                home = re.sub(
                    r"^(بث مباشر|يلا شوت)\s*", "", home
                ).strip()

                away = re.sub(
                    r"\s*(بث مباشر|يلا شوت)$", "", away
                ).strip()

                if home and away and len(home) < 70 and len(away) < 70:
                    return home, away

    # محاولة أخيرة من رابط المباراة
    slug = unquote(urlparse(url).path.split("/")[-2])
    slug = slug.replace("مباراة-", "").replace("-", " ")

    if " و " in slug:
        parts = slug.split(" و ", 1)

        if len(parts) == 2:
            return clean(parts[0]), clean(parts[1])

    return "", ""


# =====================================
# التاريخ والوقت
# =====================================

def extract_datetime(text, fallback_day):
    date_match = re.search(
        r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})",
        text
    )

    time_match = re.search(
        r"الساعة\s*(\d{1,2}):(\d{2})|"
        r"\b(\d{1,2}):(\d{2})\s*(AM|PM)\b",
        text,
        re.I
    )

    if date_match:
        d, m, y = map(int, date_match.groups())
        try:
            match_date = datetime(y, m, d).date()
        except ValueError:
            match_date = None
    else:
        match_date = None

    if not match_date:
        today = datetime.now(TZ).date()

        offsets = {
            "today": 0,
            "yesterday": -1,
            "tomorrow": 1,
        }

        match_date = today + timedelta(
            days=offsets[fallback_day]
        )

    if not time_match:
        return None

    if time_match.group(1) is not None:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2))
    else:
        hour = int(time_match.group(3))
        minute = int(time_match.group(4))
        period = time_match.group(5).upper()

        if period == "PM" and hour != 12:
            hour += 12
        elif period == "AM" and hour == 12:
            hour = 0

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None

    # وقت Shot Wiki في بيانات المباراة مذكور بتوقيت مصر.
    # العراق متقدم بساعة عن مصر في تاريخ التشغيل الحالي.
    if "بتوقيت مصر" in text:
        dt = datetime(
            match_date.year,
            match_date.month,
            match_date.day,
            hour,
            minute
        ) + timedelta(hours=1)

    elif "بتوقيت بغداد" in text or "بتوقيت العراق" in text:
        dt = datetime(
            match_date.year,
            match_date.month,
            match_date.day,
            hour,
            minute
        )

    else:
        dt = datetime(
            match_date.year,
            match_date.month,
            match_date.day,
            hour,
            minute
        ) + timedelta(hours=1)

    return dt.replace(tzinfo=TZ)


# =====================================
# القناة والمعلق والبطولة
# =====================================

def extract_channel(text):
    patterns = [
        r"القناة المدرجة في بيانات المباراة هي\s*(.+?)(?:\.|،|$)",
        r"اسم القناة\s*(.+?)(?:\s+المعلق|\s+البطولة|$)",
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
# النتيجة والحالة والشعارات
# =====================================

def extract_score(text):
    m = re.search(
        r"\b(\d{1,2})\s*[-:]\s*(\d{1,2})\b",
        text
    )

    if m:
        return m.group(1) + "-" + m.group(2)

    return ""


def extract_status(text, score):
    if any(x in text for x in [
        "انتهت", "نهاية المباراة", "مباراة انتهت"
    ]):
        return "ended"

    if any(x in text for x in [
        "مباشر", "جارية", "الشوط الأول", "الشوط الثاني"
    ]):
        return "live"

    return "upcoming"


def extract_logos(card):
    home_img = ""
    away_img = ""

    if not card:
        return home_img, away_img

    images = card.find_all("img")

    found = []

    for img in images:
        src = (
            img.get("data-src")
            or img.get("data-lazy-src")
            or img.get("src")
            or ""
        )

        if src.startswith("//"):
            src = "https:" + src

        if src.startswith("http"):
            found.append(src)

    if len(found) >= 2:
        home_img = found[0]
        away_img = found[1]

    return home_img, away_img


# =====================================
# قراءة مباراة واحدة
# =====================================

def parse_match(url, day, listing_soup):
    soup = get_soup(url)

    if not soup:
        return None

    card, card_text = find_card(listing_soup, url)

    page_text = clean(soup.get_text(" ", strip=True))

    home, away = extract_teams(
        soup, url, card_text
    )

    if not home or not away:
        print("لم أتعرف على الفريقين:", url)
        return None

    # نقرأ التاريخ والوقت من صفحة المباراة أولاً
    dt = extract_datetime(page_text, day)

    if not dt:
        # عند عدم وجود تاريخ في التفاصيل نستخدم بطاقة اليوم
        dt = extract_datetime(card_text, day)

    if not dt:
        print("لم أتعرف على الوقت:", home, "-", away)
        return None

    # بيانات القناة والمعلق من صفحة المباراة
    channel = extract_channel(page_text)
    commentator = extract_commentator(page_text)
    league = extract_league(page_text)

    # معلومات البطاقة كخيار احتياطي
    if not channel:
        channel = extract_channel(card_text)

    if not league:
        league = extract_league(card_text)

    score = extract_score(card_text)

    if not score:
        score = extract_score(page_text)

    status = extract_status(card_text, score)

    if not card_text:
        status = extract_status(page_text, score)

    home_img, away_img = extract_logos(card)

    return {
        "league": league,
        "home": home,
        "away": away,
        "team1": home,
        "team2": away,
        "home_img": home_img,
        "away_img": away_img,
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
# حفظ JSON بأمان
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
# التشغيل
# =====================================

def main():
    print("=" * 45)
    print("Yalla Kora - Shot Wiki")
    print("=" * 45)

    all_matches = {}

    for day in ["yesterday", "today", "tomorrow"]:
        print("\nتحميل صفحة", day)

        listing_soup = get_soup(PAGES[day])

        if not listing_soup:
            print("تعذر تحميل صفحة", day)
            continue

        links = []

        for a in listing_soup.find_all("a", href=True):
            url = urljoin(BASE_URL, a["href"]).split("#")[0]

            if valid_url(url):
                links.append(url)

        links = unique(links)[:MAX_MATCHES_PER_DAY]

        print("روابط المباريات:", len(links))

        for index, url in enumerate(links, 1):
            print(f"فحص {index}/{len(links)}")

            try:
                match = parse_match(url, day, listing_soup)

                if match:
                    key = (
                        match["date"],
                        match["home"],
                        match["away"]
                    )

                    all_matches[key] = match

                    print(
                        "تم:",
                        match["home"],
                        "-",
                        match["away"],
                        match["hour"]
                    )

            except Exception as e:
                print("خطأ في المباراة:", e)

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
            "لم يتم استخراج مباريات اليوم. "
            "تم الاحتفاظ بملف matches.json القديم."
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
    print("اكتمل التحديث")
    print("اليوم:", len(today))
    print("الأمس:", len(yesterday))
    print("الغد:", len(tomorrow))
    print("=" * 45)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("\nفشل التحديث:", e)
        sys.exit(1)
            
