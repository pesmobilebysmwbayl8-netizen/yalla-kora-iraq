#!/usr/bin/env python3
# YALLA KORA V21 - Arabic + international fixtures and broadcast metadata
# Keeps the existing matches.json schema and adds channels/commentators arrays.
# Sources are independent: a failed source does not stop the others.

import json, re, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

TZ = ZoneInfo("Asia/Baghdad")
NOW = datetime.now(TZ)
DATES = [NOW.date() + timedelta(days=i) for i in (-1, 0, 1)]
OUTPUT = Path("matches.json")
TIMEOUT = 22

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 Chrome/130.0.0.0 Mobile Safari/537.36",
    "Accept": "text/html,application/json,*/*",
    "Accept-Language": "ar,en-US;q=0.9",
}

# Arabic sites first. International feeds are schedule fallbacks.
ARABIC_PAGES = [
    ("Yacine TV", "https://yacine.website/matches"),
    ("YallaKora", "https://yallakora.work/"),
    ("ElGoal", "https://elgoal.net/"),
]
ESPN_LEAGUES = [
    "eng.1","eng.2","eng.3","eng.4","esp.1","esp.2","ger.1","ger.2",
    "ita.1","ita.2","fra.1","fra.2","ned.1","por.1","bel.1","tur.1",
    "sco.1","usa.1","mex.1","arg.1","bra.1","aus.1","ksa.1","qat.1",
    "irn.1","jpn.1","kor.1","uefa.champions","uefa.europa","uefa.nations","fifa.world"
]

session = requests.Session()
session.headers.update(HEADERS)
STATS = {"arabic_pages": {}, "fotmob": 0, "espn": 0, "errors": []}

def clean(v):
    if v is None: return ""
    return re.sub(r"\s+", " ", str(v)).strip(" \t\r\n|•·")

def norm(v):
    s = clean(v).lower()
    s = s.replace("أ","ا").replace("إ","ا").replace("آ","ا").replace("ى","ي").replace("ة","ه")
    return re.sub(r"[^a-z0-9\u0600-\u06ff]", "", s)

def parse_dt(v):
    if not v: return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z","+00:00"))
        if d.tzinfo is None: d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(TZ)
    except Exception:
        return None

def get_json(url, params=None):
    r = session.get(url, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()

def get_html(url):
    r = session.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    return r.text

def record(home, away, league, kickoff, status="upcoming", score="VS",
           home_img="", away_img="", channels=None, commentators=None, source=""):
    channels = unique(channels or [])
    commentators = unique(commentators or [])
    return {
        "league": clean(league) or "كرة القدم",
        "home": clean(home), "away": clean(away),
        "team1": clean(home), "team2": clean(away),
        "home_img": clean(home_img), "away_img": clean(away_img),
        "hour": kickoff.strftime("%H:%M"), "time": kickoff.strftime("%H:%M"),
        "date": kickoff.date().isoformat(), "match_date": kickoff.date().isoformat(),
        "status": status, "score": score or "VS",
        # Keep legacy string fields for the app; never collapse different channels.
        "channel": " | ".join(channels),
        "channels": channels,
        "commentator": " | ".join(commentators),
        "commentators": commentators,
        "streamUrl": "", "_sources": [source] if source else []
    }

def unique(values):
    out, seen = [], set()
    for v in values:
        v = clean(v)
        k = norm(v)
        if v and k not in seen and k not in ("لم يحدد بعد","غير محدد","غير متوفر","يحدد لاحقا"):
            seen.add(k); out.append(v)
    return out

def map_status(text="", completed=False):
    t = clean(text).lower()
    if completed or any(x in t for x in ("final","full time","ended","انتهت")): return "ended"
    if any(x in t for x in ("in progress","live","half","استراحة","مباشر","جارية")): return "live"
    return "upcoming"

def parse_fotmob(day):
    data = get_json("https://www.fotmob.com/api/matches",
                    {"date":day.strftime("%Y%m%d"),"ccode3":"IRQ"})
    out = []
    for lg in data.get("leagues",[]):
        for m in lg.get("matches",[]):
            h, a = m.get("home") or {}, m.get("away") or {}
            st = m.get("status") or {}
            dt = parse_dt(st.get("utcTime") or m.get("utcTime") or m.get("kickoff"))
            hn, an = clean(h.get("name") or h.get("shortName")), clean(a.get("name") or a.get("shortName"))
            if not dt or not hn or not an: continue
            hs, aws = h.get("score"), a.get("score")
            score = f"{hs} - {aws}" if hs is not None and aws is not None else "VS"
            out.append(record(hn,an,lg.get("name") or lg.get("title"),dt,
                map_status(st.get("reason") or st.get("description"),st.get("finished",False)),score,
                f"https://images.fotmob.com/image_resources/logo/teamlogo/{h.get('id')}.png" if h.get("id") else "",
                f"https://images.fotmob.com/image_resources/logo/teamlogo/{a.get('id')}.png" if a.get("id") else "",
                source="FotMob"))
    return out

def parse_espn(day, league_id):
    data = get_json(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league_id}/scoreboard",
                    {"dates":day.strftime("%Y%m%d"),"limit":500})
    out=[]
    for ev in data.get("events",[]):
        dt=parse_dt(ev.get("date"))
        comps=ev.get("competitions") or []
        comp=comps[0] if comps else {}
        teams=comp.get("competitors") or []
        h=next((x for x in teams if x.get("homeAway")=="home"),None)
        a=next((x for x in teams if x.get("homeAway")=="away"),None)
        if (not h or not a) and len(teams)>=2: h,a=teams[0],teams[1]
        if not dt or not h or not a: continue
        ht,at=h.get("team") or {},a.get("team") or {}
        hn=clean(ht.get("displayName") or ht.get("name")); an=clean(at.get("displayName") or at.get("name"))
        if not hn or not an: continue
        si=(comp.get("status") or {}).get("type") or {}
        hs,aws=h.get("score"),a.get("score")
        out.append(record(hn,an,(data.get("leagues") or [{}])[0].get("name") or league_id,dt,
            map_status(si.get("description") or si.get("state"),si.get("completed")),
            f"{hs} - {aws}" if hs not in (None,"") and aws not in (None,"") else "VS",
            ht.get("logo") or "",at.get("logo") or "",source="ESPN"))
    return out

