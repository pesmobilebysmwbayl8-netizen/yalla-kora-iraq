#!/usr/bin/env python3
# YALLA KORA - MULTI-SOURCE FIXTURES ENGINE
# Replaces the existing update_matches.py. Keeps the existing matches.json schema.
# Sources: FotMob + ESPN public scoreboards. No channel/commentator scraping.

import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

TZ = ZoneInfo("Asia/Baghdad")
NOW = datetime.now(TZ)
DATES = [NOW.date() + timedelta(days=i) for i in (-1, 0, 1)]
OUTPUT = Path("matches.json")
TIMEOUT = 20

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 Chrome/130.0 Mobile Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "ar,en-US;q=0.9",
}

# ESPN competition identifiers. Unsupported competitions are skipped automatically.
ESPN_LEAGUES = [
    "eng.1", "eng.2", "eng.3", "eng.4",
    "esp.1", "esp.2", "ger.1", "ger.2",
    "ita.1", "ita.2", "fra.1", "fra.2",
    "ned.1", "por.1", "bel.1", "tur.1",
    "sco.1", "usa.1", "mex.1", "arg.1",
    "bra.1", "aus.1", "ksa.1", "qat.1",
    "irn.1", "jpn.1", "kor.1", "uefa.champions",
    "uefa.europa", "uefa.nations", "fifa.world",
]

session = requests.Session()
session.headers.update(HEADERS)
SOURCE_COUNTS = {"fotmob": 0, "espn": 0, "errors": []}


