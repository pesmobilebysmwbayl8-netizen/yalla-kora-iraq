
#!/usr/bin/env python3
"""Fetch today's football matches and save them as stable JSON."""

import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

SOURCE_URL = os.getenv(
    "MATCHES_SOURCE_URL",
    "https://yallashootio.com/matches-todays/"
)
OUTPUT = Path("matches.json")

SOURCE_HOST = (urlparse(SOURCE_URL).hostname or "").lower()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/126 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,*/*;q=0.8"
    ),
    "Accept-Language": "ar,en-US;q=0.8,en;q=0.7",
}

# كلمات تشير غالباً إلى رابط قناة أو مشغّل، وليس صفحة المباراة.
PLAYER_HINTS = (
    "stream", "player", "watch", "embed",
    "ssc-", "bein-", "beinsport", "on-time",
    "shahid", "m3u8", "live-tv",
)

MEDIA_EXTENSIONS = (
    ".m3u8", ".mp4", ".mpd", ".ts", ".m4v",
)


def clean(node):
    if not node:
        return ""
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True))


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
        if value and value.strip():
            return urljoin(SOURCE_URL, value.strip())

    return ""


def is_source_url(url):
    """Accept only links hosted on the source website."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()

    return (
        parsed.scheme in ("http", "https")
        and (
            host == SOURCE_HOST
            or host.endswith("." + SOURCE_HOST)
        )
    )


def choose_match_link(card):
    """
    Select a likely match-details page.
    Never substitute an external channel/player URL for a match link.
    """
    candidates = []

    for anchor in card.select("a[href]"):
        href = anchor.get("href", "").strip()
        if not href:
            continue

        url = urljoin(SOURCE_URL, href)
        parsed = urlparse(url)
        path = parsed.path.lower()
        text = clean(anchor).lower()
        hints = (
            f"{path} {text} "
            f"{anchor.get('class', [])} "
            f"{anchor.get('title', '')}"
        ).lower()

        # Ignore external links and direct media URLs.
        if not is_source_url(url):
            continue

        if path.endswith(MEDIA_EXTENSIONS):
            continue

        if any(word in hints for word in PLAYER_HINTS):
            continue

        # Prefer anchors explicitly marked as match/detail links.
        score = 0
        if any(word in hints for word in (
            "match", "details", "fixture", "مباراة", "تفاصيل"
        )):
            score += 3

        # A URL pointing to the schedule page itself isn't a detail page.
        if parsed.path.rstrip("/") == urlparse(SOURCE_URL).path.rstrip("/"):
            continue

        candidates.append((score, url))

    if not candidates:
        return ""

    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def scrape():
    response = requests.get(
        SOURCE_URL,
        headers=HEADERS,
        timeout=(12, 30),
    )
    response.raise_for_status()

    if len(response.text) < 1000:
        raise RuntimeError(
            f"Source response unexpectedly short "
            f"({len(response.text)} chars)"
        )

    soup = BeautifulSoup(response.text, "html.parser")
    cards = soup.select("div.AY_Match")

    if not cards:
        raise RuntimeError(
            "No match cards found; source markup may have changed "
            "or access was blocked"
        )

    matches = []

    for card in cards:
        home = first_text(
            card, [".TM1 .TM_Name", ".TM1 .team-name", ".TM1"]
        )
        away = first_text(
            card, [".TM2 .TM_Name", ".TM2 .team-name", ".TM2"]
        )
        time = first_text(card, [".MT_Time", ".time"])
        status = first_text(
            card, [".MT_Stat", ".match-status", ".status"]
        )

        goals = card.select(".RS-goals")
        score = "-".join(clean(g) for g in goals[:2]) \
            if len(goals) >= 2 else ""

        info = [
            clean(node)
            for node in card.select(".MT_Info span")
            if clean(node)
        ]

        match_link = choose_match_link(card)

        # Skip empty layout fragments.
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
            "match_link": match_link,
            "debug_info": info,
        })

    if not matches:
        raise RuntimeError(
            "Match cards were present but no usable team names "
            "were extracted"
        )

    return {
        "success": True,
        "count": len(matches),
        "source": SOURCE_URL,
        "updated_at": datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ),
        "matches": matches,
    }


def main():
    data = scrape()
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None

    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=OUTPUT.parent,
            delete=False,
        ) as tmp:
            tmp.write(payload)
            temp_name = tmp.name

        # Replace old JSON only after a successful scrape and write.
        os.replace(temp_name, OUTPUT)
        temp_name = None

    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)

    print(
        f"Saved {data['count']} matches to {OUTPUT}; "
        f"updated_at={data['updated_at']}"
    )

    missing_links = sum(
        1 for match in data["matches"] if not match["match_link"]
    )
    if missing_links:
        print(
            f"Notice: {missing_links} matches have no verified "
            "same-site details link."
        )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            f"Update failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)
        
