
#!/usr/bin/env python3
# YALLA KORA V23 - BROADCAST + COMMENTATOR ENGINE
# Keeps existing matches.json structure.
# Channels and commentators are matched per event.
# Missing information stays empty; never guessed.

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
DATE_SET = {d.isoformat() for d in DATES}

OUTPUT = Path("matches.json")
TIMEOUT = 25

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 Chrome/130.0.0.0 Mobile Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "ar,en-US;q=0.9",
}

ESPN_LEAGUES = [
    "eng.1", "eng.2", "eng.3", "esp.1", "ger.1",
    "ita.1", "fra.1", "ned.1", "por.1", "bel.1",
    "tur.1", "sco.1", "usa.1", "mex.1", "arg.1",
    "bra.1", "aus.1", "ksa.1", "uefa.champions",
    "uefa.europa", "uefa.europa.conf",
    "uefa.nations", "fifa.world", "fifa.friendly",
]

session = requests.Session()
session.headers.update(HEADERS)

STATS = {
    "espn": {"ok": 0, "failed": 0},
    "fotmob": {"ok": 0, "failed": 0},
    "broadcast": {"checked": 0, "found": 0},
    "commentators": {"checked": 0, "found": 0},
    "errors": [],
}


def clean(v):
    return re.sub(r"\s+", " ", str(v or "")).strip(" \t\r\n|•·")


def norm(v):
    s = clean(v).lower()
    s = s.replace("أ", "ا").replace("إ", "ا")
    s = s.replace("آ", "ا").replace("ى", "ي")
    s = s.replace("ة", "ه")
    return re.sub(r"[^a-z0-9\u0600-\u06ff]", "", s)


def unique(values):
    out = []
    seen = set()

    for v in values or []:
        v = clean(v)
        k = norm(v)

        if v and k and k not in seen:
            seen.add(k)
            out.append(v)

    return out


def parse_dt(v):
    if not v:
        return None

    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))

        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)

        return d.astimezone(TZ)

    except (TypeError, ValueError):
        return None


def get_json(url, params=None):
    r = session.get(url, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def recursive_values(obj, keys):
    found = []

    if isinstance(obj, dict):
        for k in keys:
            v = obj.get(k)

            if isinstance(v, str):
                found.append(v)

            elif isinstance(v, dict):
                for name in ("name", "displayName", "title"):
                    if v.get(name):
                        found.append(v[name])

            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, str):
                        found.append(item)

                    elif isinstance(item, dict):
                        for name in ("name", "displayName", "title"):
                            if item.get(name):
                                found.append(item[name])

        for value in obj.values():
            if isinstance(value, (dict, list)):
                found.extend(recursive_values(value, keys))

    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, (dict, list)):
                found.extend(recursive_values(item, keys))

    return unique(found)


def match_status(raw="", completed=False, state=""):
    t = (clean(raw) + " " + clean(state)).lower()

    if completed or state.lower() == "post":
        return "ended"

    if any(x in t for x in (
        "final", "full time", "ended", "finished",
        "انتهت"
    )):
        return "ended"

    if state.lower() == "in" or any(x in t for x in (
        "in progress", "live", "half", "مباشر",
        "استراحة", "جارية"
    )):
        return "live"

    return "upcoming"


def make_row(
    home, away, league, kickoff,
    status="upcoming", score="VS",
    home_img="", away_img="",
    channels=None, commentators=None,
    event_id=""
):
    channels = unique(channels or [])
    commentators = unique(commentators or [])

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
        "score": clean(score) or "VS",
        "channel": " | ".join(channels),
        "channels": channels,
        "commentator": " | ".join(commentators),
        "commentators": commentators,
        "streamUrl": "",
        "_event_id": str(event_id or "")
    }


def parse_espn(day, league_id):
    url = (
        "https://site.api.espn.com/apis/site/v2/"
        f"sports/soccer/{league_id}/scoreboard"
    )

    data = get_json(url, {
        "dates": day.strftime("%Y%m%d"),
        "limit": 500
    })

    rows = []
    league_name = (
        (data.get("leagues") or [{}])[0].get("name")
        or league_id
    )

    for event in data.get("events", []):
        kickoff = parse_dt(event.get("date"))
        competitions = event.get("competitions") or []
        comp = competitions[0] if competitions else {}

        teams = comp.get("competitors") or []

        home = next(
            (x for x in teams if x.get("homeAway") == "home"),
            None
        )

        away = next(
            (x for x in teams if x.get("homeAway") == "away"),
            None
        )

        if (not home or not away) and len(teams) >= 2:
            home, away = teams[0], teams[1]

        if not kickoff or not home or not away:
            continue

        ht = home.get("team") or {}
        at = away.get("team") or {}

        hn = clean(ht.get("displayName") or ht.get("name"))
        an = clean(at.get("displayName") or at.get("name"))

        if not hn or not an:
            continue

        state = comp.get("status") or event.get("status") or {}
        typ = state.get("type") or {}

        hs = home.get("score")
        aws = away.get("score")

        score = (
            f"{hs} - {aws}"
            if hs not in (None, "") and aws not in (None, "")
            else "VS"
        )

        # Only explicitly provided broadcast metadata.
        channels = recursive_values(
            comp,
            ("channel", "channels", "broadcast", "broadcasters")
        )

        commentators = recursive_values(
            comp,
            ("commentator", "commentators", "commentary")
        )

        rows.append(make_row(
            hn,
            an,
            league_name,
            kickoff,
            match_status(
                typ.get("description"),
                typ.get("completed", False),
                typ.get("state", "")
            ),
            score,
            ht.get("logo", ""),
            at.get("logo", ""),
            channels,
            commentators,
            event.get("id", "")
        ))

    return rows


