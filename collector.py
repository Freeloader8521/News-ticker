#!/usr/bin/env python3
"""
Collector: builds data.json for the Global Situational Awareness Dashboard.

- Loads feeds from feeds.yaml
- Filters by watch_terms.yaml (airport/security/diplomatic + weather/airspace terms)
- Enriches geo from airports.json (IATA/aliases) or country aliases
- Classifies items: 'major news' | 'local news' | 'social'
- De-dupes, sorts by time, writes data.json
"""

import re
import json
import hashlib
from datetime import datetime, timezone

import requests
import feedparser
import yaml
from dateutil import parser as dtparse


# ----------------------------- Basics -----------------------------
def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def sha1_16(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]

def get_domain(url: str) -> str:
    m = re.search(r"https?://([^/]+)", url or "")
    return (m.group(1).lower() if m else "").replace("www.", "")

def clean_source(feed_title: str, url: str) -> str:
    t = (feed_title or "").strip()
    if t:
        t = re.sub(r"\s*[-–—]\s*RSS.*$", "", t, flags=re.I)
        t = re.sub(r"\s*RSS\s*Feed.*$", "", t, flags=re.I)
        return t
    return get_domain(url)

UA = {"User-Agent": "GSA-Collector/1.0 (+https://streamlit.app)"}


# ----------------------------- Config: feeds -----------------------------
try:
    with open("feeds.yaml", "r", encoding="utf-8") as f:
        FEEDS = yaml.safe_load(f) or {}
except FileNotFoundError:
    FEEDS = {}

NEWS_FEEDS     = FEEDS.get("news", [])
AUTH_FEEDS     = FEEDS.get("aviation_authorities", [])
OFFICIAL_FEEDS = FEEDS.get("official_announcements", [])
WEATHER_FEEDS  = FEEDS.get("weather_alerts", [])
SOCIAL_FEEDS   = FEEDS.get("social", [])

# Major outlets / official domains we treat as 'major news'
MAJOR_DOMAINS = {
    # Wires / papers / broadcasters
    "reuters.com","bbc.co.uk","apnews.com","theguardian.com","nytimes.com",
    "bloomberg.com","ft.com","cnn.com","aljazeera.com","sky.com","latimes.com",
    "cbc.ca","theglobeandmail.com","scmp.com","straitstimes.com","japantimes.co.jp",
    # Aviation specialist & official
    "avherald.com","gov.uk","faa.gov","easa.europa.eu","caa.co.uk","ntsb.gov",
    "bea.aero","atsb.gov.au","caa.govt.nz","caa.co.za","tc.gc.ca","noaa.gov",
    "nhc.noaa.gov","weather.gov"
}


# ----------------------------- Config: watch terms -----------------------------
with open("watch_terms.yaml", "r", encoding="utf-8") as f:
    TERMS = yaml.safe_load(f) or {}

CORE   = set(TERMS.get("core_terms", []))
DIPLO  = set(TERMS.get("diplomacy_terms", []))
EXCLUDE= set(TERMS.get("exclude_terms", []))

# ----------------------------- Config: airports -----------------------------
try:
    with open("airports.json", "r", encoding="utf-8") as f:
        AIRPORTS = json.load(f)
except FileNotFoundError:
    AIRPORTS = []

# alias/iata -> airport meta
ALIASES = {}
for a in AIRPORTS:
    for alias in (a.get("aliases") or []) + [a.get("iata", "")]:
        if alias:
            ALIASES[alias.lower()] = {
                "iata": a.get("iata"),
                "name": a.get("name"),
                "city": a.get("city"),
                "country": a.get("country"),
            }

# ----------------------------- Country aliases (expandable) -----------------------------
COUNTRY_ALIASES = {
    # UK & variants
    "united kingdom":"United Kingdom","uk":"United Kingdom","u.k.":"United Kingdom",
    "britain":"United Kingdom","great britain":"United Kingdom",
    "england":"United Kingdom","scotland":"United Kingdom","wales":"United Kingdom",
    "northern ireland":"United Kingdom","london":"United Kingdom",
    # Europe (sample + capitals)
    "france":"France","paris":"France",
    "germany":"Germany","berlin":"Germany","frankfurt":"Germany",
    "netherlands":"Netherlands","holland":"Netherlands","amsterdam":"Netherlands",
    "spain":"Spain","madrid":"Spain","barcelona":"Spain",
    "italy":"Italy","rome":"Italy","milan":"Italy",
    "ireland":"Ireland","dublin":"Ireland",
    "switzerland":"Switzerland","zurich":"Switzerland",
    "austria":"Austria","vienna":"Austria",
    "belgium":"Belgium","brussels":"Belgium",
    "poland":"Poland","warsaw":"Poland",
    "greece":"Greece","athens":"Greece",
    "türkiye":"Türkiye","turkey":"Türkiye","istanbul":"Türkiye",
    # Middle East
    "united arab emirates":"United Arab Emirates","uae":"United Arab Emirates",
    "dubai":"United Arab Emirates","abu dhabi":"United Arab Emirates",
    "qatar":"Qatar","doha":"Qatar",
    "saudi arabia":"Saudi Arabia","riyadh":"Saudi Arabia",
    "israel":"Israel","tel aviv":"Israel",
    # Asia-Pacific
    "singapore":"Singapore","hong kong":"Hong Kong",
    "china":"China","beijing":"China","shanghai":"China","guangzhou":"China",
    "japan":"Japan","tokyo":"Japan","osaka":"Japan",
    "south korea":"South Korea","korea":"South Korea","seoul":"South Korea",
    "india":"India","delhi":"India","mumbai":"India","bangalore":"India",
    "thailand":"Thailand","bangkok":"Thailand",
    "malaysia":"Malaysia","kuala lumpur":"Malaysia",
    "philippines":"Philippines","manila":"Philippines",
    "indonesia":"Indonesia","jakarta":"Indonesia",
    "australia":"Australia","sydney":"Australia","melbourne":"Australia",
    "new zealand":"New Zealand","auckland":"New Zealand",
    # Americas
    "united states":"United States","u.s.":"United States","usa":"United States","us":"United States",
    "washington":"United States","new york":"United States","los angeles":"United States","miami":"United States",
    "canada":"Canada","toronto":"Canada","vancouver":"Canada","montreal":"Canada",
    "mexico":"Mexico","brazil":"Brazil","rio":"Brazil","sao paulo":"Brazil",
    "argentina":"Argentina","buenos aires":"Argentina","chile":"Chile","santiago":"Chile",
    # Africa
    "south africa":"South Africa","johannesburg":"South Africa","cape town":"South Africa",
    "kenya":"Kenya","nairobi":"Kenya",
    "egypt":"Egypt","cairo":"Egypt",
    "nigeria":"Nigeria","lagos":"Nigeria",
    "ghana":"Ghana","accra":"Ghana",
}

