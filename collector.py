#!/usr/bin/env python3
"""
Collector: pulls headlines hourly, tags relevance (airport/diplomatic),
infers geo from airport (IATA) OR country mentions, classifies items,
and writes data.json for the Streamlit app.
"""

import re
import json
import hashlib
from datetime import datetime, timezone

import requests
import feedparser
import yaml
from dateutil import parser as dtparse


# ----------------------------- Utils -----------------------------
def now() -> datetime:
    return datetime.now(timezone.utc)

def hash_id(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]

def domain(url: str) -> str:
    m = re.search(r"https?://([^/]+)/?", url or "")
    return m.group(1).lower().replace("www.", "") if m else ""

def clean_source(feed_title: str, url: str) -> str:
    title = (feed_title or "").strip()
    if title:
        title = re.sub(r"\s*[-–—]\s*RSS.*$", "", title, flags=re.I)
        title = re.sub(r"\s*RSS\s*Feed$", "", title, flags=re.I)
        return title
    return domain(url)


# ----------------------------- Config & Data -----------------------------
# Major outlets / wires (extend any time)
MAJOR_DOMAINS = {
    "reuters.com", "bbc.co.uk", "apnews.com", "avherald.com", "gov.uk",
    "theguardian.com", "sky.com", "cnn.com", "nytimes.com", "aljazeera.com",
    "ft.com", "bloomberg.com"
}

# Social via RSS (safe examples; extend freely)
SOCIAL_FEEDS = [
    "https://www.reddit.com/r/aviation/.rss",
    "https://www.reddit.com/r/flying/.rss",
    "https://www.reddit.com/r/aviationsafety/.rss",
    "https://www.reddit.com/r/uknews/.rss",
    "https://mastodon.social/tags/aviation.rss",
    "https://mastodon.social/tags/airport.rss",
]

# News feeds (global wires + UK + gov + aviation specialist)
NEWS_FEEDS = [
    "https://www.reuters.com/rssFeed/worldNews",
    "http://feeds.bbci.co.uk/news/world/rss.xml",
    "http://feeds.bbci.co.uk/news/uk/rss.xml",
    "https://apnews.com/hub/apf-topnews?format=rss",
    "https://avherald.com/rss.php",
    "https://www.gov.uk/government/announcements.atom",
]

# Watch terms for relevance
with open("watch_terms.yaml", "r", encoding="utf-8") as f:
    TERMS = yaml.safe_load(f) or {}
CORE = set(TERMS.get("core_terms", []))
DIPLO = set(TERMS.get("diplomacy_terms", []))
EXCLUDE = set(TERMS.get("exclude_terms", []))

# Airport reference for geo enrichment
try:
    with open("airports.json", "r", encoding="utf-8") as f:
        AIRPORTS = json.load(f)
except FileNotFoundError:
    AIRPORTS = []

# Map alias (and IATA codes) -> airport meta
ALIASES = {}
for a in AIRPORTS:
    for alias in (a.get("aliases", []) or []) + [a.get("iata", "")]:
        if alias:
            ALIASES[alias.lower()] = {
                "iata": a.get("iata"),
                "name": a.get("name"),
                "city": a.get("city"),
                "country": a.get("country"),
            }

# Country aliases -> canonical name (keep in sync with flags in the app)
COUNTRY_ALIASES = {
    # United Kingdom variants
    "united kingdom": "United Kingdom",
    "uk": "United Kingdom",
    "u.k.": "United Kingdom",
    "britain": "United Kingdom",
    "great britain": "United Kingdom",
    "england": "United Kingdom",
    "scotland": "United Kingdom",
    "wales": "United Kingdom",
    "northern ireland": "United Kingdom",

    # Europe
    "france": "France",
    "germany": "Germany",
    "netherlands": "Netherlands",
    "holland": "Netherlands",
    "spain": "Spain",
    "catalonia": "Spain",
    "italy": "Italy",
    "ireland": "Ireland",
    "switzerland": "Switzerland",
    "austria": "Austria",
    "belgium": "Belgium",
    "luxembourg": "Luxembourg",
    "denmark": "Denmark",
    "norway": "Norway",
    "sweden": "Sweden",
    "finland": "Finland",
    "iceland": "Iceland",
    "poland": "Poland",
    "czech republic": "Czech Republic",
    "czechia": "Czech Republic",
    "slovakia": "Slovakia",
    "hungary": "Hungary",
    "romania": "Romania",
    "bulgaria": "Bulgaria",
    "greece": "Greece",
    "turkey": "Türkiye",
    "türkiye": "Türkiye",
    "croatia": "Croatia",
    "slovenia": "Slovenia",

    # Middle East
    "united arab emirates": "United Arab Emirates",
    "uae": "United Arab Emirates",
    "dubai": "United Arab Emirates",
    "abu dhabi": "United Arab Emirates",
    "qatar": "Qatar",
    "doha": "Qatar",
    "saudi arabia": "Saudi Arabia",
    "riyadh": "Saudi Arabia",
    "iran": "Iran",
    "iraq": "Iraq",
    "jordan": "Jordan",
    "lebanon": "Lebanon",
    "israel": "Israel",
    "palestine": "Palestine",

    # Asia-Pacific
    "singapore": "Singapore",
    "hong kong": "Hong Kong",
    "china": "China",
    "prc": "China",
    "beijing": "China",
    "shanghai": "China",
    "japan": "Japan",
    "tokyo": "Japan",
    "osaka": "Japan",
    "south korea": "South Korea",
    "korea": "South Korea",
    "seoul": "South Korea",
    "north korea": "North Korea",
    "india": "India",
    "delhi": "India",
    "mumbai": "India",
    "thailand": "Thailand",
    "bangkok": "Thailand",
    "malaysia": "Malaysia",
    "kuala lumpur": "Malaysia",
    "philippines": "Philippines",
    "manila": "Philippines",
    "indonesia": "Indonesia",
    "jakarta": "Indonesia",
    "australia": "Australia",
    "sydney": "Australia",
    "melbourne": "Australia",
    "new zealand": "New Zealand",
    "auckland": "New Zealand",

    # Americas
    "united states": "United States",
    "u.s.": "United States",
    "usa": "United States",
    "us": "United States",
    "washington": "United States",
    "america": "United States",
    "canada": "Canada",
    "toronto": "Canada",
    "vancouver": "Canada",
    "mexico": "Mexico",
    "brazil": "Brazil",
    "rio": "Brazil",
    "são paulo": "Brazil",
    "argentina": "Argentina",
    "buenos aires": "Argentina",
    "chile": "Chile",
    "santiago": "Chile",

    # Africa
    "south africa": "South Africa",
    "johannesburg": "South Africa",
    "cape town": "South Africa",
    "kenya": "Kenya",
    "nairobi": "Kenya",
    "egypt": "Egypt",
    "cairo": "Egypt",
    "nigeria": "Nigeria",
    "lagos": "Nigeria",
    "ghana": "Ghana",
    "accra": "Ghana",
}

