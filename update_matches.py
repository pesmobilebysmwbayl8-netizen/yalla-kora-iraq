
#!/usr/bin/env python3
# Yalla Kora - Blogger Matches Fetcher

import json
import re
import os
import sys
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

SOURCE_URL = "https://yalliraqkoraliev8.blogspot.com/"
OUTPUT = Path("matches.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 Chrome/126 Mobile Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/json",
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
}

def normalize_status(status):
    s = str(status or "").strip().lower()

    if any(x in s for x in ["live", "مباشر", "جارية"]):
        return "live"

    if any(x in s for x in ["ended", "finished", "انتهت"]):
        return "ended"

    return "upcoming"


def extract_json(soup, element_id):
    node = soup.find(id=element_id)

    if not node:
        return []

    raw = node.string or node.get_text(strip=True)

    if not raw:
        return []

    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("matches", [])
    except json.JSONDecodeError:
        print(f"Invalid JSON in {element_id}")

    return []


def normalize_match(match):
    if not isinstance(match, dict):
        return None

    home = (
        match.get("home")
        or match.get("team1")
        or match.get("homeTeam")
        or ""
    )

    away = (
        match.get("away")
        or match.get("team2")
        or match.get("awayTeam")
        or ""
    )

    if not home and not away:
        return None

    return {
        "league": match.get("league", ""),
        "home": home,
        "away": away,
        "team1": home,
        "team2": away,
        "home_img": match.get("home_img") or match.get("team1_img", ""),
        "away_img": match.get("away_img") or match.get("team2_img", ""),
        "hour": match.get("hour") or match.get("time", ""),
        "time": match.get("time") or match.get("hour", ""),
        "status": normalize_status(match.get("status")),
        "score": match.get("score", ""),
        "channel": match.get("channel", ""),
        "commentator": match.get("commentator", ""),
        "streamUrl": match.get("streamUrl", ""),
        "match_link": match.get("match_link", ""),
    }


def scrape():
    response = requests.get(
        SOURCE_URL,
        headers=HEADERS,
        timeout=30
    )

    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    today = extract_json(soup, "matchesTodayJSON")
    yesterday = extract_json(soup, "matchesYesterdayJSON")

    if not today and not yesterday:
        raise RuntimeError(
            "لم يتم العثور على بيانات المباريات. "
            "تحقق من وجود matchesTodayJSON و matchesYesterdayJSON "
            "في HTML الصفحة الرئيسية."
        )

    today_matches = [
        m for item in today
        if (m := normalize_match(item))
    ]

    yesterday_matches = [
        m for item in yesterday
        if (m := normalize_match(item))
    ]

    all_matches = today_matches + yesterday_matches

    return {
        "success": True,
        "source": SOURCE_URL,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(all_matches),
        "today_count": len(today_matches),
        "yesterday_count": len(yesterday_matches),
        "matches": all_matches,
        "today": today_matches,
        "yesterday": yesterday_matches,
    }


def save(data):
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

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
    data = scrape()
    save(data)

    print("تم تحديث المباريات بنجاح")
    print("المصدر:", SOURCE_URL)
    print("مباريات اليوم:", data["today_count"])
    print("مباريات الأمس:", data["yesterday_count"])
    print("المجموع:", data["count"])
    print("الملف:", OUTPUT.resolve())


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("فشل التحديث:", e, file=sys.stderr)
        sys.exit(1)