CHANNEL_RE = re.compile(r"(?:القناة(?:\s+الناقلة)?|القنوات(?:\s+الناقلة)?|على\s+قناة)\s*[:：]?\s*([^|•\n\r]+)", re.I)
COMMENT_RE = re.compile(r"(?:المعلق|المعلّق|التعليق)\s*[:：]?\s*([^|•\n\r]+)", re.I)
TIME_RE = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
PAIR_RE = re.compile(r"(.{2,70}?)\s+(?:ضد|vs\.?|v)\s+(.{2,70}?)(?=\s+(?:القناة|المعلق|المعلّق|مباشر|انتهت|لم تبدأ)|$)", re.I)

def extract_channels(text):
    m=CHANNEL_RE.search(text)
    if not m: return []
    raw=re.split(r"\s*(?:،|,|/|\+|\s+\|\s+)\s*",m.group(1))
    return unique(raw)

def extract_commentators(text):
    m=COMMENT_RE.search(text)
    if not m: return []
    raw=re.split(r"\s*(?:،|,|/|\+|\s+\|\s+)\s*",m.group(1))
    return unique(raw)

def parse_arabic_page(name, url, day):
    html=get_html(url)
    soup=BeautifulSoup(html,"html.parser")
    found={}
    # Prefer structured JSON embedded in the page, if present.
    scripts=soup.find_all("script")
    for sc in scripts:
        raw=sc.string or sc.get_text(" ",strip=True)
        if not raw or len(raw)<20: continue
        if sc.get("type") not in ("application/ld+json","application/json") and not any(k in raw for k in ("homeTeam","awayTeam","home_team","away_team")):
            continue
        try: obj=json.loads(raw)
        except Exception: continue
        for m in walk_match_objects(obj):
            item=from_structured(m,name,day)
            if item: found[match_key(item)]=item

    # Generic visible match cards. Keep source-specific card nodes separate.
    selectors = [
        "[class*='match-card']", "[class*='match_item']", "[class*='match-item']",
        "[class*='fixture']", "[class*='event-card']", "[class*='match-row']",
        "article", "[data-home]", "[data-hometeam]"
    ]
    nodes=[]
    for sel in selectors:
        try: nodes.extend(soup.select(sel))
        except Exception: pass
    seen_nodes=set()
    for node in nodes:
        ident=id(node)
        if ident in seen_nodes: continue
        seen_nodes.add(ident)
        txt=clean(node.get_text(" ",strip=True))
        if len(txt)<12 or len(txt)>1800: continue
        pair=PAIR_RE.search(txt)
        inferred_score="VS"
        if pair:
            hn,an=clean(pair.group(1)),clean(pair.group(2))
        else:
            # Arabic match-card pattern: Home 1 - 0 انتهت Away ... channel/commentator
            scored=re.search(r"^(.{2,65}?)\s+(\d{1,2})\s*[-:]\s*(\d{1,2})\s+(?:انتهت|استراحة|نهاية|\d{1,2}['’])\s*(.{2,65}?)(?=\s+(?:القناة|المعلق|المعلّق)|$)",txt)
            upcoming=re.search(r"^(.{2,65}?)\s+(?:\d{1,2}:\d{2})\s+(?:لم تبدأ|قريباً|قادمة)\s+(.{2,65}?)(?=\s+(?:القناة|المعلق|المعلّق)|$)",txt)
            if scored:
                hn,an=clean(scored.group(1)),clean(scored.group(4))
                inferred_score=f"{scored.group(2)} - {scored.group(3)}"
            elif upcoming:
                hn,an=clean(upcoming.group(1)),clean(upcoming.group(2))
            else:
                # Some cards list team names in data attributes.
                hn=clean(node.get("data-home") or node.get("data-hometeam"))
                an=clean(node.get("data-away") or node.get("data-awayteam"))
        if not hn or not an or len(hn)>70 or len(an)>70: continue
        tm=TIME_RE.search(txt)
        if tm:
            dt=datetime.combine(day,datetime.strptime(tm.group(0),"%H:%M").time()).replace(tzinfo=TZ)
        else:
            # Use machine-readable time when available; otherwise skip rather than invent kickoff.
            dt=parse_dt(node.get("data-date") or node.get("datetime"))
            if not dt: continue
        channels=extract_channels(txt)
        commentators=extract_commentators(txt)
        league=""
        parent=node
        for _ in range(4):
            if not parent: break
            prev=parent.find_previous(["h2","h3","h4"])
            if prev:
                league=clean(prev.get_text(" ",strip=True)); break
            parent=parent.parent
        score=inferred_score
        if score=="VS":
            sm=re.search(r"(\d{1,2})\s*[-:]\s*(\d{1,2})",txt)
            if sm: score=f"{sm.group(1)} - {sm.group(2)}"
        status=map_status(txt, "انتهت" in txt)
        item=record(hn,an,league or name,dt,status,score,channels=channels,
                    commentators=commentators,source=name)
        found[match_key(item)]=item
    return list(found.values())