def parse_fotmob(day):
    # Current API route is attempted first.
    urls = [
        "https://www.fotmob.com/api/data/matches",
        "https://www.fotmob.com/api/matches",
    ]

    data = None

    for url in urls:
        try:
            data = get_json(url, {
                "date": day.strftime("%Y%m%d"),
                "ccode3": "IRQ"
            })
            break
        except Exception:
            continue

    if not isinstance(data, dict):
        raise RuntimeError("FotMob match endpoint unavailable")

    rows = []

    for league in data.get("leagues", []):
        for m in league.get("matches", []):
            h = m.get("home") or {}
            a = m.get("away") or {}
            s = m.get("status") or {}

            kickoff = parse_dt(
                s.get("utcTime")
                or m.get("utcTime")
                or m.get("kickoff")
            )

            hn = clean(h.get("name") or h.get("shortName"))
            an = clean(a.get("name") or a.get("shortName"))

            if not kickoff or not hn or not an:
                continue

            hs = h.get("score")
            aws = a.get("score")

            score = (
                f"{hs} - {aws}"
                if hs is not None and aws is not None
                else "VS"
            )

            channels = recursive_values(
                m,
                ("channel", "channels", "tv", "broadcaster", "broadcasters")
            )

            commentators = recursive_values(
                m,
                ("commentator", "commentators", "commentary")
            )

            rows.append(make_row(
                hn,
                an,
                league.get("name") or league.get("title"),
                kickoff,
                match_status(
                    s.get("reason") or s.get("description"),
                    s.get("finished", False),
                    s.get("state", "")
                ),
                score,
                (
                    "https://images.fotmob.com/image_resources/"
                    f"logo/teamlogo/{h.get('id')}.png"
                    if h.get("id") else ""
                ),
                (
                    "https://images.fotmob.com/image_resources/"
                    f"logo/teamlogo/{a.get('id')}.png"
                    if a.get("id") else ""
                ),
                channels,
                commentators,
                m.get("id", "")
            ))

    return rows


def event_details(event_id):
    """
    Fetch ESPN event details.
    Only use metadata returned for this exact event.
    """
    if not event_id:
        return [], []

    url = (
        "https://site.api.espn.com/apis/site/v2/"
        f"sports/soccer/all/summary?event={event_id}"
    )

    try:
        data = get_json(url)

        channels = recursive_values(
            data,
            ("channel", "channels", "broadcast", "broadcasters")
        )

        commentators = recursive_values(
            data,
            ("commentator", "commentators", "commentary")
        )

        return channels, commentators

    except Exception:
        return [], []


def enrich_broadcasts(rows):
    """
    Event-specific enrichment.
    Never copy metadata between different matches.
    """
    for row in rows:
        event_id = row.get("_event_id", "")

        if not event_id:
            continue

        STATS["broadcast"]["checked"] += 1

        channels, commentators = event_details(event_id)

        if channels:
            row["channels"] = unique(
                row.get("channels", []) + channels
            )
            row["channel"] = " | ".join(row["channels"])
            STATS["broadcast"]["found"] += 1

        if commentators:
            row["commentators"] = unique(
                row.get("commentators", []) + commentators
            )
            row["commentator"] = " | ".join(row["commentators"])
            STATS["commentators"]["found"] += 1

        time.sleep(0.05)


def key(row):
    return (
        clean(row.get("date") or row.get("match_date")),
        norm(row.get("home") or row.get("team1")),
        norm(row.get("away") or row.get("team2"))
    )


def load_old():
    if not OUTPUT.exists():
        return {}

    try:
        data = json.loads(
            OUTPUT.read_text(encoding="utf-8")
        )

        rows = data.get("matches", []) if isinstance(data, dict) else data

        return {
            key(x): x
            for x in rows
            if isinstance(x, dict)
            and key(x)[1]
            and key(x)[2]
        }

    except Exception as e:
        print("WARNING: previous JSON unreadable:", e)
        return {}


