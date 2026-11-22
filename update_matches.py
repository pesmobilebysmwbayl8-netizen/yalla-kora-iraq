#!/usr/bin/env python3
# Yalla Kora - today's matches only
# Sources: ESPN public scoreboard API + FotMob public matches API
# No stream URLs are collected. Broadcast data is included only when the source provides it.

import json
import re
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

TZ = ZoneInfo("Asia/Baghdad")
NOW = datetime.now(TZ)
TODAY = NOW.strftime("%Y%m%d")
OUT = Path(__file__).resolve().parent / "matches.json"
TIMEOUT = 12

ESPN_LEAGUES = [
    "eng.1", "esp.1", "ger.1", "ita.1", "fra.1",
    "uefa.champions", "uefa.europa", "uefa.europa.conf",
    "ksa.1", "qat.1", "uae.1", "irq.1",
]

LEAGUE_AR = {
    "eng.1": "الدوري الإنجليزي الممتاز",
    "esp.1": "الدوري الإسباني",
    "ger.1": "الدوري الألماني",
    "ita.1": "الدوري الإيطالي",
    "fra.1": "الدوري الفرنسي",
    "uefa.champions": "دوري أبطال أوروبا",
    "uefa.europa": "الدوري الأوروبي",
    "uefa.europa.conf": "دوري المؤتمر الأوروبي",
    "ksa.1": "الدوري السعودي",
    "qat.1": "الدوري القطري",
    "uae.1": "الدوري الإماراتي",
    "irq.1": "دوري نجوم العراق",
}

TEAM_AR = {
    "Manchester City": "مانشستر سيتي", "Manchester United": "مانشستر يونايتد",
    "Liverpool": "ليفربول", "Arsenal": "أرسنال", "Chelsea": "تشيلسي",
    "Tottenham Hotspur": "توتنهام", "Newcastle United": "نيوكاسل",
    "Real Madrid": "ريال مدريد", "Barcelona": "برشلونة", "Atletico Madrid": "أتلتيكو مدريد",
    "Atlético Madrid": "أتلتيكو مدريد", "Sevilla": "إشبيلية", "Girona": "جيرونا",
    "Bayern Munich": "بايرن ميونخ", "Borussia Dortmund": "بوروسيا دورتموند",
    "Bayer Leverkusen": "باير ليفركوزن", "Inter": "إنتر ميلان",
    "Internazionale": "إنتر ميلان", "AC Milan": "ميلان", "Juventus": "يوفنتوس",
    "Napoli": "نابولي", "Roma": "روما", "Lazio": "لاتسيو",
    "Paris Saint-Germain": "باريس سان جيرمان", "PSG": "باريس سان جيرمان",
    "Marseille": "مارسيليا", "Al Hilal": "الهلال", "Al-Nassr": "النصر",
    "Al Nassr": "النصر", "Al Ahli": "الأهلي", "Al-Ittihad": "الاتحاد",
    "Al Ittihad": "الاتحاد", "Al Sadd": "السد", "Al Duhail": "الدحيل",
    "Al Ain": "العين", "Shabab Al Ahli": "شباب الأهلي",
    "Al Wasl": "الوصل", "Al Shorta": "الشرطة", "Al Quwa Al Jawiya": "القوة الجوية",
}

def arabic_team(name):
    name = (name or "").strip()
    if name in TEAM_AR:
        return TEAM_AR[name]
    # Keep source name when no reliable Arabic equivalent is known.
    return name

def get_json(url, params=None):
    try:
        r = requests.get(
            url, params=params, timeout=TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0 (compatible; YallaKora/1.0)"}
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"Source error: {url} -> {e}")
        return None

def parse_status(event):
    comp = (event.get("competitions") or [{}])[0]
    status = (event.get("status") or comp.get("status") or {}).get("type", {})
    state = status.get("state", "")
    if state == "in":
        return "live"
    if state == "post":
        return "ended"
    return "upcoming"

def parse_score(comp):
    scores = []
    for team in comp.get("competitors", []):
        scores.append(str(team.get("score", "")))
    if len(scores) == 2 and all(s != "" for s in scores):
        return f"{scores[0]} - {scores[1]}"
    return ""

def extract_broadcast(comp):
    # ESPN may expose broadcast names in competition.broadcasts.
    names = []
    for b in comp.get("broadcasts", []) or []:
        if isinstance(b, dict):
            name = b.get("names") or b.get("name") or b.get("media")
            if isinstance(name, list):
                names.extend(str(x) for x in name if x)
            elif name:
                names.append(str(name))
        elif b:
            names.append(str(b))
    names = list(dict.fromkeys(n.strip() for n in names if n and n.strip()))
    return names

