#!/usr/bin/env python3
import os, re, json, hashlib, requests, feedparser, yaml
from datetime import datetime, timezone
from dateutil import parser as dtparse

# ------------ config / data ------------
def now(): return datetime.now(timezone.utc)
def hash_id(s): return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]
def domain(url):
    m = re.search(r"https?://([^/]+)/", url + "/")
    return m.group(1).lower() if m else ""

# watch terms
with open("watch_terms.yaml","r",encoding="utf-8") as f:
    TERMS = yaml.safe_load(f) or {}

CORE = set(TERMS.get("core_terms", []))
DIPLO = set(TERMS.get("diplomacy_terms", []))
EXCLUDE = set(TERMS.get("exclude_terms", []))

# airport reference
with open("airports.json","r",encoding="utf-8") as f:
    AIRPORTS = json.load(f)

# build alias -> meta map
ALIASES = {}
for a in AIRPORTS:
    for alias in a.get("aliases", []) + [a.get("iata","")]:
        if alias:
            ALIASES[alias.lower()] = {
                "iata": a.get("iata"),
                "name": a.get("name"),
                "city": a.get("city"),
                "country": a.get("country")
            }

RSS_FEEDS = [
    "https://www.reuters.com/rssFeed/worldNews",
    "http://feeds.bbci.co.uk/news/world/rss.xml",
    "http://feeds.bbci.co.uk/news/uk/rss.xml",
    "https://apnews.com/hub/apf-topnews?format=rss",
    "https://avherald.com/rss.php",
    "https://www.gov.uk/government/announcements.atom"
]

TIER1 = ["reuters.com","bbc.co.uk","apnews.com","gov.uk","avherald.com", "police.uk"]

# ------------ helpers ------------
def should_exclude(text: str) -> bool:
    t = text.lower()
    return any(x.lower() in t for x in EXCLUDE)

def tags_for(text: str):
    t = text.lower()
    tags = []
    if any(x.lower() in t for x in CORE): tags.append("airport/security")
    if any(x.lower() in t for x in DIPLO): tags.append("diplomatic")
    return tags

def match_airport(text: str):
    t = text.lower()
    for alias, meta in ALIASES.items():
        if alias and alias in t:
            return meta
    return None

def confidence(url_domain: str, tags) -> str:
    if any(url_domain.endswith(d) for d in TIER1): return "high"
    if tags: return "medium"
    return "low"

def normalise(entry, feedtitle):
    url = entry.get("link","")
    title = entry.get("title","") or "(no title)"
    summary = entry.get("summary","")
    if should_exclude(title + " " + summary):
        return None
    # time
    pub = None
    for k in ("published","updated","created"):
        if entry.get(k):
            try:
                pub = dtparse.parse(entry[k]).astimezone(timezone.utc)
                break
            except Exception:
                pass
    if not pub: pub = now()

    full_text = f"{title} {summary}"
    item_tags = tags_for(full_text)

    # airport geo
    geo = {}
    ap = match_airport(full_text)
    if ap:
        geo = {"airport": ap["name"], "city": ap["city"], "country": ap["country"], "iata": ap["iata"]}
        # add IATA as a tag so you can filter
        item_tags.append(ap["iata"])

    src_dom = domain(url)
    conf = confidence(src_dom, item_tags)

    return {
        "id": hash_id(url or title),
        "title": title,
        "url": url,
        "source": feedtitle or src_dom,
        "published_at": pub.isoformat(),
        "summary": summary,
        "tags": sorted(set(item_tags)),
        "confidence": conf,
        "type": "news",
        "geo": geo
    }

# ------------ collect & write ------------
def collect():
    items = []
    for feed in RSS_FEEDS:
        try:
            d = feedparser.parse(feed)
            for e in d.entries[:60]:
                it = normalise(e, d.feed.get("title","rss"))
                if it and it["tags"]:   # keep only relevant
                    items.append(it)
        except Exception as ex:
            print("Feed error", feed, ex)
    items.sort(key=lambda x: x["published_at"], reverse=True)
    return items[:400]

def main():
    items = collect()
    data = {"generated_at": now().isoformat(), "items": items, "trends": {}}
    with open("data.json","w",encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Wrote data.json with {len(items)} items")

if __name__ == "__main__":
    main()