def merge(fresh, old):
    merged = {
        k: dict(v)
        for k, v in old.items()
        if k[0] in DATE_SET
    }

    for row in fresh:
        k = key(row)

        if k[0] not in DATE_SET or not k[1] or not k[2]:
            continue

        previous = merged.get(k) or old.get(k) or {}

        item = dict(previous)
        item.update(row)

        for field in ("streamUrl", "home_img", "away_img"):
            if previous.get(field) and not row.get(field):
                item[field] = previous[field]

        old_channels = previous.get("channels") or (
            [previous["channel"]] if previous.get("channel") else []
        )

        old_commentators = previous.get("commentators") or (
            [previous["commentator"]]
            if previous.get("commentator") else []
        )

        item["channels"] = unique(
            (row.get("channels") or []) + old_channels
        )

        item["commentators"] = unique(
            (row.get("commentators") or []) + old_commentators
        )

        item["channel"] = " | ".join(item["channels"])
        item["commentator"] = " | ".join(item["commentators"])

        if (
            row.get("status") == "upcoming"
            and previous.get("status") in ("live", "ended")
        ):
            item["status"] = previous["status"]

        if (
            row.get("score") in ("", "VS", None)
            and previous.get("score") not in ("", "VS", None)
        ):
            item["score"] = previous["score"]

        item["team1"] = item.get("home", item.get("team1", ""))
        item["team2"] = item.get("away", item.get("team2", ""))
        item["time"] = item.get("hour", item.get("time", ""))
        item["match_date"] = item.get("date", item.get("match_date", ""))

        merged[k] = item

    return sorted(
        merged.values(),
        key=lambda x: (
            clean(x.get("date")),
            clean(x.get("hour")),
            clean(x.get("home"))
        )
    )


def main():
    print("YALLA KORA V23")
    print("Timezone:", NOW.isoformat())

    old = load_old()
    fresh = []

    for day in DATES:
        for league_id in ESPN_LEAGUES:
            try:
                got = parse_espn(day, league_id)
                fresh.extend(got)
                STATS["espn"]["ok"] += len(got)

            except Exception as e:
                STATS["espn"]["failed"] += 1

                if len(STATS["errors"]) < 30:
                    STATS["errors"].append(
                        f"ESPN {league_id} {day}: {e}"
                    )

            time.sleep(0.04)

        try:
            got = parse_fotmob(day)
            fresh.extend(got)
            STATS["fotmob"]["ok"] += len(got)

        except Exception as e:
            STATS["fotmob"]["failed"] += 1
            STATS["errors"].append(
                f"FotMob {day}: {e}"
            )

    # Enrich only when a source returns event-specific metadata.
    enrich_broadcasts(fresh)

    rows = merge(fresh, old)

    if not rows:
        raise RuntimeError(
            "No fixtures found. Existing matches.json was not changed."
        )

    for x in rows:
        x.pop("_event_id", None)

        x.setdefault("team1", x.get("home", ""))
        x.setdefault("team2", x.get("away", ""))
        x.setdefault("time", x.get("hour", ""))
        x.setdefault("match_date", x.get("date", ""))

        x["channels"] = unique(
            x.get("channels") or (
                [x["channel"]] if x.get("channel") else []
            )
        )

        x["commentators"] = unique(
            x.get("commentators") or (
                [x["commentator"]]
                if x.get("commentator") else []
            )
        )

        x["channel"] = " | ".join(x["channels"])
        x["commentator"] = " | ".join(x["commentators"])
        x.setdefault("streamUrl", "")

    today = NOW.date().isoformat()

    result = {
        "version": "V23-BROADCAST-COMMENTATOR",
        "updated_at": datetime.now(TZ).isoformat(),
        "timezone": "Asia/Baghdad",
        "matches": rows,
        "counts": {
            "total": len(rows),
            "today": sum(x.get("date") == today for x in rows),
            "yesterday": sum(
                x.get("date") == (
                    NOW.date() - timedelta(days=1)
                ).isoformat()
                for x in rows
            ),
            "tomorrow": sum(
                x.get("date") == (
                    NOW.date() + timedelta(days=1)
                ).isoformat()
                for x in rows
            ),
            "with_channel": sum(
                bool(x.get("channel")) for x in rows
            ),
            "with_commentator": sum(
                bool(x.get("commentator")) for x in rows
            )
        },
        "sources": STATS
    }

    tmp = OUTPUT.with_suffix(".json.tmp")

    tmp.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    tmp.replace(OUTPUT)

    print("DONE:")
    print(json.dumps(result["counts"], ensure_ascii=False))
    print("SOURCE STATS:")
    print(json.dumps(STATS, ensure_ascii=False))


if __name__ == "__main__":
    main()
    
