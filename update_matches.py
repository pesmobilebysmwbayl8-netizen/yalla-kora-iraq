
#!/usr/bin/env python3
# YALLA KORA - FIXED MULTI-SOURCE ENGINE
# Sources: FotMob + ESPN
# Timezone: Iraq
# Never invent channel or commentator names.

import json
import re
import html
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

TZ = ZoneInfo("Asia/Baghdad")
NOW = datetime.now(TZ)
DAYS = [NOW.date() + timedelta(days=n) for n in (-1, 0, 1)]

OUTPUT = Path("matches.json")
TIMEOUT = 25

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 Chrome/128 Mobile Safari/537.36",
    "Accept": "application/json,text/html,*/*",
    "Accept-Language": "ar,en-US;q=0.9"
})

ESPN_LEAGUES = [
    "eng.1", "eng.2", "esp.1", "ger.1", "ita.1",
    "fra.1", "ned.1", "por.1", "bel.1", "tur.1",
    "sco.1", "usa.1", "mex.1", "arg.1", "bra.1",
    "aus.1", "ksa.1", "uefa.champions",
    "uefa.europa", "uefa.europa.conf",
    "uefa.nations", "fifa.world"
]

TEAM_ALIASES = {
    "الهلال": ["al hilal", "hilal"],
    "النصر": ["al nassr", "al nasr", "nassr"],
    "الاتحاد": ["al ittihad", "ittihad"],
    "الأهلي": ["al ahli", "ahli"],
    "الشباب": ["al shabab", "shabab"],
    "القادسية": ["al qadsiah", "qadsiah"],
    "العين": ["al ain"],
    "السد": ["al sadd", "sadd"],
    "الدحيل": ["al duhail", "duhail"],
    "الريان": ["al rayyan", "rayyan"],
    "الغرافة": ["al gharafa", "gharafa"],
    "الشرطة": ["al shorta", "al shurta", "shorta"],
    "القوة الجوية": ["al quwa al jawiya", "air force"],
    "الزوراء": ["al zawraa", "zawraa"],
    "الطلبة": ["al talab", "talaba"],
    "أربيل": ["erbil", "arbil"],
    "دهوك": ["duhok", "dohuk"],
    "برشلونة": ["barcelona", "fc barcelona"],
    "ريال مدريد": ["real madrid"],
    "أتلتيكو مدريد": ["atletico madrid"],
    "مانشستر سيتي": ["manchester city", "man city"],
    "مانشستر يونايتد": ["manchester united", "man utd"],
    "ليفربول": ["liverpool"],
    "أرسنال": ["arsenal"],
    "تشيلسي": ["chelsea"],
    "توتنهام": ["tottenham"],
    "بايرن ميونخ": ["bayern munich", "bayern"],
    "بوروسيا دورتموند": ["borussia dortmund", "dortmund"],
    "باريس سان جيرمان": ["paris saint germain", "psg"],
    "يوفنتوس": ["juventus"],
    "إنتر": ["inter milan", "internazionale"],
    "ميلان": ["ac milan", "milan"],
    "روما": ["as roma"],
    "نابولي": ["napoli"],
    "أياكس": ["ajax"],
    "بنفيكا": ["benfica"],
    "بورتو": ["porto"],
    "منتخب العراق": ["iraq", "iraq national team"],
    "منتخب السعودية": ["saudi arabia"],
    "منتخب قطر": ["qatar"],
    "منتخب الإمارات": ["uae", "united arab emirates"],
    "منتخب مصر": ["egypt"],
    "منتخب المغرب": ["morocco"],
    "منتخب الجزائر": ["algeria"],
    "منتخب تونس": ["tunisia"],
    "منتخب الأردن": ["jordan"],
    "منتخب اليابان": ["japan"],
    "منتخب كوريا الجنوبية": ["south korea"],
    "منتخب البرازيل": ["brazil"],
    "منتخب الأرجنتين": ["argentina"],
    "منتخب فرنسا": ["france"],
    "منتخب إنجلترا": ["england"],
    "منتخب إسبانيا": ["spain"],
    "منتخب ألمانيا": ["germany"],
    "منتخب البرتغال": ["portugal"],
    "منتخب هولندا": ["netherlands", "holland"],
    "منتخب إيطاليا": ["italy"],
    "منتخب إيران": ["iran"],
    "منتخب الكويت": ["kuwait"],
    "منتخب البحرين": ["bahrain"],
    "منتخب سوريا": ["syria"],
    "منتخب فلسطين": ["palestine"],
    "منتخب لبنان": ["lebanon"],
    "منتخب أوزبكستان": ["uzbekistan"]
}