def clean(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def parse_datetime(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(TZ)
    except (ValueError, TypeError):
        return None


def default_record(home, away, league, kickoff, home_img="", away_img="",
                   status="upcoming", score="VS"):
    return {
        "league": clean(league) or "كرة القدم",
        "home": clean(home),
        "away": clean(away),
        "team1": clean(home),
        "team2": clean(away),
        "home_img": clean(home_img),
        "away_img": clean(away_img),
        "hour": kickoff.strftime("%H:%M"),
        "time": kickoff.strftime("%H:%M"),
        "date": kickoff.date().isoformat(),
        "match_date": kickoff.date().isoformat(),
        "status": status,
        "score": score or "VS",
        "channel": "",
        "commentator": "",
        "streamUrl": "",
    }


def map_status(status_text, home_score=None, away_score=None, completed=False):
    text = clean(status_text).lower()
    if completed or any(x in text for x in ("final", "full time", "ft", "ended")):
        return "ended"
    if any(x in text for x in ("in progress", "live", "half", "1st", "2nd", "period")):
        return "live"
    return "upcoming"


def fetch_json(url, params=None):
    response = session.get(url, params=params, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


def fetch_fotmob(day):
    # FotMob returns grouped league/match data for the requested calendar date.
    url = "https://www.fotmob.com/api/matches"
    payload = fetch_json(url, params={"date": day.strftime("%Y%m%d"), "ccode3": "IRQ"})
    found = []

    for league in payload.get("leagues", []):
        league_name = clean(league.get("name") or league.get("title"))
        for match in league.get("matches", []):
            home = match.get("home") or {}
            away = match.get("away") or {}
            kickoff = parse_datetime(
                match.get("status", {}).get("utcTime")
                or match.get("utcTime")
                or match.get("kickoff")
            )
            if not kickoff:
                continue

            home_name = clean(home.get("name") or home.get("shortName"))
            away_name = clean(away.get("name") or away.get("shortName"))
            if not home_name or not away_name:
                continue

            status_obj = match.get("status") or {}
            status = map_status(
                status_obj.get("reason") or status_obj.get("description"),
                completed=status_obj.get("finished", False),
            )
            score = "VS"
            hs = home.get("score")
            aws = away.get("score")
            if hs is not None and aws is not None:
                score = f"{hs} - {aws}"

            record = default_record(
                home_name, away_name, league_name, kickoff,
                home.get("id") and f"https://images.fotmob.com/image_resources/logo/teamlogo/{home['id']}.png" or "",
                away.get("id") and f"https://images.fotmob.com/image_resources/logo/teamlogo/{away['id']}.png" or "",
                status, score
            )
            found.append(record)

    return found


def fetch_espn(day, league_id):
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league_id}/scoreboard"
    payload = fetch_json(url, params={"dates": day.strftime("%Y%m%d"), "limit": 500})
    found = []

    for event in payload.get("events", []):
        kickoff = parse_datetime(event.get("date"))
        if not kickoff:
            continue

        competitions = event.get("competitions") or []
        comp = competitions[0] if competitions else {}
        competitors = comp.get("competitors") or []
        home = next((x for x in competitors if x.get("homeAway") == "home"), None)
        away = next((x for x in competitors if x.get("homeAway") == "away"), None)
        if not home and len(competitors) >= 2:
            home, away = competitors[0], competitors[1]
        if not home or not away:
            continue

        home_team = home.get("team") or {}
        away_team = away.get("team") or {}
        home_name = clean(home_team.get("displayName") or home_team.get("name"))
        away_name = clean(away_team.get("displayName") or away_team.get("name"))
        if not home_name or not away_name:
            continue

        league_name = clean(
            (payload.get("leagues") or [{}])[0].get("name")
            or event.get("name")
            or league_id
        )
        status_info = (comp.get("status") or {}).get("type") or {}
        state = clean(status_info.get("state") or status_info.get("description"))
        completed = bool(status_info.get("completed"))
        status = map_status(state, completed=completed)

        score = "VS"
        hs, aws = home.get("score"), away.get("score")
        if hs not in (None, "") and aws not in (None, ""):
            score = f"{hs} - {aws}"

        record = default_record(
            home_name, away_name, league_name, kickoff,
            (home_team.get("logo") or ""),
            (away_team.get("logo") or ""),
            status, score
        )
        found.append(record)

    return found


def match_key(item):
    def norm(s):
        s = clean(s).lower()
        s = re.sub(r"[^a-z0-9\u0600-\u06ff]", "", s)
        return s
    return (
        item.get("date", ""),
        norm(item.get("home", "")),
        norm(item.get("away", "")),
    )


def load_existing():
    if not OUTPUT.exists():
        return {}
    try:
        data = json.loads(OUTPUT.read_text(encoding="utf-8"))
        rows = data.get("matches", []) if isinstance(data, dict) else data
        return {match_key(x): x for x in rows if isinstance(x, dict)}
    except Exception as exc:
        print("WARNING: could not read existing matches.json:", exc)
        return {}


def merge_records(records, old_records):
    merged = {}
    for item in records:
        key = match_key(item)
        if not key[1] or not key[2]:
            continue
        if key not in merged:
            merged[key] = item
        else:
            current = merged[key]
            # Prefer richer non-empty data without replacing valid fixture details.
            for field in ("league", "home_img", "away_img"):
                if (not current.get(field) or current.get(field) == "كرة القدم") and item.get(field):
                    current[field] = item[field]
            if current.get("status") != "live" and item.get("status") == "live":
                current["status"] = "live"
            if item.get("score") not in ("", "VS", None):
                current["score"] = item["score"]

    # Preserve app-specific channel/stream metadata from the previous JSON.
    for key, item in merged.items():
        old = old_records.get(key)
        if old:
            for field in ("channel", "commentator", "streamUrl", "home_img", "away_img"):
                if old.get(field) and not item.get(field):
                    item[field] = old[field]
            if item.get("status") == "upcoming" and old.get("status") in ("live", "ended"):
                item["status"] = old["status"]
            if item.get("score") == "VS" and old.get("score") not in ("", "VS", None):
                item["score"] = old["score"]

    return sorted(merged.values(), key=lambda x: (x["date"], x["hour"], x["home"]))


def main():
    print("YALLA KORA MULTI-SOURCE FIXTURES")
    print("Baghdad time:", NOW.isoformat())

    old_records = load_existing()
    collected = []

    # FotMob is queried once per target date.
    for day in DATES:
        try:
            rows = fetch_fotmob(day)
            SOURCE_COUNTS["fotmob"] += len(rows)
            collected.extend(rows)
            print(f"FotMob {day}: {len(rows)}")
        except Exception as exc:
            SOURCE_COUNTS["errors"].append(f"FotMob {day}: {exc}")
            print(f"FotMob ERROR {day}: {exc}")

    # ESPN sources are independent: one failing competition won't stop others.
    for day in DATES:
        for league_id in ESPN_LEAGUES:
            try:
                rows = fetch_espn(day, league_id)
                SOURCE_COUNTS["espn"] += len(rows)
                collected.extend(rows)
            except Exception as exc:
                # Unsupported league IDs commonly return 404; keep log concise.
                if len(SOURCE_COUNTS["errors"]) < 30:
                    SOURCE_COUNTS["errors"].append(f"ESPN {league_id} {day}: {exc}")
            time.sleep(0.08)

    allowed_dates = {d.isoformat() for d in DATES}
    collected = [x for x in collected if x.get("date") in allowed_dates]
    matches = merge_records(collected, old_records)

    # Safety: never replace a working schedule with an empty/failed extraction.
    if not matches:
        raise RuntimeError(
            "All schedule sources returned zero usable matches. "
            "Existing matches.json was left unchanged."
        )

    result = {
        "version": "V20-MULTI-SOURCE",
        "updated_at": datetime.now(TZ).isoformat(),
        "timezone": "Asia/Baghdad",
        "matches": matches,
        "counts": {
            "total": len(matches),
            "today": sum(x["date"] == NOW.date().isoformat() for x in matches),
            "yesterday": sum(x["date"] == (NOW.date() - timedelta(days=1)).isoformat() for x in matches),
            "tomorrow": sum(x["date"] == (NOW.date() + timedelta(days=1)).isoformat() for x in matches),
            "with_channel": sum(bool(x.get("channel")) for x in matches),
            "with_commentator": sum(bool(x.get("commentator")) for x in matches),
            "with_home_image": sum(bool(x.get("home_img")) for x in matches),
            "with_away_image": sum(bool(x.get("away_img")) for x in matches),
        },
        "sources": {
            **SOURCE_COUNTS,
            "unique_matches": len(matches),
        },
    }

    temp = OUTPUT.with_suffix(".json.tmp")
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(OUTPUT)

    print("\nFINISHED")
    print(json.dumps(result["counts"], ensure_ascii=False, indent=2))
    print("Source totals:", json.dumps(SOURCE_COUNTS, ensure_ascii=False))
    print("Updated:", OUTPUT)


if __name__ == "__main__":
    main()
                    
