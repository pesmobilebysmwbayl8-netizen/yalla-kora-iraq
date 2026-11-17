#!/usr/bin/env python3
# YALLA KORA V22 - stable multi-source fixtures
# Keeps the existing matches.json schema and preserves channel/commentator/streamUrl data.
# No guessed Arabic website URLs are used.

import json, re, time
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
    "eng.1","eng.2","eng.3","eng.4","esp.1","esp.2","ger.1","ger.2",
    "ita.1","ita.2","fra.1","fra.2","ned.1","por.1","bel.1","tur.1",
    "sco.1","usa.1","mex.1","arg.1","bra.1","aus.1","ksa.1","qat.1",
    "irn.1","jpn.1","kor.1","uefa.champions","uefa.europa",
    "uefa.europa.conf","uefa.nations","fifa.world","fifa.friendly",
]
session = requests.Session()
session.headers.update(HEADERS)
STATS = {"fotmob":{"ok":0,"failed":0},"espn":{"ok":0,"failed":0},"errors":[]}

def clean(v):
    return re.sub(r"\s+"," ",str(v or "")).strip(" \t\r\n|•·")

def norm(v):
    s=clean(v).lower()
    s=s.replace("أ","ا").replace("إ","ا").replace("آ","ا").replace("ى","ي").replace("ة","ه")
    return re.sub(r"[^a-z0-9\u0600-\u06ff]","",s)

def unique(values):
    out=[]; seen=set()
    for v in values or []:
        v=clean(v); k=norm(v)
        if v and k and k not in seen:
            seen.add(k); out.append(v)
    return out

def parse_dt(v):
    if not v: return None
    try:
        d=datetime.fromisoformat(str(v).replace("Z","+00:00"))
        if d.tzinfo is None: d=d.replace(tzinfo=timezone.utc)
        return d.astimezone(TZ)
    except (TypeError,ValueError):
        return None

