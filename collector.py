#!/usr/bin/env python3
"""
Collector: pulls headlines hourly, tags airport/diplomatic relevance,
classifies each item as major news / local news / social, and writes data.json.
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
    """
    Prefer a helpful feed title, otherwise fall back to the domain.
    Trim noisy suffixes like ' – RSS' etc.
    """
    title = (feed_title or "").strip()
    if title:
        title = re.sub(r"\s*[-–—]\s*RSS.*$", "", title, flags=re.I)
        title = re.sub(r"\s*RSS\s*Feed$", "", title, flags=re.I)
        return title
    return domain(url)


# ----------------------------- Config & Data -----------------------------
# Major outlets / wires
MAJOR_DOMAINS = {
    "reuters.com", "bbc.co.uk", "apnews.com", "avherald.com", "gov.uk",
    "theguardian.com", "sky.com", "skynews.com.au", "cnn.com", "nytimes.com",
    "aljazeera.com", "ft.com", "bloomberg.com"
}

# Social sources we can fetch via RSS safely (examples; expand as you like)
SOCIAL_FEEDS = [
    # Reddit (every subreddit has .rss)
    "https://www.reddit.com/r/aviation/.rss",
    "https://www.reddit.com/r/flying/.rss",
    "https://www.reddit.com/r/aviationsafety/.rss",
    "https://www.reddit.com/r/uknews/.rss",

    # Mastodon (tag feed example via mastodon.social)
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

ALIASES = {}
for a in AIRPORTS:
    for alias in a.get("aliases", []) + [a.get("iata", "")]:
        if alias:
            ALIASES[alias.lower()] = {
                "iata": a.get("iata"),
                "name": a.get("name"),
                "city": a.get("city"),
                "country": a.get("country"),
            }


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
    """
    Returns one of: 'major news', 'local news', 'social'
    - If the feed declares 'social', return 'social'
    - Else if domain is in MAJOR_DOMAINS -> major news
    - Else -> local news
    """
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
        geo = {"airport": ap["name"], "city": ap["city"], "country": ap["country"], "iata": ap["iata"]}
        if ap["iata"]:
            item_tags.append(ap["iata"])

    # classification
    item_type = classify_type(url, declared_type, src_dom)

    return {
        "id": hash_id(url or title),
        "title": title,
        "url": url,
        "source": src_name,
        "published_at": pub.isoformat(),
        "summary": summary,
        "tags": sorted(set(item_tags)),
        "type": item_type,              # 'major news' | 'local news' | 'social'
        "geo": geo
    }


# ----------------------------- Collectors -----------------------------
def pull_feed(url: str):
    """Fetch RSS/Atom and return (feedtitle, entries)."""
    d = feedparser.parse(url)
    return d.feed.get("title", domain(url)), d.entries

def collect_block(feed_urls, declared_type: str):
    items = []
    for f in feed_urls:
        try:
            feedtitle, entries = pull_feed(f)
            for e in entries[:60]:
                it = normalise(e, feedtitle, declared_type)
                if it and (("airport/security" in it["tags"]) or ("diplomatic" in it["tags"])):
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