def espn_fetch():
    rows = []
    for league in ESPN_LEAGUES:
        url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard"
        data = get_json(url, {"dates": TODAY})
        if not data:
            continue
        for event in data.get("events", []):
            comp = (event.get("competitions") or [{}])[0]
            competitors = comp.get("competitors", [])
            home = next((x for x in competitors if x.get("homeAway") == "home"), None)
            away = next((x for x in competitors if x.get("homeAway") == "away"), None)
            if not home or not away:
                continue

            hteam = home.get("team", {})
            ateam = away.get("team", {})
            kickoff = event.get("date") or comp.get("date") or ""
            try:
                dt = datetime.fromisoformat(kickoff.replace("Z", "+00:00")).astimezone(TZ)
                hour = dt.strftime("%I:%M %p").lstrip("0")
                match_date = dt.strftime("%Y-%m-%d")
            except Exception:
                hour, match_date = "", NOW.strftime("%Y-%m-%d")

            channels = extract_broadcast(comp)
            league_name = (event.get("league", {}).get("name")
                           or data.get("leagues", [{}])[0].get("name")
                           or LEAGUE_AR.get(league, league))
            rows.append({
                "league": LEAGUE_AR.get(league, league_name),
                "home": arabic_team(hteam.get("displayName") or hteam.get("name")),
                "away": arabic_team(ateam.get("displayName") or ateam.get("name")),
                "team1": arabic_team(hteam.get("displayName") or hteam.get("name")),
                "team2": arabic_team(ateam.get("displayName") or ateam.get("name")),
                "home_img": hteam.get("logo") or "",
                "away_img": ateam.get("logo") or "",
                "hour": hour,
                "time": hour,
                "date": match_date,
                "match_date": match_date,
                "status": parse_status(event),
                "score": parse_score(comp),
                "channel": channels[0] if channels else "",
                "channels": channels,
                "commentator": "",
                "commentators": [],
                "streamUrl": "",
                "sources": ["ESPN"],
                "_id": event.get("id") or "",
                "_kickoff": kickoff,
            })
    return rows

def fotmob_fetch():
    rows = []
    data = get_json("https://www.fotmob.com/api/matches", {"date": TODAY})
    if not data:
        return rows

    # FotMob response layouts can change; inspect common structures defensively.
    groups = data.get("leagues") or data.get("matches") or []
    if isinstance(groups, dict):
        groups = list(groups.values())
    for group in groups:
        league = group.get("name") or group.get("title") or group.get("leagueName") or ""
        matches = group.get("matches") or group.get("fixtures") or []
        for m in matches:
            h = m.get("home") or m.get("homeTeam") or {}
            a = m.get("away") or m.get("awayTeam") or {}
            if not h or not a:
                continue
            hname = h.get("name") or h.get("title") or ""
            aname = a.get("name") or a.get("title") or ""
            timestamp = m.get("status", {}).get("utcTime") or m.get("utcTime") or m.get("date")
            hour, match_date = "", NOW.strftime("%Y-%m-%d")
            try:
                dt = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00")).astimezone(TZ)
                hour, match_date = dt.strftime("%I:%M %p").lstrip("0"), dt.strftime("%Y-%m-%d")
            except Exception:
                pass
            status_obj = m.get("status") or {}
            if status_obj.get("finished") or m.get("finished"):
                state = "ended"
            elif status_obj.get("started") or m.get("live"):
                state = "live"
            else:
                state = "upcoming"
            score = ""
            hs = m.get("homeScore", h.get("score"))
            aw = m.get("awayScore", a.get("score"))
            if hs is not None and aw is not None:
                score = f"{hs} - {aw}"
            rows.append({
                "league": league,
                "home": arabic_team(hname), "away": arabic_team(aname),
                "team1": arabic_team(hname), "team2": arabic_team(aname),
                "home_img": h.get("image") or h.get("logo") or "",
                "away_img": a.get("image") or a.get("logo") or "",
                "hour": hour, "time": hour, "date": match_date,
                "match_date": match_date, "status": state, "score": score,
                "channel": "", "channels": [],
                "commentator": "", "commentators": [],
                "streamUrl": "", "sources": ["FotMob"],
                "_id": str(m.get("id") or m.get("matchId") or ""),
                "_kickoff": str(timestamp or ""),
            })
    return rows

def dedupe(rows):
    out, seen = [], set()
    for r in rows:
        key = r.get("_id")
        if not key:
            key = "|".join([
                r.get("date", ""), r.get("hour", ""),
                r.get("league", ""), r.get("home", ""), r.get("away", "")
            ])
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out

def main():
    print(f"Yalla Kora updater | Baghdad | {TODAY}")
    rows = []
    rows.extend(espn_fetch())
    rows.extend(fotmob_fetch())
    rows = dedupe(rows)

    # Keep only Baghdad-local today's fixtures.
    today_local = NOW.strftime("%Y-%m-%d")
    rows = [r for r in rows if r.get("date") == today_local]

    if not rows:
        print("No fixtures fetched. Existing matches.json will NOT be overwritten.")
        return

    for r in rows:
        r.pop("_id", None)
        r.pop("_kickoff", None)

    # Preserve existing metadata when present, while replacing fixture list.
    payload = rows
    try:
        old = json.loads(OUT.read_text(encoding="utf-8"))
        if isinstance(old, dict):
            payload = {"matches": rows}
            for k, v in old.items():
                if k != "matches":
                    payload[k] = v
    except Exception:
        pass

    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(OUT)
    print(f"Saved {len(rows)} matches to {OUT}")

if __name__ == "__main__":
    main()
