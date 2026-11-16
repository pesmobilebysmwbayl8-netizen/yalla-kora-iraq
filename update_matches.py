
import json
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
import update_matches as engine

TZ = ZoneInfo("Asia/Baghdad")
NOW = datetime.now(TZ)
TODAY = NOW.date()

SOURCES = {
    "filgoal": "https://www.filgoal.com/matches?date=today",
    "yallakora": "https://www.yallakora.com/",
    "almashhad": "https://www.almashhad.com/"
}

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 Chrome/130.0 Mobile Safari/537.36",
    "Accept-Language": "ar,en-US;q=0.9"
})

REPORT = {
    name: {
        "pages_checked": 0,
        "matches_found": 0,
        "with_channel": 0,
        "with_commentator": 0,
        "errors": []
    }
    for name in SOURCES
}


def fetch(url):
    r = session.get(url, timeout=25)
    r.raise_for_status()
    if not r.encoding or r.encoding.lower() == "iso-8859-1":
        r.encoding = r.apparent_encoding
    return r.text


def discover(name, start_url):
    pages = [start_url]

    try:
        soup = BeautifulSoup(fetch(start_url), "html.parser")
    except Exception as e:
        REPORT[name]["errors"].append(str(e))
        return pages

    host = urlparse(start_url).netloc

    for a in soup.find_all("a", href=True):
        url = urljoin(start_url, a["href"]).split("#")[0]
        label = a.get_text(" ", strip=True) + " " + url

        if urlparse(url).netloc != host:
            continue

        if re.search(
            r"match|matches|news|sport|مباراة|مباريات|جدول|القنوات",
            label,
            re.I
        ):
            if url not in pages:
                pages.append(url)

        if len(pages) >= 9:
            break

    return pages


def normalize(item):
    date = item.get("date") or item.get("match_date") or TODAY.isoformat()
    home = item.get("home") or item.get("team1") or ""
    away = item.get("away") or item.get("team2") or ""

    return {
        "league": item.get("league") or "كرة القدم",
        "home": home,
        "away": away,
        "team1": home,
        "team2": away,
        "home_img": item.get("home_img") or "",
        "away_img": item.get("away_img") or "",
        "hour": item.get("hour") or item.get("time") or "",
        "time": item.get("hour") or item.get("time") or "",
        "date": date,
        "match_date": date,
        "status": item.get("status") or "upcoming",
        "score": engine.valid_score(item.get("score", "")) or "VS",
        "channel": item.get("channel") or "",
        "commentator": item.get("commentator") or "",
        "streamUrl": item.get("streamUrl") or ""
    }


def run_source(name, url):
    print("\n==========", name.upper(), "==========")
    found = []

    for page_url in discover(name, url):
        try:
            html = fetch(page_url)
            REPORT[name]["pages_checked"] += 1

            items = engine.parse_structured(html)
            items += engine.parse_cards(html, page_url)

            for item in items:
                record = normalize(item)

                if not record["home"] or not record["away"]:
                    continue

                if not any(
                    engine.matches_same(record, old)
                    for old in found
                ):
                    found.append(record)

            print("PAGE OK:", page_url, "| extracted:", len(items))

        except Exception as e:
            REPORT[name]["errors"].append(page_url + " | " + str(e))
            print("PAGE ERROR:", str(e))

    allowed = {
        TODAY.isoformat(),
        (TODAY - timedelta(days=1)).isoformat(),
        (TODAY + timedelta(days=1)).isoformat()
    }

    found = [x for x in found if x["date"] in allowed]

    REPORT[name]["matches_found"] = len(found)
    REPORT[name]["with_channel"] = sum(bool(x["channel"]) for x in found)
    REPORT[name]["with_commentator"] = sum(bool(x["commentator"]) for x in found)

    print("MATCHES:", len(found))
    print("CHANNELS:", REPORT[name]["with_channel"])
    print("COMMENTATORS:", REPORT[name]["with_commentator"])

    return found


def main():
    print("YALLA KORA - TEST ONLY")
    print("Baghdad:", NOW.isoformat())
    print("Production matches.json will NOT be changed.")

    matches = []

    for name, url in SOURCES.items():
        for item in run_source(name, url):
            old = next(
                (x for x in matches if engine.matches_same(x, item)),
                None
            )

            if old is None:
                matches.append(item)
            else:
                for field in (
                    "league", "channel", "commentator",
                    "home_img", "away_img", "hour", "time"
                ):
                    if not old.get(field) and item.get(field):
                        old[field] = item[field]

    matches.sort(key=lambda x: (x["date"], x["hour"], x["home"]))

    result = {
        "version": "TEST-ONLY",
        "updated_at": NOW.isoformat(),
        "timezone": "Asia/Baghdad",
        "matches": matches,
        "today": [x for x in matches if x["date"] == TODAY.isoformat()],
        "yesterday": [
            x for x in matches
            if x["date"] == (TODAY - timedelta(days=1)).isoformat()
        ],
        "tomorrow": [
            x for x in matches
            if x["date"] == (TODAY + timedelta(days=1)).isoformat()
        ],
        "counts": {
            "total": len(matches),
            "with_channel": sum(bool(x["channel"]) for x in matches),
            "with_commentator": sum(bool(x["commentator"]) for x in matches)
        },
        "source_test": REPORT
    }

    with open("test_matches.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("\nTEST FINISHED")
    print(json.dumps(result["counts"], ensure_ascii=False, indent=2))
    print("Report saved: test_matches.json")
    print("Original matches.json was not modified.")


if __name__ == "__main__":
    main()