LEAGUE_NAMES = [
    (["premier league"], "الدوري الإنجليزي الممتاز"),
    (["la liga", "laliga"], "الدوري الإسباني"),
    (["bundesliga"], "الدوري الألماني"),
    (["serie a"], "الدوري الإيطالي"),
    (["ligue 1"], "الدوري الفرنسي"),
    (["eredivisie"], "الدوري الهولندي"),
    (["champions league"], "دوري أبطال أوروبا"),
    (["europa league"], "الدوري الأوروبي"),
    (["conference league"], "دوري المؤتمر الأوروبي"),
    (["saudi pro league", "saudi league"], "الدوري السعودي"),
    (["iraqi stars league", "iraq stars league"], "دوري نجوم العراق"),
    (["iraqi premier"], "الدوري العراقي"),
    (["qatar stars league"], "الدوري القطري"),
    (["egyptian premier"], "الدوري المصري"),
    (["world cup"], "كأس العالم"),
    (["friendly", "friendlies"], "مباريات ودية")
]

STATS = {
    "fotmob": 0,
    "espn": 0,
    "errors": [],
    "total": 0,
    "with_channel": 0,
    "with_commentator": 0
}


def clean(value):
    return re.sub(
        r"\s+", " ",
        html.unescape(str(value or ""))
    ).strip(" \t\r\n|•·")


def norm(value):
    value = clean(value).lower()

    # Fixed Arabic normalization: dictionary avoids unequal-length error.
    value = value.translate(str.maketrans({
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ى": "ي",
        "ة": "ه"
    }))

    value = re.sub(r"[ًٌٍَُِّْـ]", "", value)
    return re.sub(r"[^a-z0-9\u0600-\u06ff]", "", value)


ALIAS_TO_AR = {}

for arabic, aliases in TEAM_ALIASES.items():
    ALIAS_TO_AR[norm(arabic)] = arabic
    for alias in aliases:
        ALIAS_TO_AR[norm(alias)] = arabic


def canonical_team(name):
    return ALIAS_TO_AR.get(norm(name), clean(name))


def arabic_league(name):
    low = clean(name).lower()
    for keys, arabic in LEAGUE_NAMES:
        if any(key in low for key in keys):
            return arabic
    return clean(name)


def request_json(url, params=None):
    response = SESSION.get(
        url, params=params, timeout=TIMEOUT
    )
    response.raise_for_status()
    return response.json()


def parse_datetime(value):
    try:
        dt = datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(TZ)
    except Exception:
        return None


def get_status(description="", state="", completed=False):
    value = (clean(description) + " " + clean(state)).lower()

    if completed or any(x in value for x in (
        "final", "full time", "ended", "finished", "انتهت"
    )):
        return "ended"

    if any(x in value for x in (
        "in progress", "live", "half", "مباشر", "استراحة"
    )):
        return "live"

    return "upcoming"


def make_match(
    home, away, league, kickoff,
    status="upcoming", score="VS",
    home_img="", away_img="", source=""
):
    home_ar = canonical_team(home)
    away_ar = canonical_team(away)

    return {
        "league": arabic_league(league),
        "home": home_ar,
        "away": away_ar,
        "team1": home_ar,
        "team2": away_ar,
        "home_img": clean(home_img),
        "away_img": clean(away_img),
        "hour": kickoff.strftime("%H:%M"),
        "time": kickoff.strftime("%H:%M"),
        "date": kickoff.date().isoformat(),
        "match_date": kickoff.date().isoformat(),
        "status": status,
        "score": clean(score) or "VS",
        "channel": "",
        "channels": [],
        "commentator": "",
        "commentators": [],
        "streamUrl": "",
        "sources": [source] if source else []
    }


def fetch_fotmob(day):
    data = request_json(
        "https://www.fotmob.com/api/data/matches",
        {
            "date": day.strftime("%Y%m%d"),
            "ccode3": "IRQ"
        }
    )

    output = []

    for league in data.get("leagues", []):
        for match in league.get("matches", []):
            home = match.get("home") or {}
            away = match.get("away") or {}
            status_data = match.get("status") or {}

            kickoff = parse_datetime(
                status_data.get("utcTime")
                or match.get("utcTime")
                or match.get("kickoff")
            )

            home_name = home.get("name") or home.get("shortName")
            away_name = away.get("name") or away.get("shortName")

            if not kickoff or not home_name or not away_name:
                continue

            hs = home.get("score")
            aws = away.get("score")

            score = (
                f"{hs} - {aws}"
                if hs is not None and aws is not None
                else "VS"
            )

            home_img = ""
            away_img = ""

            if home.get("id"):
                home_img = (
                    "https://images.fotmob.com/image_resources/"
                    f"logo/teamlogo/{home['id']}.png"
                )

            if away.get("id"):
                away_img = (
                    "https://images.fotmob.com/image_resources/"
                    f"logo/teamlogo/{away['id']}.png"
                )

            output.append(make_match(
                home_name,
                away_name,
                league.get("name") or league.get("title"),
                kickoff,
                get_status(
                    status_data.get("reason") or status_data.get("description"),
                    status_data.get("state"),
                    status_data.get("finished", False)
                ),
                score,
                home_img,
                away_img,
                "fotmob"
            ))

    return output


