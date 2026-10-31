import json
import os
import re
import sys
import tempfile
import hashlib
from pathlib import Path
from datetime import datetime, timedelta, time as dt_time
from difflib import SequenceMatcher
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# مصادر متعددة: جدول عربي للمباريات والقنوات + جدول عربي للمعلقين.
# لا نضع أسماء المصادر أو روابطها داخل بيانات التطبيق.
BAGHDAD = ZoneInfo("Asia/Baghdad")
CAIRO = ZoneInfo("Africa/Cairo")
OUTPUT = Path("matches.json")

MATCH_PAGES = {
    "today": "https://www.koraliveonline.net/matches-today/",
    "yesterday": "https://www.koraliveonline.net/matches-yesterday/",
    "tomorrow": "https://www.koraliveonline.net/matches-tomorrow/",
}

COMMENTATOR_PAGES = [
    "https://elgoal.net/معلقين-مباريات-اليوم-ومعلقين-الاسبوع/",
    "https://elgoal.net/معلقين-مباريات-الغد/",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/128.0 Safari/537.36",
    "Accept-Language": "ar,en-US;q=0.8,en;q=0.7",
}

CHANNEL_WORDS = (
    "bein", "be in", "بي ان", "بيإن", "بي إن", "ثمانية", "ssc", "شاهد", "shahid",
    "mbc", "action", "starz", "on sport", "اون سبورت", "الكأس", "الكاس",
    "ابوظبي الرياضية", "أبوظبي الرياضية", "العراقية الرياضية", "الرياضية المغربية",
    "المغربية الرياضية", "دبي الرياضية", "الشارقة الرياضية", "الكويت الرياضية",
)
LEAGUE_WORDS = (
    "الدوري", "كأس", "champions", "premier league", "la liga", "serie a",
    "bundesliga", "ligue 1", "روشن", "نجوم العراق", "المحترفين", "أبطال أوروبا",
)
STATUS_WORDS = (
    "مباشر", "جارية", "الشوط", "انتهت", "لم تبدأ", "تبدأ قريب", "بعد قليل",
    "live", "finished", "ended", "not started", "upcoming", "half time",
)
TIME_RE = re.compile(r"(?<!\d)(\d{1,2}:\d{2})(?:\s*([AP]M|م|ص))?(?!\d)", re.I)
SCORE_RE = re.compile(r"(?<!\d)(\d{1,2})\s*[-–]\s*(\d{1,2})(?!\d)")


def make_session():
    session = requests.Session()
    session.headers.update(HEADERS)
    retry = Retry(total=2, connect=2, read=2, backoff_factor=1,
                  status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=("GET",))
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def clean(value):
    value = str(value or "").replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip(" \t\r\n|•·")


def get_text_lines(node):
    return [clean(x) for x in node.get_text("\n", strip=True).splitlines() if clean(x)]


def normalize_time(value, day="today"):
    value = clean(value)
    match = TIME_RE.search(value)
    if not match:
        return value
    clock, meridiem = match.groups()
    meridiem = (meridiem or "").upper()
    if meridiem == "م":
        meridiem = "PM"
    elif meridiem == "ص":
        meridiem = "AM"

    try:
        if meridiem in ("AM", "PM"):
            parsed = datetime.strptime(f"{clock} {meridiem}", "%I:%M %p")
        else:
            parsed = datetime.strptime(clock, "%H:%M")
    except ValueError:
        return clock

    base_date = datetime.now(BAGHDAD).date()
    offset = {"yesterday": -1, "today": 0, "tomorrow": 1}.get(day, 0)
    source_date = base_date + timedelta(days=offset)
    source_dt = datetime.combine(source_date, parsed.time()).replace(tzinfo=CAIRO)
    return source_dt.astimezone(BAGHDAD).strftime("%H:%M")


def get_status(text):
    text = clean(text).lower()
    if any(x in text for x in ("انتهت", "finished", "ended", "full time")):
        return "ended"
    if any(x in text for x in ("مباشر", "جارية", "الشوط", "live", "half time")):
        return "live"
    return "upcoming"