def detect_country(text: str):
    t = (text or "").lower()
    for needle, canon in COUNTRY_ALIASES.items():
        if needle in t:
            return canon
    return None


# ----------------------------- Relevance & Enrichment -----------------------------
def should_exclude(text: str) -> bool:
    t = (text or "").lower()
    return any(x.lower() in t for x in EXCLUDE)

def tags_for(text: str):
    t = (text or "").lower()
    tags = []
    if any(x.lower() in t for x in CORE):
        tags.append("airport/security")
    if any(x.lower() in t for x in DIPLO):
        tags.append("diplomatic")
    return tags

def match_airport(text: str):
    t = (text or "").lower()
    for alias, meta in ALIASES.items():
        if alias and alias in t:
            return meta
    return None

def classify_type(url: str, declared_type: str, src_domain: str) -> str:
    if (declared_type or "").lower() == "social":
        return "social"
    if any(src_domain.endswith(d) for d in MAJOR_DOMAINS):
        return "major news"
    return "local news"


# ----------------------------- Normalisation -----------------------------
def normalise(entry, feedtitle: str, declared_type: str):
    url = entry.get("link", "") or entry.get("id", "")
    title = entry.get("title", "") or "(no title)"
    summary = entry.get("summary", "") or ""
    if should_exclude(title + " " + summary):
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
        pub = now()

    src_dom = domain(url)
    src_name = clean_source(feedtitle, url)

    # tags & geo
    item_tags = tags_for(f"{title} {summary}")

    geo = {}
    ap = match_airport(f"{title} {summary}")
    if ap:
        # Airport match → full geo + IATA tag
        geo = {"airport": ap["name"], "city": ap["city"], "country": ap["country"], "iata": ap["iata"]}
        if ap.get("iata"):
            item_tags.append(ap["iata"])
    else:
        # No airport → try country mention
        ct = detect_country(f"{title} {summary}")
        if ct:
            geo = {"country": ct}

    item_type = classify_type(url, declared_type, src_dom)

    # Only keep items that are relevant to the brief
    if not (("airport/security" in item_tags) or ("diplomatic" in item_tags)):
        return None

    return {
        "id": hash_id(url or title),
        "title": title,
        "url": url,
        "source": src_name,
        "published_at": pub.isoformat(),
        "summary": summary,
        "tags": sorted(set(item_tags)),
        "type": item_type,              # 'major news' | 'local news' | 'social'
        "geo": geo                      # may be {country: ...} even without airport
    }


# ----------------------------- Collectors -----------------------------
def pull_feed(url: str):
    d = feedparser.parse(url)
    return d.feed.get("title", domain(url)), d.entries

def collect_block(feed_urls, declared_type: str):
    items = []
    for f in feed_urls:
        try:
            feedtitle, entries = pull_feed(f)
            for e in entries[:60]:
                it = normalise(e, feedtitle, declared_type)
                if it:
                    items.append(it)
        except Exception as ex:
            print("Feed error:", f, ex)
    return items

def collect_all():
    items = []
    items += collect_block(NEWS_FEEDS, "news")
    items += collect_block(SOCIAL_FEEDS, "social")

    # De-duplicate by id, keep newest
    dedup = {}
    for it in items:
        k = it["id"]
        if (k not in dedup) or (it["published_at"] > dedup[k]["published_at"]):
            dedup[k] = it
    out = list(dedup.values())
    out.sort(key=lambda x: x["published_at"], reverse=True)
    return out[:500]


# ----------------------------- Main -----------------------------
def main():
    items = collect_all()
    data = {"generated_at": now().isoformat(), "items": items, "trends": {}}
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Wrote data.json with {len(items)} items")

if __name__ == "__main__":
    main()

