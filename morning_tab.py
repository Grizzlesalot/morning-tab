#!/usr/bin/env python3
"""
Morning Tab: builds Chris's daily new-tab page.

Runs once a day in GitHub Actions. Some sections are fetched directly in
Python for free (weather, Reddit, YouTube, eBay). The rest are researched by
Claude through the API using web search and web fetch, which is what spends
the monthly API credit.

Run locally with demo data (no API calls):  python morning_tab.py --demo
"""
import concurrent.futures as cf
import datetime as dt
import html
import json
import os
import re
import sys
import urllib.parse
from zoneinfo import ZoneInfo

import requests

# ---------------------------------------------------------------- settings
MEL = ZoneInfo("Australia/Melbourne")
NOW = dt.datetime.now(MEL)
OUT_DIR = os.environ.get("OUT_DIR", "site")

# Cheap model for lookups, stronger model for judgement calls.
FAST_MODEL = os.environ.get("FAST_MODEL", "claude-haiku-5-5")
SMART_MODEL = os.environ.get("SMART_MODEL", "claude-sonnet-5-5")

# USD per million tokens (input, output), used only to show cost in the footer.
PRICES = {"claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.0, 10.0),
          "claude-opus-5-5": (4.0, 20.0)}
SEARCH_PRICE = 0.01  # USD per web search

LAT, LON = -38.106, 145.262  # Cranbourne West
USER_LOCATION = {"type": "approximate", "city": "Cranbourne West",
                 "region": "Victoria", "country": "AU",
                 "timezone": "Australia/Melbourne"}
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129 Safari/537.36",
      "Accept-Language": "en-AU,en;q=0.9"}

PARANORMAL_SUBS = ["Paranormal", "HighStrangeness", "Ghosts", "Thetruthishere", "UFOs"]
VIDEO_DOMAINS = ("v.redd.it", "youtube.com", "youtu.be", "tiktok.com",
                 "streamable.com", "instagram.com", "x.com", "twitter.com")
YOUTUBE_QUERIES = ["ghost caught on camera", "paranormal activity caught on camera",
                   "UFO sighting", "haunted", "creepy unexplained footage", "ghost hunting",
                   "paranormal investigation", "UFO caught on camera", "scary videos",
                   "poltergeist", "cryptid sighting", "haunted house"]
EXCLUDE_CHANNELS = ("slapped ham",)

CARD_SEARCHES = [
    ("Teamcoach 2024", "2024 teamcoach"),
    ("Teamcoach 2025", "2025 teamcoach"),
    ("Teamcoach 2026", "2026 teamcoach"),
    ("Select Footy Stars 2024", "2024 select footy stars"),
    ("Select Footy Stars 2025", "2025 select footy stars"),
    ("Select Footy Stars 2026", "2026 select footy stars"),
    ("Essendon (TC + Select)", "(teamcoach, select) essendon"),
    ("West Coast (TC + Select)", "(teamcoach, select) west coast eagles"),
]
CARD_YEARS = ("2024", "2025", "2026")
HIGHLIGHT_WORDS = ("essendon", "bombers", "west coast", "eagles")

SYSTEM = (
    "You research a personal morning briefing page for Chris, who lives in "
    "Cranbourne West in South East Melbourne, Australia. Today is {today}. "
    "Use your web search and web fetch tools to find what is new. When the request "
    "lists useful pages, fetch those first and use search only to fill gaps, because "
    "your number of searches is limited. Only report "
    "things you actually found, each with the real URL you found it at. Prefer "
    "the newest items and skip anything older than the window you are given. "
    "Write in plain Australian English, short and friendly. Never use em dashes. "
    "Reply with ONLY a JSON object and no other text, in this shape: "
    '{{"items": [{{"title": "...", "summary": "one or two short sentences", '
    '"url": "https://...", "source": "site name", "date": "e.g. 8 Oct or empty", '
    '"tag": "short label or empty", "highlight": false}}], "note": "one line or empty"}}'
)