# ----------------------------- Relevance & enrichment -----------------------------
def should_exclude(text: str) -> bool:
    t = (text or "").lower()
    return any(x.lower() in t for x in EXCLUDE)

def tags_for(text: str):
    t = (text or "").lower()
    out = []
    if any(x.lower() in t for x in CORE):
        out.append("airport/security")
    if any(x.lower() in t for x in DIPLO):
        out.append("diplomatic")
    return out

def match_airport(text: str):
    t = (text or "").lower()
    for alias, meta in ALIASES.items():
        if alias and alias in t:
            return meta
    return None

def detect_country(text: str):
    t = (text or "").lower()
    for needle, canon in COUNTRY_ALIASES.items():
        if needle in t:
            return canon
    return None

def classify_type(url: str, declared_type: str, src_domain: str) -> str:
    if (declared_type or "").lower() == "social":
        return "social"
    return "major news" if any(src_domain.endswith(d) for d in MAJOR_DOMAINS) else "local news"


# ----------------------------- Fetch & parse -----------------------------
def fetch_feed(url: str):
    """Fetch with requests (so we can set UA), then parse with feedparser."""
    try:
        r = requests.get(url, headers=UA, timeout=20)
        r.raise_for_status()
        d = feedparser.parse(r.content)
        return d.feed.get("title", get_domain(url)), d.entries
    except Exception as ex:
        print("Feed error:", url, ex)
        return get_domain(url), []

def normalise(entry, feedtitle: str, declared_type: str):
    url = entry.get("link", "") or entry.get("id", "") or ""
    title = entry.get("title", "") or "(no title)"
    summary = entry.get("summary", "") or ""
    text = f"{title} {summary}"

    if should_exclude(text):
        return None

    # time
    pub = None
    for k in ("published", "updated", "created"):
        if entry.get(k):
            try:
                pub = dtparse.parse(entry[k]).astimezone(timezone.utc)
                break
            except Exception:
                pass
    if not pub:
        pub = now_utc()

    src_dom = get_domain(url)
    src_name = clean_source(feedtitle, url)

    # tags & geo
    item_tags = tags_for(text)

    geo = {}
    ap = match_airport(text)
    if ap:
        # Airport match → full geo + IATA + country tag
        geo = {"airport": ap["name"], "city": ap["city"], "country": ap["country"], "iata": ap["iata"]}
        if ap.get("iata"):
            item_tags.append(ap["iata"])
        if ap.get("country"):
            item_tags.append(ap["country"])
    else:
        # No airport → try country mention and tag it
        ct = detect_country(text)
        if ct:
            geo = {"country": ct}
            item_tags.append(ct)

    # Only keep relevant items
    if not (("airport/security" in item_tags) or ("diplomatic" in item_tags)):
        return None

    item_type = classify_type(url, declared_type, src_dom)
    item_tags = sorted(set(item_tags))

    return {
        "id": sha1_16(url or title),
        "title": title,
        "url": url,
        "source": src_name,
        "published_at": pub.isoformat(),
        "summary": summary,
        "tags": item_tags,
        "type": item_type,   # 'major news' | 'local news' | 'social'
        "geo": geo
    }


# ----------------------------- Collect -----------------------------
def collect_block(feed_urls, declared_type: str, per_feed_limit: int = 80):
    items = []
    for f in feed_urls:
        feedtitle, entries = fetch_feed(f)
        for e in entries[:per_feed_limit]:
            it = normalise(e, feedtitle, declared_type)
            if it:
                items.append(it)
    return items

def collect_all():
    items = []
    items += collect_block(NEWS_FEEDS, "news")
    items += collect_block(AUTH_FEEDS, "news")
    items += collect_block(OFFICIAL_FEEDS, "news")
    items += collect_block(WEATHER_FEEDS, "news")
    items += collect_block(SOCIAL_FEEDS, "social")

    # De-duplicate by id, keep newest
    best = {}
    for it in items:
        k = it["id"]
        if (k not in best) or (it["published_at"] > best[k]["published_at"]):
            best[k] = it
    out = list(best.values())
    out.sort(key=lambda x: x["published_at"], reverse=True)
    return out[:500]


# ----------------------------- Main -----------------------------
def main():
    items = collect_all()
    data = {"generated_at": now_utc().isoformat(), "items": items, "trends": {}}
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Wrote data.json with {len(items)} items")

if __name__ == "__main__":
    main()