def is_status(text):
    low = clean(text).lower()
    return any(x in low for x in STATUS_WORDS)


def looks_channel(text):
    low = clean(text).lower()
    return any(x in low for x in CHANNEL_WORDS)


def looks_league(text):
    low = clean(text).lower()
    return any(x in low for x in LEAGUE_WORDS)


def is_team_candidate(text):
    text = clean(text)
    low = text.lower()
    if len(text) < 2 or len(text) > 65:
        return False
    if is_status(text) or looks_channel(text) or looks_league(text):
        return False
    if TIME_RE.search(text) or SCORE_RE.search(text):
        return False
    if any(x in low for x in ("التفاصيل", "مركز المباراة", "تابع المباراة", "مباريات اليوم", "مباريات الغد", "لم يعلن بعد", "لم يُعلن بعد", "يعلن لاحقاً", "يحدد لاحقاً", "غير معروف")):
        return False
    if re.fullmatch(r"[\d\W_]+", text):
        return False
    return True


def extract_pair(text):
    text = clean(text)
    patterns = [r"\s+ضد\s+", r"\s+×\s+", r"\s+x\s+", r"\s+vs\.?\s+", r"\s+VS\s+"]
    for pattern in patterns:
        parts = re.split(pattern, text, maxsplit=1, flags=re.I)
        if len(parts) == 2 and is_team_candidate(parts[0]) and is_team_candidate(parts[1]):
            return clean(parts[0]), clean(parts[1])
    return "", ""


def parse_match_card(card, page_url, day):
    lines = get_text_lines(card)
    if not lines:
        return None

    home = away = ""
    pair_line = next((x for x in lines if extract_pair(x) != ("", "")), "")
    if pair_line:
        home, away = extract_pair(pair_line)

    # شعارات الفرق غالباً تحمل أسماء الفرق في alt.
    if not home or not away:
        image_names = []
        for img in card.find_all("img"):
            alt = clean(img.get("alt"))
            if is_team_candidate(alt) and alt not in image_names:
                image_names.append(alt)
        if len(image_names) >= 2:
            home, away = image_names[0], image_names[1]

    if not home or not away:
        candidates = [x for x in lines if is_team_candidate(x)]
        if len(candidates) >= 2:
            home, away = candidates[0], candidates[1]

    if not home or not away or home.casefold() == away.casefold():
        return None

    hour = ""
    score = ""
    status_text = ""
    league = ""
    channel = ""

    for line in lines:
        if not hour and TIME_RE.search(line):
            hour = normalize_time(line, day)
        score_match = SCORE_RE.search(line)
        if score_match and not TIME_RE.search(line):
            score = f"{score_match.group(1)}-{score_match.group(2)}"
        if not status_text and is_status(line):
            status_text = line
        if not league and (line.startswith("🏆") or looks_league(line)):
            league = clean(line.replace("🏆", ""))
        if not channel and (line.startswith("📺") or looks_channel(line)):
            channel = clean(line.replace("📺", ""))

    status = get_status(status_text)
    if status == "upcoming":
        score = ""

    images = []
    for img in card.find_all("img"):
        alt = clean(img.get("alt"))
        src = img.get("data-src") or img.get("data-lazy-src") or img.get("src") or ""
        if alt and src:
            images.append((alt, urljoin(page_url, src)))

    def image_for(team):
        for alt, src in images:
            if alt.casefold() == team.casefold() or team.casefold() in alt.casefold():
                return src
        return ""

    match_link = ""
    for a in card.find_all("a", href=True):
        href = a.get("href", "")
        if href and not href.startswith("#") and "javascript:" not in href.lower():
            candidate = urljoin(page_url, href)
            if candidate.startswith("https://"):
                match_link = candidate
                break

    return {
        "day": day,
        "league": league,
        "home": home,
        "away": away,
        "team1": home,
        "team2": away,
        "home_img": image_for(home),
        "away_img": image_for(away),
        "hour": hour,
        "time": hour,
        "status": status,
        "score": score,
        "channel": channel,
        "commentator": "",
        "streamUrl": "",
        "match_link": "",
    }