def walk_match_objects(obj):
    if isinstance(obj,dict):
        keys=set(obj.keys())
        if ({"homeTeam","awayTeam"}<=keys or {"home_team","away_team"}<=keys or {"home","away"}<=keys):
            yield obj
        for v in obj.values(): yield from walk_match_objects(v)
    elif isinstance(obj,list):
        for v in obj: yield from walk_match_objects(v)

def team_name(v):
    if isinstance(v,dict): return clean(v.get("name") or v.get("displayName") or v.get("shortName"))
    return clean(v)

def from_structured(m,source,day):
    h=m.get("homeTeam") or m.get("home_team") or m.get("home")
    a=m.get("awayTeam") or m.get("away_team") or m.get("away")
    hn,an=team_name(h),team_name(a)
    dt=parse_dt(m.get("startDate") or m.get("date") or m.get("start_time") or m.get("utcTime"))
    if not hn or not an or not dt or dt.date()!=day: return None
    broadcast=m.get("broadcast") or m.get("tv") or {}
    if not isinstance(broadcast,dict): broadcast={"name":broadcast}
    channels=m.get("channels") or m.get("tvChannels") or [broadcast.get("name") or m.get("channel")]
    comms=m.get("commentators") or [m.get("commentator")]
    if not isinstance(channels,list): channels=[channels]
    if not isinstance(comms,list): comms=[comms]
    league=m.get("league") or m.get("competition") or source
    if isinstance(league,dict): league=league.get("name")
    return record(hn,an,league,dt,map_status(m.get("status")),m.get("score") or "VS",
                  channels=channels,commentators=comms,source=source)

def match_key(x):
    return (x.get("date",""),norm(x.get("home","")),norm(x.get("away","")))

def load_old():
    if not OUTPUT.exists(): return {}
    try:
        d=json.loads(OUTPUT.read_text(encoding="utf-8"))
        rows=d.get("matches",[]) if isinstance(d,dict) else d
        return {match_key(x):x for x in rows if isinstance(x,dict)}
    except Exception as e:
        print("WARNING: old matches.json could not be read:",e)
        return {}

