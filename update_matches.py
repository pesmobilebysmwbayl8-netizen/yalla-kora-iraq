
import json
import re
import sys
import os
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://syriashdab.com/"
OUTPUT = Path("matches.json")

PAGES = {
    "today": urljoin(BASE, "matches-today/"),
    "yesterday": urljoin(BASE, "matches-yesterday/"),
    "tomorrow": urljoin(BASE, "matches-tomorrow/"),
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36",
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
}


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def get_status(text):
    text = clean(text).lower()

    if any(x in text for x in ["جارية الآن", "مباشر", "الشوط", "live"]):
        return "live"

    if any(x in text for x in ["انتهت", "ended", "finished"]):
        return "ended"

    return "upcoming"


def is_status(text):
    text = clean(text).lower()
    words = [
        "جارية الآن", "مباشر", "الشوط", "live",
        "انتهت", "ended", "finished",
        "لم تبدأ", "upcoming", "not started"
    ]
    return any(x in text for x in words)


def is_metadata(line):
    line = clean(line)

    if not line or is_status(line):
        return True

    if re.search(r"\d{1,2}:\d{2}", line):
        return True

    if re.match(r"^\d+\s*[-–:]\s*\d+$", line):
        return True

    return line.startswith(("📺", "🏆"))


def parse_card(card, page_url, day):
    lines = [
        clean(x)
        for x in card.get_text("\n", strip=True).splitlines()
    ]
    lines = [x for x in lines if x]

    status_index = next(
        (i for i, x in enumerate(lines) if is_status(x)),
        None
    )

    if status_index is None:
        return None

    before = [
        x for x in lines[:status_index]
        if not is_metadata(x)
    ]

    after = [
        x for x in lines[status_index + 1:]
        if not is_metadata(x)
    ]

    if not before or not after:
        return None

    home = before[0]
    away = after[0]

    if home == away or len(home) > 80 or len(away) > 80:
        return None

    hour = ""
    score = ""

    for line in lines:
        if re.search(r"\d{1,2}:\d{2}", line):
            hour = line

        if re.match(r"^\d+\s*[-–:]\s*\d+$", line):
            score = line

    channel = ""
    league = ""

    for line in lines:
        if line.startswith("📺"):
            channel = clean(line.replace("📺", ""))

        if line.startswith("🏆"):
            league = clean(line.replace("🏆", ""))

    images = card.find_all("img")

    def find_image(team):
        for img in images:
            alt = clean(img.get("alt"))

            if alt and (alt == team or team in alt):
                return (
                    img.get("data-src")
                    or img.get("data-lazy-src")
                    or img.get("src")
                    or ""
                )

        return ""

    match_link = ""

    for a in card.find_all("a", href=True):
        href = a["href"]

        if href and not href.startswith("#"):
            match_link = urljoin(page_url, href)
            break

    return {
        "day": day,
        "league": league,
        "home": home,
        "away": away,
        "team1": home,
        "team2": away,
        "home_img": find_image(home),
        "away_img": find_image(away),
        "hour": hour,
        "time": hour,
        "status": get_status(lines[status_index]),
        "score": score,
        "channel": channel,
        "commentator": "",
        "streamUrl": "",
        "match_link": match_link
    }


def scrape_page(session, day, url):
    response = session.get(url, timeout=35)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    selectors = [
        ".match-card",
        ".match-item",
        ".matches-item",
        ".fixture",
        ".event-card",
        ".event-item",
        "[class*='match-card']",
        "[class*='match-item']",
        "[class*='fixture']",
    ]

    cards = []

    for selector in selectors:
        cards.extend(soup.select(selector))

    # Fallback إذا اختلفت أسماء عناصر التصميم
    if not cards:
        for node in soup.find_all(["article", "li", "div"]):
            text = node.get_text(" ", strip=True)

            if is_status(text) and len(text) < 1200:
                cards.append(node)

    matches = []
    seen = set()

    for card in cards:
        match = parse_card(card, url, day)

        if not match:
            continue

        key = (
            match["home"].casefold(),
            match["away"].casefold()
        )

        if key in seen:
            continue

        seen.add(key)
        matches.append(match)

    if not matches:
        raise RuntimeError(
            f"لم يتم استخراج مباريات {day} من {url}"
        )

    print(f"{day}: {len(matches)} مباراة")
    return matches


def save_json(data):
    payload = json.dumps(
        data,
        ensure_ascii=False,
        indent=2
    ) + "\n"

    temp_name = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=OUTPUT.parent,
            delete=False
        ) as tmp:
            tmp.write(payload)
            temp_name = tmp.name

        os.replace(temp_name, OUTPUT)
        temp_name = None

    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def main():
    session = requests.Session()
    session.headers.update(HEADERS)

    results = {}
    errors = {}

    for day, url in PAGES.items():
        try:
            results[day] = scrape_page(session, day, url)
        except Exception as error:
            errors[day] = str(error)
            print(f"تحذير {day}: {error}")

    # لا نكتب ملفاً فارغاً إذا فشل جلب مباريات اليوم
    if not results.get("today"):
        raise RuntimeError(
            "فشل جلب مباريات اليوم. الملف القديم لم يتغير."
        )

    today = results.get("today", [])
    yesterday = results.get("yesterday", [])
    tomorrow = results.get("tomorrow", [])

    all_matches = today + yesterday + tomorrow

    data = {
        "success": True,
        "source": BASE,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(all_matches),
        "today_count": len(today),
        "yesterday_count": len(yesterday),
        "tomorrow_count": len(tomorrow),
        "matches": all_matches,
        "today": today,
        "yesterday": yesterday,
        "tomorrow": tomorrow,
        "warnings": errors
    }

    save_json(data)

    print("تم تحديث matches.json بنجاح")
    print("مباريات اليوم:", len(today))
    print("مباريات الأمس:", len(yesterday))
    print("مباريات الغد:", len(tomorrow))
    print("المجموع:", len(all_matches))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("فشل التحديث:", error, file=sys.stderr)
        sys.exit(1)
