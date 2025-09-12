#!/usr/bin/env python3
import os, re, json, hashlib, requests, feedparser, yaml
from datetime import datetime, timezone
from dateutil import parser as dtparse

# Load watch terms
with open("watch_terms.yaml","r",encoding="utf-8") as f:
    TERMS = yaml.safe_load(f)

CORE = set(TERMS.get("core_terms", []))
DIPLO = set(TERMS.get("diplomacy_terms", []))
AIRPORTS = set(TERMS.get("airport_names", []))
EXCLUDE = set(TERMS.get("exclude_terms", []))

# Sources
RSS_FEEDS = [
    "https://www.reuters.com/rssFeed/worldNews",
    "http://feeds.bbci.co.uk/news/world/rss.xml",
    "http://feeds.bbci.co.uk/news/uk/rss.xml",
    "https://apnews.com/hub/apf-topnews?format=rss",
    "https://avherald.com/rss.php",
    "https://www.gov.uk/government/announcements.atom"
]

# Confidence rules
TIER1 = ["reuters.com","bbc.co.uk","apnews.com","gov.uk","avherald.com"]

def now(): return datetime.now(timezone.utc)

def hash_id(s): return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]

def domain(url):
    m = re.search(r"https?://([^/]+)/", url+"/")
    return m.group(1).lower() if m else ""

def should_exclude(text):
    return any(t.lower() in text.lower() for t in EXCLUDE)

def tag_item(title, summary):
    text = (title+" "+summary).lower()
    tags = []
    if any(t.lower() in text for t in CORE): tags.append("airport/security")
    if any(t.lower() in text for t in DIPLO): tags.append("diplomatic")
    for a in AIRPORTS:
        if a.lower() in text: tags.append(a)
    return tags

def confidence(src, tags):
    if any(src.endswith(t) for t in TIER1): return "high"
    if tags: return "medium"
    return "low"

def normalise(entry, feedtitle):
    url = entry.get("link","")
    title = entry.get("title","(no title)")
    summary = entry.get("summary","")
    pub = None
    for k in ("published","updated"):
        if entry.get(k): pub = dtparse.parse(entry[k]); break
    if not pub: pub = now()
    tags = tag_item(title, summary)
    src = domain(url)
    return {
        "id": hash_id(url or title),
        "title": title,
        "url": url,
        "source": feedtitle,
        "published_at": pub.isoformat(),
        "summary": summary,
        "tags": tags,
        "confidence": confidence(src, tags),
        "type": "news"
    }

def collect():
    items = []
    for feed in RSS_FEEDS:
        try:
            d = feedparser.parse(feed)
            for e in d.entries[:50]:
                if should_exclude((e.get("title","")+e.get("summary",""))): continue
                it = normalise(e, d.feed.get("title","rss"))
                if it["tags"]:  # only keep if relevant
                    items.append(it)
        except Exception as ex:
            print("Feed error", feed, ex)
    items.sort(key=lambda x: x["published_at"], reverse=True)
    return items

def main():
    items = collect()
    data = {
        "generated_at": now().isoformat(),
        "items": items[:400],
        "trends": {}
    }
    with open("data.json","w",encoding="utf-8") as f:
        json.dump(data,f,indent=2)
    print("Wrote", len(items), "items")

if __name__=="__main__":
    main()