def fetch_espn(day, league_id):
    url = (
        "https://site.api.espn.com/apis/site/v2/sports/"
        f"soccer/{league_id}/scoreboard"
    )

    data = request_json(url, {
        "dates": day.strftime("%Y%m%d"),
        "limit": 500
    })

    league = (
        (data.get("leagues") or [{}])[0].get("name")
        or league_id
    )

    output = []

    for event in data.get("events", []):
        kickoff = parse_datetime(event.get("date"))
        competitions = event.get("competitions") or []
        competition = competitions[0] if competitions else {}
        teams = competition.get("competitors") or []

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

        home_name = ht.get("displayName") or ht.get("name")
        away_name = at.get("displayName") or at.get("name")

        if not home_name or not away_name:
            continue

        status_data = (
            competition.get("status")
            or event.get("status")
            or {}
        )
        status_type = status_data.get("type") or {}

        hs = home.get("score")
        aws = away.get("score")

        score = (
            f"{hs} - {aws}"
            if hs not in (None, "") and aws not in (None, "")
            else "VS"
        )

        output.append(make_match(
            home_name,
            away_name,
            league,
            kickoff,
            get_status(
                status_type.get("description"),
                status_type.get("state"),
                status_type.get("completed", False)
            ),
            score,
            ht.get("logo", ""),
            at.get("logo", ""),
            "espn"
        ))

    return output


def match_key(match):
    return (
        match.get("date", ""),
        norm(match.get("home", "")),
        norm(match.get("away", ""))
    )


def preserve_old_metadata(matches):
    if not OUTPUT.exists():
        return

    try:
        old_data = json.loads(OUTPUT.read_text(encoding="utf-8"))
        if not isinstance(old_data, list):
            return

        old_map = {
            match_key(item): item
            for item in old_data
            if isinstance(item, dict)
        }

        for match in matches:
            old = old_map.get(match_key(match))
            if not old:
                continue

            # Keep previously collected broadcast information.
            for field in (
                "channel", "channels",
                "commentator", "commentators",
                "streamUrl"
            ):
                value = old.get(field)
                if value:
                    match[field] = value

    except Exception as exc:
        STATS["errors"].append(
            "Old metadata preservation: " + str(exc)
        )


def main():
    all_matches = []
    seen = set()

    print("=" * 60)
    print("YALLA KORA - FIXED ENGINE")
    print("Timezone:", str(TZ))
    print("=" * 60)

    for day in DAYS:
        print("\nFetching:", day.isoformat())

        try:
            fixtures = fetch_fotmob(day)
            STATS["fotmob"] += len(fixtures)
            all_matches.extend(fixtures)
            print("FotMob:", len(fixtures))
        except Exception as exc:
            STATS["errors"].append(
                f"FotMob {day}: {exc}"
            )
            print("FotMob error:", exc)

        for league_id in ESPN_LEAGUES:
            try:
                fixtures = fetch_espn(day, league_id)
                STATS["espn"] += len(fixtures)
                all_matches.extend(fixtures)
            except Exception as exc:
                STATS["errors"].append(
                    f"ESPN {league_id} {day}: {exc}"
                )

    # Keep only requested dates and remove duplicate fixtures.
    unique = []

    for match in all_matches:
        if match["date"] not in {
            d.isoformat() for d in DAYS
        }:
            continue

        key = match_key(match)
        if key in seen:
            continue

        seen.add(key)
        unique.append(match)

    preserve_old_metadata(unique)

    unique.sort(key=lambda x: (
        x.get("date", ""),
        x.get("hour", "")
    ))

    STATS["total"] = len(unique)
    STATS["with_channel"] = sum(
        bool(x.get("channel") or x.get("channels"))
        for x in unique
    )
    STATS["with_commentator"] = sum(
        bool(x.get("commentator") or x.get("commentators"))
        for x in unique
    )

    OUTPUT.write_text(
        json.dumps(
            unique,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    print("\n========== DONE ==========")
    print("Total:", STATS["total"])
    print("FotMob:", STATS["fotmob"])
    print("ESPN:", STATS["espn"])
    print("With channel:", STATS["with_channel"])
    print("With commentator:", STATS["with_commentator"])
    print("Errors:", len(STATS["errors"]))

    for error in STATS["errors"][:15]:
        print("ERROR:", error)

    print("Saved:", OUTPUT)


if __name__ == "__main__":
    main()