# ---------------------------------------------------------- Claude sections
def claude_sections(fixture_hint=""):
    weekday = NOW.weekday()  # Mon=0
    today = NOW.strftime("%A %d %B %Y")
    sat = NOW + dt.timedelta(days=(5 - weekday) % 7)
    sun = sat + dt.timedelta(days=1)
    sections = [
        dict(key="fantasy", title="Fantasy League Lens", model=SMART_MODEL,
             searches=8, fetches=6, prompt=f"""
Build the AFL Fantasy section. Cover, in this order, whatever is current today ({today}):
1. AFLW team selections, ins, outs and late changes for the current or next round. Set highlight true when a popular AFLW Fantasy pick is out or a key player returns. Tag "Teams".
2. New AFLW injuries and expected returns. Tag "Injury".
4. AFL trade period, free agency and draft news, each with one short line on the likely 2027 AFL Fantasy impact. Tag "Trade".
5. Headlines of new official AFL Fantasy or SuperCoach articles from the last 3 days. Tag "Fantasy".
6. Finally 2 or 3 newsletter angle ideas for The Lens (an AFLW Fantasy newsletter) based on today's news. Tag "Idea", url may be empty.
{fixture_hint}If the AFLW season has finished, skip parts 1 and 2. Up to 12 items. Useful pages:
https://www.afl.com.au/news  https://www.womens.afl/news  https://www.afl.com.au/fantasy
https://www.womens.afl/matches/team-lineups
"""),
        dict(key="ai", title="AI updates", model=FAST_MODEL, searches=4, fetches=4,
             prompt="""
Find new announcements and product updates from the last 7 days from OpenAI (ChatGPT),
Anthropic (Claude) and xAI (Grok). Tag each with the company name. Highlight big model
launches. Up to 8 items. Start from these pages:
https://openai.com/news/  https://www.anthropic.com/news  https://x.ai/news
"""),
        dict(key="moca", title="Moca and Minds", model=FAST_MODEL, searches=9, fetches=6,
             prompt="""
Find news from the last 14 days about Moca Network, Mocaverse, AIR Kit and Moca Chain
(Animoca Brands), Minds by Animoca Brands (personal AI agents, hellominds.ai) and
MINDS.GAMES (AI Mind competition with a prize pool, minds.games). Include season dates,
launches, partnerships and token news. Tag with the product name. Highlight anything
with a deadline or launch date. Up to 8 items. If nothing is new, say so in note.
Start from: https://moca.network  https://www.mocaverse.xyz  https://hellominds.ai  https://minds.games
"""),
        dict(key="news", title="Melbourne headlines", model=FAST_MODEL, searches=4, fetches=4,
             prompt="""
Give 3 or 4 notable Melbourne or Victorian news stories from the last 24 hours, tagged
"Melbourne", keeping it light where possible (skip grim crime unless it is major).
Useful pages: https://www.abc.net.au/news/vic  https://www.theage.com.au/melbourne
"""),
        dict(key="sport", title="Sport", model=FAST_MODEL, searches=5, fetches=8,
             prompt="""
Give 6 to 8 sports stories from the last 24 hours, tagged with the sport. Cover as many
of these as have real news: AFL (trade period, draft), AFLW, cricket, A-League, NBL,
plus any big international sport. Fetch these pages first:
https://www.abc.net.au/news/sport  https://www.afl.com.au/news  https://www.cricket.com.au/news
https://keepup.com.au/news  https://nbl.com.au/news
"""),
    ]
    if weekday >= 3:  # Thursday to Sunday
        sections.append(dict(
            key="kids", title=f"Kids this weekend ({sat.strftime('%a %d')} and {sun.strftime('%a %d %b')})",
            model=FAST_MODEL, searches=6, fetches=5, prompt=f"""
Find fun activities and events for young kids (preschool and early primary) on
{sat.strftime('%A %d %B')} and {sun.strftime('%A %d %B')}. Prioritise places within about
25 minutes drive of Cranbourne West (City of Casey, Dandenong, Frankston, Mornington
Peninsula), then 2 or 3 bigger Melbourne events. In summary give what it is, when, and
cost. Tag with the suburb. Highlight free events. Up to 8 items. Useful pages:
https://www.casey.vic.gov.au/events  https://www.rbg.vic.gov.au/visit-cranbourne/whats-on/
https://whatson.melbourne.vic.gov.au  https://www.weekendnotes.com
"""))
    return sections