def get_json(url,params=None):
    r=session.get(url,params=params,timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()

def find_metadata(obj, keys):
    found=[]
    if isinstance(obj,dict):
        for k in keys:
            v=obj.get(k)
            if isinstance(v,str): found.append(v)
            elif isinstance(v,dict):
                found.extend(v[x] for x in ("name","displayName","title") if v.get(x))
            elif isinstance(v,list):
                for item in v:
                    if isinstance(item,str): found.append(item)
                    elif isinstance(item,dict):
                        found.extend(item[x] for x in ("name","displayName","title") if item.get(x))
        for v in obj.values():
            if isinstance(v,dict): found.extend(find_metadata(v,keys))
            elif isinstance(v,list):
                for x in v:
                    if isinstance(x,dict): found.extend(find_metadata(x,keys))
    elif isinstance(obj,list):
        for x in obj:
            if isinstance(x,dict): found.extend(find_metadata(x,keys))
    return unique(found)

def status(raw="",completed=False,state=""):
    t=(clean(raw)+" "+clean(state)).lower()
    if completed or state.lower()=="post" or any(x in t for x in ("final","full time","ended","انتهت","finished")):
        return "ended"
    if state.lower()=="in" or any(x in t for x in ("in progress","live","half","مباشر","استراحة","جارية")):
        return "live"
    return "upcoming"

def make_row(home,away,league,kickoff,st="upcoming",score="VS",home_img="",away_img="",channels=None,commentators=None):
    ch=unique(channels or []); co=unique(commentators or [])
    return {
        "league":clean(league) or "كرة القدم","home":clean(home),"away":clean(away),
        "team1":clean(home),"team2":clean(away),"home_img":clean(home_img),"away_img":clean(away_img),
        "hour":kickoff.strftime("%H:%M"),"time":kickoff.strftime("%H:%M"),
        "date":kickoff.date().isoformat(),"match_date":kickoff.date().isoformat(),
        "status":st,"score":clean(score) or "VS","channel":" | ".join(ch),"channels":ch,
        "commentator":" | ".join(co),"commentators":co,"streamUrl":""
    }

def parse_fotmob(day):
    data=get_json("https://www.fotmob.com/api/matches",{"date":day.strftime("%Y%m%d"),"ccode3":"IRQ"})
    rows=[]
    for league in data.get("leagues",[]):
        for m in league.get("matches",[]):
            h=m.get("home") or {}; a=m.get("away") or {}; s=m.get("status") or {}
            dt=parse_dt(s.get("utcTime") or m.get("utcTime") or m.get("kickoff"))
            hn=clean(h.get("name") or h.get("shortName")); an=clean(a.get("name") or a.get("shortName"))
            if not dt or not hn or not an: continue
            hs,aws=h.get("score"),a.get("score")
            score=f"{hs} - {aws}" if hs is not None and aws is not None else "VS"
            rows.append(make_row(
                hn,an,league.get("name") or league.get("title"),dt,
                status(s.get("reason") or s.get("description"),s.get("finished",False),s.get("state","")),
                score,
                f"https://images.fotmob.com/image_resources/logo/teamlogo/{h.get('id')}.png" if h.get("id") else "",
                f"https://images.fotmob.com/image_resources/logo/teamlogo/{a.get('id')}.png" if a.get("id") else "",
                find_metadata(m,("channel","channels","tv","broadcaster","broadcasters")),
                find_metadata(m,("commentator","commentators","commentary"))
            ))
    return rows

def parse_espn(day,lid):
    data=get_json(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{lid}/scoreboard",
                  {"dates":day.strftime("%Y%m%d"),"limit":500})
    rows=[]; league=((data.get("leagues") or [{}])[0]).get("name") or lid
    for ev in data.get("events",[]):
        dt=parse_dt(ev.get("date")); comps=ev.get("competitions") or []
        comp=comps[0] if comps else {}; teams=comp.get("competitors") or []
        h=next((x for x in teams if x.get("homeAway")=="home"),None)
        a=next((x for x in teams if x.get("homeAway")=="away"),None)
        if (not h or not a) and len(teams)>=2: h,a=teams[0],teams[1]
        if not dt or not h or not a: continue
        ht=h.get("team") or {}; at=a.get("team") or {}
        hn=clean(ht.get("displayName") or ht.get("name")); an=clean(at.get("displayName") or at.get("name"))
        if not hn or not an: continue
        so=comp.get("status") or ev.get("status") or {}; typ=so.get("type") or {}
        hs,aws=h.get("score"),a.get("score")
        score=f"{hs} - {aws}" if hs not in (None,"") and aws not in (None,"") else "VS"
        rows.append(make_row(
            hn,an,league,dt,status(typ.get("description") or so.get("displayClock"),typ.get("completed",False),typ.get("state","")),
            score,ht.get("logo",""),at.get("logo",""),
            find_metadata(comp,("channel","channels","broadcast","broadcasters")),
            find_metadata(comp,("commentator","commentators","commentary"))
        ))
    return rows

def key(row):
    return (clean(row.get("date") or row.get("match_date")),
            norm(row.get("home") or row.get("team1")),
            norm(row.get("away") or row.get("team2")))

def load_old():
    if not OUTPUT.exists(): return {}
    try:
        d=json.loads(OUTPUT.read_text(encoding="utf-8"))
        rows=d.get("matches",[]) if isinstance(d,dict) else d
        return {key(x):x for x in rows if isinstance(x,dict) and key(x)[1] and key(x)[2]}
    except Exception as e:
        print("WARNING: previous JSON unreadable:",e); return {}

def merge(fresh,old):
    merged={k:dict(v) for k,v in old.items() if k[0] in DATE_SET}
    for row in fresh:
        k=key(row)
        if k[0] not in DATE_SET or not k[1] or not k[2]: continue
        prev=merged.get(k) or old.get(k) or {}
        item=dict(prev); item.update(row)
        for field in ("streamUrl","home_img","away_img"):
            if prev.get(field) and not row.get(field): item[field]=prev[field]
        old_ch=prev.get("channels") or ([prev["channel"]] if prev.get("channel") else [])
        old_co=prev.get("commentators") or ([prev["commentator"]] if prev.get("commentator") else [])
        item["channels"]=unique((row.get("channels") or [])+old_ch)
        item["commentators"]=unique((row.get("commentators") or [])+old_co)
        item["channel"]=" | ".join(item["channels"]); item["commentator"]=" | ".join(item["commentators"])
        if row.get("status")=="upcoming" and prev.get("status") in ("live","ended"): item["status"]=prev["status"]
        if row.get("score") in ("","VS",None) and prev.get("score") not in ("","VS",None): item["score"]=prev["score"]
        item["team1"]=item.get("home",item.get("team1","")); item["team2"]=item.get("away",item.get("team2",""))
        item["time"]=item.get("hour",item.get("time","")); item["match_date"]=item.get("date",item.get("match_date",""))
        merged[k]=item
    return sorted(merged.values(),key=lambda x:(clean(x.get("date")),clean(x.get("hour")),clean(x.get("home"))))

def main():
    print("YALLA KORA V22 | Asia/Baghdad |",NOW.isoformat())
    old=load_old(); fresh=[]
    for day in DATES:
        try:
            got=parse_fotmob(day); fresh.extend(got); STATS["fotmob"]["ok"]+=len(got)
            print("FotMob",day,len(got))
        except Exception as e:
            STATS["fotmob"]["failed"]+=1; STATS["errors"].append(f"FotMob {day}: {e}")
            print("FotMob FAILED",day,e)
        for lid in ESPN_LEAGUES:
            try:
                got=parse_espn(day,lid); fresh.extend(got); STATS["espn"]["ok"]+=len(got)
            except Exception as e:
                STATS["espn"]["failed"]+=1
                if len(STATS["errors"])<30: STATS["errors"].append(f"ESPN {lid} {day}: {e}")
            time.sleep(0.04)

    rows=merge(fresh,old)
    if not rows: raise RuntimeError("No fixtures found. Existing matches.json was not changed.")
    for x in rows:
        x.setdefault("team1",x.get("home","")); x.setdefault("team2",x.get("away",""))
        x.setdefault("time",x.get("hour","")); x.setdefault("match_date",x.get("date",""))
        x.setdefault("channels",[x["channel"]] if x.get("channel") else [])
        x.setdefault("commentators",[x["commentator"]] if x.get("commentator") else [])
        x["channels"]=unique(x.get("channels",[])); x["commentators"]=unique(x.get("commentators",[]))
        x["channel"]=" | ".join(x["channels"]); x["commentator"]=" | ".join(x["commentators"])
        x.setdefault("streamUrl","")

    today=NOW.date().isoformat()
    result={
        "version":"V22-STABLE-MULTI-SOURCE",
        "updated_at":datetime.now(TZ).isoformat(),"timezone":"Asia/Baghdad","matches":rows,
        "counts":{
            "total":len(rows),"today":sum(x.get("date")==today for x in rows),
            "yesterday":sum(x.get("date")== (NOW.date()-timedelta(days=1)).isoformat() for x in rows),
            "tomorrow":sum(x.get("date")== (NOW.date()+timedelta(days=1)).isoformat() for x in rows),
            "with_channel":sum(bool(x.get("channel")) for x in rows),
            "with_multiple_channels":sum(len(x.get("channels",[]))>1 for x in rows),
            "with_commentator":sum(bool(x.get("commentator")) for x in rows)
        },"sources":STATS
    }
    tmp=OUTPUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    tmp.replace(OUTPUT)
    print("DONE:",json.dumps(result["counts"],ensure_ascii=False))
    print("SOURCES:",json.dumps(STATS,ensure_ascii=False))

if __name__=="__main__":
    main()
            