def scrape_matches_page(session, day, url):
    response = session.get(url, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    selectors = [
        ".match-card", ".match-item", ".matches-item", ".fixture",
        ".event-card", ".event-item", "[class*='match-card']",
        "[class*='match-item']", "[class*='fixture']",
    ]
    cards = []
    for selector in selectors:
        cards.extend(soup.select(selector))

    if not cards:
        cards = soup.find_all(["article", "li"])
    if not cards:
        # بعض المواقع تضع كل مباراة داخل div بلا class ثابت؛ نلتقط أصغر حاوية
        # تحتوي شعارَي الفريق والقناة والبطولة حتى لا نقرأ الصفحة كلها كبطاقة واحدة.
        for node in soup.find_all(["div", "section"]):
            text_value = node.get_text(" ", strip=True)
            if (len(text_value) < 900 and len(node.find_all("img")) >= 2
                    and looks_channel(text_value) and looks_league(text_value)):
                cards.append(node)

    matches = []
    seen = set()
    for card in sorted(cards, key=lambda n: len(n.get_text(" ", strip=True))):
        match = parse_match_card(card, url, day)
        if not match:
            continue
        key = (normalize_team(match["home"]), normalize_team(match["away"]))
        if key in seen:
            continue
        seen.add(key)
        matches.append(match)

    if not matches:
        raise RuntimeError(f"لم يتم العثور على بطاقات مباريات في صفحة {day}")
    print(f"{day}: {len(matches)} مباراة")
    return matches


def normalize_team(name):
    name = clean(name).lower()
    name = re.sub(r"[ًٌٍَُِّْـ]", "", name)
    name = name.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    name = name.replace("ى", "ي").replace("ة", "ه")
    name = re.sub(r"\b(fc|cf|sc|afc|club|نادي|نادي)?\b", "", name)
    name = re.sub(r"[^\w\u0600-\u06FF]+", "", name)
    return name


def pair_similarity(a1, a2, b1, b2):
    a1, a2, b1, b2 = map(normalize_team, (a1, a2, b1, b2))
    direct = (SequenceMatcher(None, a1, b1).ratio() + SequenceMatcher(None, a2, b2).ratio()) / 2
    reverse = (SequenceMatcher(None, a1, b2).ratio() + SequenceMatcher(None, a2, b1).ratio()) / 2
    return max(direct, reverse)


def parse_commentator_table(session, url, day="today"):
    response = session.get(url, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    found = []

    for row in soup.find_all("tr"):
        cells = [clean(c.get_text(" ", strip=True)) for c in row.find_all(["td", "th"])]
        cells = [x for x in cells if x]
        if len(cells) < 3:
            continue
        joined = " | ".join(cells)
        home = away = ""
        for cell in cells:
            home, away = extract_pair(cell)
            if home and away:
                break
        if not home or not away:
            continue

        channel = ""
        channel_index = -1
        for i, cell in enumerate(cells):
            if looks_channel(cell):
                channel, channel_index = cell, i
                break

        commentator = ""
        if channel_index >= 0:
            for cell in cells[channel_index + 1:]:
                if (not TIME_RE.search(cell) and not is_status(cell)
                        and not looks_league(cell) and not looks_channel(cell)
                        and len(cell) <= 55 and is_team_candidate(cell)):
                    commentator = cell
                    break

        hour = ""
        for cell in cells:
            if TIME_RE.search(cell):
                hour = normalize_time(cell, day)
                break

        found.append({"home": home, "away": away, "channel": channel,
                      "commentator": commentator, "hour": hour})

    # بعض الصفحات تعرض الجداول داخل div بدل table.
    if not found:
        for node in soup.select("article, .match, .match-row, [class*='match']"):
            lines = get_text_lines(node)
            if len(lines) < 3:
                continue
            home = away = ""
            for line in lines:
                home, away = extract_pair(line)
                if home and away:
                    break
            if not home or not away:
                continue
            channel = next((x for x in lines if looks_channel(x)), "")
            commentator = ""
            if channel:
                ci = lines.index(channel)
                commentator = next((x for x in lines[ci + 1:]
                                    if is_team_candidate(x) and not looks_channel(x)
                                    and not looks_league(x) and not is_status(x)
                                    and not TIME_RE.search(x)), "")
            hour = next((normalize_time(x, day) for x in lines if TIME_RE.search(x)), "")
            found.append({"home": home, "away": away, "channel": channel,
                          "commentator": commentator, "hour": hour})

    print(f"تم قراءة {len(found)} سجل تعليق")
    return found


def merge_commentators(matches, commentator_rows):
    for match in matches:
        best = None
        best_score = 0.0
        for row in commentator_rows:
            score = pair_similarity(match["home"], match["away"], row["home"], row["away"])
            if score > best_score:
                best, best_score = row, score
        if best and best_score >= 0.78:
            if not match.get("channel") and best.get("channel"):
                match["channel"] = best["channel"]
            if best.get("commentator"):
                match["commentator"] = best["commentator"]
            if not match.get("hour") and best.get("hour"):
                match["hour"] = best["hour"]
                match["time"] = best["hour"]


def save_json(data):
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=OUTPUT.parent,
                                         delete=False) as tmp:
            tmp.write(payload)
            temp_name = tmp.name
        os.replace(temp_name, OUTPUT)
        temp_name = None
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def main():
    session = make_session()
    results = {}
    errors = {}

    for day, url in MATCH_PAGES.items():
        try:
            results[day] = scrape_matches_page(session, day, url)
        except Exception as exc:
            errors[day] = str(exc)
            print(f"تحذير {day}: {exc}")

    commentary_rows = []
    for idx, url in enumerate(COMMENTATOR_PAGES):
        page_day = "today" if idx == 0 else "tomorrow"
        try:
            commentary_rows.extend(parse_commentator_table(session, url, page_day))
        except Exception as exc:
            print(f"تعذر قراءة جدول التعليق: {exc}")

    for day in ("today", "tomorrow", "yesterday"):
        merge_commentators(results.get(day, []), commentary_rows)

    today = results.get("today", [])
    yesterday = results.get("yesterday", [])
    tomorrow = results.get("tomorrow", [])
    all_matches = today + yesterday + tomorrow

    if not today:
        raise RuntimeError("لم تصل مباريات اليوم؛ لم يتم استبدال matches.json حتى لا نخسر البيانات القديمة")

    # منع تكرار السجل نفسه مع اختلاف بسيط في كتابة اسم الفريق.
    deduped = []
    seen = set()
    for match in all_matches:
        key = (normalize_team(match["home"]), normalize_team(match["away"]), match.get("day", ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(match)

    today = [m for m in deduped if m["day"] == "today"]
    yesterday = [m for m in deduped if m["day"] == "yesterday"]
    tomorrow = [m for m in deduped if m["day"] == "tomorrow"]

    now = datetime.now(BAGHDAD)
    output = {
        "success": True,
        "updated_at": now.isoformat(),
        "timezone": "Asia/Baghdad",
        "count": len(deduped),
        "today_count": len(today),
        "yesterday_count": len(yesterday),
        "tomorrow_count": len(tomorrow),
        "matches": deduped,
        "today": today,
        "yesterday": yesterday,
        "tomorrow": tomorrow,
        "warnings_count": len(errors),
    }
    save_json(output)
    print("اكتمل إنشاء matches.json")
    print(f"اليوم: {len(today)} | الأمس: {len(yesterday)} | الغد: {len(tomorrow)}")
    print(f"مجموع المباريات: {len(deduped)} | سجلات المعلقين: {len(commentary_rows)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"فشل التحديث: {exc}", file=sys.stderr)
        sys.exit(1)
                