PARANORMAL_BACKUP = dict(
    key="paranormal", title="Trending paranormal videos", model=FAST_MODEL,
    searches=6, fetches=4, prompt="""
Find the most viral paranormal videos posted in the last 48 hours: ghosts, hauntings,
UFOs, cryptids and creepy unexplained footage, on YouTube, TikTok, Instagram, X or Reddit.
Prefer clips that are getting a lot of views or shares right now, and say the view or
upvote count in the summary if you can find it. Skip anything posted by Slapped Ham.
Tag each with the platform. Highlight anything clearly blowing up. Up to 8 items.
""")


def tool_defs(searches, fetches, direct=False):
    s = {"type": "web_search_20260318", "name": "web_search", "max_uses": searches,
         "user_location": USER_LOCATION}
    f = {"type": "web_fetch_20260318", "name": "web_fetch", "max_uses": fetches,
         "max_content_tokens": 15000}
    if direct:
        s["allowed_callers"] = ["direct"]
        f["allowed_callers"] = ["direct"]
    return [s, f]


def parse_json(text):
    text = re.sub(r"```(?:json)?", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON in reply")
    data = json.loads(text[start:end + 1])
    data.setdefault("items", [])
    data.setdefault("note", "")
    return data


def ask_claude(client, sec, usage):
    import anthropic
    messages = [{"role": "user", "content": sec["prompt"].strip()}]
    system = SYSTEM.format(today=NOW.strftime("%A %d %B %Y"))
    direct = False
    resp = None
    for _ in range(6):
        try:
            resp = client.messages.create(
                model=sec["model"], max_tokens=6000, system=system, messages=messages,
                tools=tool_defs(sec["searches"], sec["fetches"], direct))
        except anthropic.BadRequestError as e:
            # Some models need direct tool calls instead of dynamic filtering.
            if not direct and "allowed_callers" in str(e):
                direct = True
                continue
            raise
        u = resp.usage
        stu = getattr(u, "server_tool_use", None)
        searches = (getattr(stu, "web_search_requests", 0) or 0) if stu else 0
        pin, pout = PRICES.get(sec["model"], (2.0, 10.0))
        tokens_in = (u.input_tokens or 0) + (getattr(u, "cache_creation_input_tokens", 0) or 0) \
            + (getattr(u, "cache_read_input_tokens", 0) or 0)
        usage.append(tokens_in * pin / 1e6 + (u.output_tokens or 0) * pout / 1e6
                     + searches * SEARCH_PRICE)
        if resp.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": resp.content})
            continue
        break
    text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")
    return parse_json(text)


AFL_API = "https://aflapi.afl.com.au/afl/v2"
FIXTURE_HIGHLIGHT = ("essendon", "west coast")


def aflw_fixture():
    """Current AFLW round from the official AFL API (free, no Claude needed)."""
    seasons = requests.get(f"{AFL_API}/competitions/3/compseasons", headers=UA, timeout=20).json()["compSeasons"]
    season = max(seasons, key=lambda x: x["id"])
    cur = season.get("currentRoundNumber") or 1
    for rnd in (cur, cur + 1):
        matches = requests.get(f"{AFL_API}/matches", headers=UA, timeout=20, params={
            "compSeasonId": season["id"], "roundNumber": rnd, "pageSize": 20}).json().get("matches", [])
        if matches and any(m.get("status") != "CONCLUDED" for m in matches):
            break
    else:
        return None
    items = []
    for m in sorted(matches, key=lambda x: x["utcStartTime"]):
        home, away = m["home"]["team"]["name"], m["away"]["team"]["name"]
        start = dt.datetime.strptime(m["utcStartTime"][:19], "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=dt.timezone.utc).astimezone(MEL)
        status = m.get("status", "")
        tag = {"CONFIRMED_TEAMS": "Teams in", "LIVE": "Live", "CONCLUDED": "Done"}.get(status, "")
        items.append(dict(
            title=f"{home} v {away}",
            summary=f"{start.strftime('%a %d %b')} {start.strftime('%I:%M%p').lstrip('0').lower()}, {m['venue']['name']}",
            url="https://www.womens.afl/fixture", source="", date="", tag=tag,
            highlight=any(t in (home + away).lower() for t in FIXTURE_HIGHLIGHT)))
    return dict(title=f"AFLW Round {rnd} fixture", sub="Melbourne time", items=items, note="")


# ------------------------------------------------------------ free sections
WMO = {0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Cloudy", 45: "Fog", 48: "Fog",
       51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle", 61: "Light rain", 63: "Rain",
       65: "Heavy rain", 80: "Showers", 81: "Showers", 82: "Heavy showers",
       95: "Thunderstorms", 96: "Storms with hail", 99: "Storms with hail"}


def get_weather():
    r = requests.get("https://api.open-meteo.com/v1/forecast", timeout=20, params=dict(
        latitude=LAT, longitude=LON, timezone="Australia/Melbourne", forecast_days=3,
        current="temperature_2m,weather_code",
        daily="weather_code,temperature_2m_max,temperature_2m_min,"
              "precipitation_probability_max,uv_index_max"))
    r.raise_for_status()
    d = r.json()
    days = []
    for i, date in enumerate(d["daily"]["time"]):
        name = "Today" if i == 0 else dt.date.fromisoformat(date).strftime("%A")
        days.append(dict(
            name=name, desc=WMO.get(d["daily"]["weather_code"][i], "Mixed"),
            hi=round(d["daily"]["temperature_2m_max"][i]),
            lo=round(d["daily"]["temperature_2m_min"][i]),
            rain=d["daily"]["precipitation_probability_max"][i],
            uv=round(d["daily"]["uv_index_max"][i] or 0)))
    return dict(now=round(d["current"]["temperature_2m"]), days=days)


def reddit_videos():
    items, failed = [], 0
    for sub in PARANORMAL_SUBS:
        try:
            r = requests.get(f"https://www.reddit.com/r/{sub}/top.json",
                             params={"t": "day", "limit": 25}, headers=UA, timeout=20)
            r.raise_for_status()
            for c in r.json()["data"]["children"]:
                p = c["data"]
                is_video = p.get("is_video") or p.get("post_hint") in ("hosted:video", "rich:video") \
                    or any(dom in p.get("domain", "") for dom in VIDEO_DOMAINS)
                if not is_video:
                    continue
                items.append(dict(
                    title=p["title"], url="https://www.reddit.com" + p["permalink"],
                    source=f"r/{sub}", score=p.get("score", 0), tag="Reddit",
                    summary=f"{p.get('score', 0):,} upvotes, {p.get('num_comments', 0):,} comments",
                    date="", highlight=p.get("score", 0) >= 1000))
        except Exception:
            failed += 1
    items.sort(key=lambda x: x["score"], reverse=True)
    return items[:8], failed == len(PARANORMAL_SUBS)


def youtube_videos():
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        return []
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ids = {}
    for q in YOUTUBE_QUERIES:
        r = requests.get("https://www.googleapis.com/youtube/v3/search", timeout=20, params=dict(
            key=key, q=q, part="snippet", type="video", order="viewCount",
            publishedAfter=since, maxResults=15, relevanceLanguage="en", regionCode="US"))
        r.raise_for_status()
        for it in r.json().get("items", []):
            ch = it["snippet"]["channelTitle"]
            if any(x in ch.lower() for x in EXCLUDE_CHANNELS):
                continue
            ids[it["id"]["videoId"]] = (html.unescape(it["snippet"]["title"]), ch)
    if not ids:
        return []
    stats, id_list = [], list(ids)
    for i in range(0, len(id_list), 50):
        r = requests.get("https://www.googleapis.com/youtube/v3/videos", timeout=20, params=dict(
            key=key, id=",".join(id_list[i:i + 50]), part="statistics"))
        r.raise_for_status()
        stats += r.json().get("items", [])
    out = []
    for v in stats:
        views = int(v["statistics"].get("viewCount", 0))
        title, ch = ids[v["id"]]
        out.append(dict(title=title, url=f"https://www.youtube.com/watch?v={v['id']}",
                        source=ch, tag="YouTube", date="", score=views,
                        summary=f"{views:,} views in under 48 hours", highlight=views >= 100000))
    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:40]


BLOCK_WORDS = ("blackpink", "kpop", "k-pop", "bts", "minecraft", "fortnite", "roblox", "gta")


def english_title(t):
    letters = [c for c in t if c.isalpha()]
    if not letters:
        return False
    latin = sum(1 for c in letters if c.isascii())
    if latin / len(letters) < 0.85:
        return False
    # Rough check for Latin-script languages other than English
    words = re.findall(r"[a-z]+", t.lower())
    common = {"the", "a", "of", "in", "on", "at", "caught", "camera", "ghost", "haunted",
              "house", "real", "scary", "night", "ufo", "is", "this", "my", "we", "i", "and", "to"}
    return any(w in common for w in words)


def prefilter_videos(items):
    return [it for it in items if english_title(it["title"])
            and not any(b in it["title"].lower() for b in BLOCK_WORDS)]


def filter_videos(client, items, usage):
    """Use the cheap model to keep only genuine, English-language paranormal clips."""
    if not items:
        return items
    listing = "\n".join(f"{i}: {it['title']} | channel: {it['source']}" for i, it in enumerate(items))
    resp = client.messages.create(
        model=FAST_MODEL, max_tokens=300,
        messages=[{"role": "user", "content": (
            "These are trending videos. Keep ones that are paranormal or spooky content: "
            "ghosts, hauntings, ghost hunts, UFOs, cryptids, unexplained footage, and Halloween "
            "content such as haunted houses, scary decorations and animatronics. "
            "Drop music, K-pop and celebrity clips, gaming, and anything whose title is "
            "not in English. Rank genuine paranormal footage first. When unsure, keep it. "
            "Reply with ONLY the kept numbers, comma separated, best first.\n\n"
            + listing)}])
    pin, pout = PRICES.get(FAST_MODEL, (0.1, 0.5))
    usage.append(resp.usage.input_tokens * pin / 1e6 + resp.usage.output_tokens * pout / 1e6)
    text = "".join(getattr(b, "text", "") for b in resp.content)
    print("video filter reply:", text[:200])
    keep = [int(n) for n in re.findall(r"\d+", text) if int(n) < len(items)]
    seen, out = set(), []
    for n in keep:
        if n not in seen:
            seen.add(n)
            out.append(items[n])
    if len(out) < 3:  # filter too strict or confused: fall back to the pre-filtered list
        return items[:8]
    return out[:8]


def ebay_url(query):
    return "https://www.ebay.com.au/sch/i.html?" + urllib.parse.urlencode(
        {"_nkw": query, "LH_Sold": 1, "LH_Complete": 1, "_sop": 13, "_ipg": 60})


def price_value(p):
    m = re.search(r"[\d,]+\.?\d*", p or "")
    return float(m.group().replace(",", "")) if m else 0.0


def ebay_sold():
    from bs4 import BeautifulSoup
    results, links, blocked = [], [], 0
    seen = set()
    for label, query in CARD_SEARCHES:
        url = ebay_url(query)
        links.append(dict(label=label, url=url))
        try:
            r = requests.get(url, headers=UA, timeout=25)
            soup = BeautifulSoup(r.text, "html.parser")
            cards = soup.select("li.s-item, li.s-card")
            if not cards:
                blocked += 1
                continue
            found = []
            for li in cards:
                t = li.select_one(".s-item__title, .s-card__title")
                a = li.select_one("a[href*='/itm/']")
                p = li.select_one(".s-item__price, .s-card__price")
                if not (t and a and p):
                    continue
                title = t.get_text(" ", strip=True).replace("New Listing", "").strip()
                if title.lower().startswith("shop on ebay"):
                    continue
                link = a["href"].split("?")[0]
                if link in seen:
                    continue
                low = title.lower()
                if not any(y in title for y in CARD_YEARS):
                    continue
                if "teamcoach" not in low.replace(" ", "") and "select" not in low:
                    continue
                cap = li.select_one(".s-item__caption--signal, .s-item__caption, .s-card__caption")
                sold = cap.get_text(" ", strip=True) if cap else ""
                seen.add(link)
                found.append(dict(
                    title=title, url=link, source=label, tag=p.get_text(" ", strip=True),
                    summary=sold, date="", price=price_value(p.get_text()),
                    highlight=any(w in low for w in HIGHLIGHT_WORDS)))
            found.sort(key=lambda x: x["price"], reverse=True)
            results.extend(found[:5])
        except Exception:
            blocked += 1
    results.sort(key=lambda x: (not x["highlight"], -x["price"]))
    return results[:24], links, blocked == len(CARD_SEARCHES)


# ------------------------------------------------------------------ render
CSS = """
:root{--bg:#f6f5f1;--card:#fff;--ink:#1d1d1b;--muted:#6b6a65;--line:#e4e2db;--accent:#c2410c;--hi:#fff4e6}
@media (prefers-color-scheme:dark){:root{--bg:#141414;--card:#1e1e1e;--ink:#ecebe7;--muted:#9a9890;--line:#2e2e2c;--accent:#fb923c;--hi:#2b2117}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:24px 16px 48px}
header{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:flex-end;gap:12px;margin-bottom:18px}
h1{margin:0;font-size:28px}.date{color:var(--muted)}
.weather{display:flex;gap:10px;flex-wrap:wrap}.wx{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px 12px;min-width:120px}
.wx b{display:block}.wx span{color:var(--muted);font-size:13px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:16px}
section{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
section.wide{grid-column:1/-1}
h2{margin:0 0 8px;font-size:17px;display:flex;justify-content:space-between;align-items:baseline}
h2 small{font-weight:400;color:var(--muted);font-size:12px}
ul{list-style:none;margin:0;padding:0}li{padding:9px 0;border-top:1px solid var(--line)}li:first-child{border-top:0}
li.hi{background:var(--hi);margin:0 -16px;padding:9px 16px}
a{color:var(--ink);text-decoration:none;font-weight:600}a:hover{color:var(--accent)}
.meta{color:var(--muted);font-size:12.5px;margin-top:2px}.sum{font-size:14px;margin-top:2px}
.tag{display:inline-block;font-size:11px;font-weight:600;color:var(--accent);border:1px solid var(--line);border-radius:999px;padding:0 7px;margin-right:6px}
.note{color:var(--muted);font-size:13px;font-style:italic;margin:4px 0}
.links{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}.links a{font-size:12px;font-weight:500;border:1px solid var(--line);border-radius:6px;padding:2px 8px}
footer{color:var(--muted);font-size:12px;margin-top:24px;text-align:center}
"""

ORDER = ["fantasy", "fixture", "paranormal", "ai", "moca", "cards", "kids", "news", "sport"]


def esc(s):
    return html.escape(str(s or ""))


def render_items(items):
    out = []
    for it in items:
        cls = ' class="hi"' if it.get("highlight") else ""
        title = esc(it.get("title"))
        title = f'<a href="{esc(it["url"])}">{title}</a>' if it.get("url") else f"<b>{title}</b>"
        tag = f'<span class="tag">{esc(it["tag"])}</span>' if it.get("tag") else ""
        meta = " · ".join(x for x in [esc(it.get("source")), esc(it.get("date"))] if x)
        summ = f'<div class="sum">{esc(it.get("summary"))}</div>' if it.get("summary") else ""
        out.append(f"<li{cls}>{tag}{title}{summ}<div class=\"meta\">{meta}</div></li>")
    return "<ul>" + "".join(out) + "</ul>"


def render(weather, sections, cost):
    wx = ""
    if weather:
        cards = [f'<div class="wx"><b>Now {weather["now"]}°</b><span>Cranbourne West</span></div>']
        for d in weather["days"]:
            cards.append(f'<div class="wx"><b>{esc(d["name"])} {d["hi"]}° / {d["lo"]}°</b>'
                         f'<span>{esc(d["desc"])}, rain {d["rain"]}%, UV {d["uv"]}</span></div>')
        wx = '<div class="weather">' + "".join(cards) + "</div>"
    body = []
    for key in ORDER:
        s = sections.get(key)
        if not s:
            continue
        wide = " wide" if key in ("fantasy",) else ""
        note = f'<p class="note">{esc(s.get("note"))}</p>' if s.get("note") else ""
        items = render_items(s.get("items", [])) if s.get("items") else ""
        links = ""
        if s.get("links"):
            links = '<div class="links">' + "".join(
                f'<a href="{esc(l["url"])}">{esc(l["label"])}</a>' for l in s["links"]) + "</div>"
        body.append(f'<section class="{key}{wide}"><h2>{esc(s["title"])}'
                    f'<small>{esc(s.get("sub", ""))}</small></h2>{note}{items}{links}</section>')
    return f"""<!doctype html><html lang="en-AU"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Morning Tab</title>
<style>{CSS}</style></head><body><div class="wrap">
<header><div><h1>Good morning, Chris</h1><div class="date">{NOW.strftime('%A %d %B %Y')}</div></div>{wx}</header>
<div class="grid">{''.join(body)}</div>
<footer>Built {NOW.strftime('%I:%M %p').lstrip('0')} · API cost this run about US${cost:.2f}</footer>
</div></body></html>"""


# -------------------------------------------------------------------- main
def build(demo=False):
    sections, usage = {}, []
    weather = None
    try:
        weather = get_weather()
    except Exception as e:
        print("weather failed:", e)

    if demo:
        from demo_data import DEMO
        sections = DEMO
    else:
        import anthropic
        client = anthropic.Anthropic()
        fixture_hint = ""
        try:
            fixture = aflw_fixture()
            if fixture:
                sections["fixture"] = fixture
                games = "; ".join(f"{i['title']} ({i['summary']})" for i in fixture["items"])
                fixture_hint = f"This round's fixture is already known, do not search for it: {games}\n"
        except Exception as e:
            print("fixture failed:", e)
        jobs = claude_sections(fixture_hint)
        with cf.ThreadPoolExecutor(max_workers=len(jobs)) as ex:
            futs = {ex.submit(ask_claude, client, s, usage): s for s in jobs}
            for fut in cf.as_completed(futs):
                s = futs[fut]
                try:
                    data = fut.result()
                except Exception as e:
                    print(f"{s['key']} failed:", e)
                    data = {"items": [], "note": "Couldn't load this section today."}
                data["title"] = s["title"]
                sections[s["key"]] = data

        # Paranormal videos (free sources first)
        vids, reddit_down = reddit_videos()
        yt = youtube_videos()
        try:
            yt = filter_videos(client, prefilter_videos(yt), usage)
        except Exception as e:
            print("video filter failed:", e)
            yt = prefilter_videos(yt)[:8]
        items = yt + vids
        note = ""
        if len(items) < 5:
            # Backup: let Claude search for viral paranormal clips.
            try:
                data = ask_claude(client, PARANORMAL_BACKUP, usage)
                for it in data.get("items", []):
                    it.setdefault("tag", "Web")
                found = [it for it in data.get("items", []) if it.get("url")]
                items += found
                if found:
                    note = "Some of these were found by web search."
            except Exception as e:
                print("paranormal backup failed:", e)
                if reddit_down:
                    note = "Reddit blocked the automatic check today."
        sections["paranormal"] = dict(title="Trending paranormal videos", sub="last 24 to 48 hours",
                                      items=items[:12], note=note)

        # eBay sold cards
        try:
            cards, links, blocked = ebay_sold()
            sections["cards"] = dict(
                title="AFL cards sold on eBay", sub="Teamcoach and Select, 2024 to 2026",
                items=cards, links=links,
                note="eBay blocked the automatic check today. Tap a search below." if blocked else "")
        except Exception as e:
            print("ebay failed:", e)

    os.makedirs(OUT_DIR, exist_ok=True)
    cost = sum(usage)
    with open(os.path.join(OUT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(render(weather, sections, cost))
    print(f"Done. Estimated API cost: US${cost:.3f}")


if __name__ == "__main__":
    build(demo="--demo" in sys.argv)
