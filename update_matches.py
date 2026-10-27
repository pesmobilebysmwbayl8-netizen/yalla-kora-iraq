#!/usr/bin/env python3
"""Fetch today's football matches and save them as stable JSON."""
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

SOURCE_URL = os.getenv("MATCHES_SOURCE_URL", "https://yallashootio.com/matches-todays/")
OUTPUT = Path("matches.json")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ar,en-US;q=0.8,en;q=0.7",
}


def clean(node):
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)) if node else ""


def first_text(root, selectors):
    for selector in selectors:
        node = root.select_one(selector)
        value = clean(node)
        if value:
            return value
    return ""


def first_image(root, selector):
    node = root.select_one(selector)
    if not node:
        return ""
    for key in ("data-src", "data-lazy-src", "src", "data-original"):
        value = node.get(key)
        if value:
            return urljoin(SOURCE_URL, value.strip())
    return ""


def scrape():
    response = requests.get(SOURCE_URL, headers=HEADERS, timeout=(12, 30))
    response.raise_for_status()
    if len(response.text) < 1000:
        raise RuntimeError(f"Source response unexpectedly short ({len(response.text)} chars)")
    soup = BeautifulSoup(response.text, "html.parser")
    cards = soup.select("div.AY_Match")
    if not cards:
        raise RuntimeError("No match cards found; source markup may have changed or access was blocked")

    matches = []
    for card in cards:
        home = first_text(card, [".TM1 .TM_Name", ".TM1 .team-name", ".TM1"])
        away = first_text(card, [".TM2 .TM_Name", ".TM2 .team-name", ".TM2"])
        time = first_text(card, [".MT_Time", ".time"])
        status = first_text(card, [".MT_Stat", ".match-status", ".status"])
        goals = card.select(".RS-goals")
        score = "-".join(clean(g) for g in goals[:2]) if len(goals) >= 2 else ""
        info = [clean(n) for n in card.select(".MT_Info span") if clean(n)]
        link_node = card.select_one("a[href]")
        link = urljoin(SOURCE_URL, link_node.get("href", "")) if link_node else ""
        # Avoid adding empty layout fragments as matches.
        if not home and not away:
            continue
        matches.append({
            "team1": home,
            "team1_img": first_image(card, ".TM1 img"),
            "team2": away,
            "team2_img": first_image(card, ".TM2 img"),
            "time": time,
            "score": score,
            "status": status,
            "channel": info[0] if len(info) > 0 else "",
            "commentator": info[1] if len(info) > 1 else "",
            "league": info[2] if len(info) > 2 else "",
            "match_link": link,
            "debug_info": info,
        })
    if not matches:
        raise RuntimeError("Match cards were present but no usable team names were extracted")
    return {
        "success": True,
        "count": len(matches),
        "source": SOURCE_URL,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "matches": matches,
    }


def main():
    data = scrape()
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    # Atomic replacement; only replace the last good data after successful scrape.
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=OUTPUT.parent, delete=False) as tmp:
        tmp.write(payload)
        temp_name = tmp.name
    os.replace(temp_name, OUTPUT)
    print(f"Saved {data['count']} matches to {OUTPUT}; updated_at={data['updated_at']}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Update failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