def merge(all_rows,old):
    merged={}
    for x in all_rows:
        k=match_key(x)
        if not k[1] or not k[2]: continue
        if k not in merged:
            merged[k]=x
            continue
        cur=merged[k]
        # Combine distinct broadcasters/commentators, never replace two Dubai Sports feeds with one.
        cur["channels"]=unique((cur.get("channels") or [cur.get("channel")]) + (x.get("channels") or [x.get("channel")]))
        cur["commentators"]=unique((cur.get("commentators") or [cur.get("commentator")]) + (x.get("commentators") or [x.get("commentator")]))
        cur["channel"]=" | ".join(cur["channels"])
        cur["commentator"]=" | ".join(cur["commentators"])
        for f in ("home_img","away_img"):
            if not cur.get(f) and x.get(f): cur[f]=x[f]
        if cur.get("status")!="live" and x.get("status")=="live": cur["status"]="live"
        if x.get("score") not in ("","VS",None): cur["score"]=x["score"]
        cur["_sources"]=unique(cur.get("_sources",[])+x.get("_sources",[]))
    # Preserve app metadata for matching fixtures.
    for k,x in merged.items():
        prev=old.get(k)
        if not prev: continue
        for f in ("streamUrl","home_img","away_img"):
            if prev.get(f) and not x.get(f): x[f]=prev[f]
        old_channels=prev.get("channels") or ([prev.get("channel")] if prev.get("channel") else [])
        old_comms=prev.get("commentators") or ([prev.get("commentator")] if prev.get("commentator") else [])
        x["channels"]=unique(x.get("channels",[])+old_channels)
        x["commentators"]=unique(x.get("commentators",[])+old_comms)
        x["channel"]=" | ".join(x["channels"])
        x["commentator"]=" | ".join(x["commentators"])
        if x["status"]=="upcoming" and prev.get("status") in ("live","ended"): x["status"]=prev["status"]
        if x["score"]=="VS" and prev.get("score") not in ("","VS",None): x["score"]=prev["score"]
    return sorted(merged.values(),key=lambda z:(z["date"],z["hour"],z["home"]))

def main():
    print("YALLA KORA V21 — ARABIC + INTERNATIONAL + BROADCAST DATA")
    print("Baghdad:",NOW.isoformat())
    old=load_old()
    rows=[]
    # Arabic sources first, each source isolated.
    for source,url in ARABIC_PAGES:
        count=0
        # These Arabic pages are daily views, not date-parameterized APIs.
        # Fetch each page once; do not relabel the same fixtures as yesterday/tomorrow.
        try:
            got=parse_arabic_page(source,url,NOW.date())
            rows.extend(got); count+=len(got)
        except Exception as e:
            if len(STATS["errors"])<40: STATS["errors"].append(f"{source}: {e}")
        STATS["arabic_pages"][source]=count
        print(f"{source}: {count} parsed records")
        time.sleep(0.25)
    # International schedule fallback.
    for day in DATES:
        try:
            got=parse_fotmob(day); rows.extend(got); STATS["fotmob"]+=len(got)
        except Exception as e:
            if len(STATS["errors"])<40: STATS["errors"].append(f"FotMob {day}: {e}")
        for lid in ESPN_LEAGUES:
            try:
                got=parse_espn(day,lid); rows.extend(got); STATS["espn"]+=len(got)
            except Exception as e:
                if len(STATS["errors"])<40: STATS["errors"].append(f"ESPN {lid} {day}: {e}")
            time.sleep(0.04)

    allowed={d.isoformat() for d in DATES}
    rows=[x for x in rows if x["date"] in allowed]
    final=merge(rows,old)
    if not final:
        raise RuntimeError("No fixtures were extracted; existing matches.json was NOT changed.")

    # Remove internal-only metadata but keep explicit arrays for apps that support them.
    for x in final:
        x.pop("_sources",None)
        x["channels"]=unique(x.get("channels",[]))
        x["commentators"]=unique(x.get("commentators",[]))
        x["channel"]=" | ".join(x["channels"])
        x["commentator"]=" | ".join(x["commentators"])

    result={
        "version":"V21-ARABIC-MULTI-SOURCE-BROADCAST",
        "updated_at":datetime.now(TZ).isoformat(),
        "timezone":"Asia/Baghdad",
        "matches":final,
        "counts":{
            "total":len(final),
            "today":sum(x["date"]==NOW.date().isoformat() for x in final),
            "yesterday":sum(x["date"]==(NOW.date()-timedelta(days=1)).isoformat() for x in final),
            "tomorrow":sum(x["date"]==(NOW.date()+timedelta(days=1)).isoformat() for x in final),
            "with_channel":sum(bool(x.get("channel")) for x in final),
            "with_multiple_channels":sum(len(x.get("channels",[]))>1 for x in final),
            "with_commentator":sum(bool(x.get("commentator")) for x in final),
        },
        "sources":STATS
    }
    tmp=OUTPUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    tmp.replace(OUTPUT)
    print("\nDONE:",json.dumps(result["counts"],ensure_ascii=False))
    print("Source report:",json.dumps(STATS,ensure_ascii=False))

if __name__=="__main__":
    main()
        
