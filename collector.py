#!/usr/bin/env python3
"""
Collector for the Global Situational Awareness Dashboard.

- Reads feeds from feeds.yaml
- Filters by watch_terms.yaml (keeps items that match airport/security or diplomatic)
- Strips HTML
- Matches airports by alias/IATA and injects geo (iata, city, country) + lat/lon
- Stores BOTH originals and English translations:
    title_orig, summary_orig, lang, title_en, summary_en
- Social posts without a title -> first line of the content as title
- Classifies: major news / local news / social
- De-dupes by newest and writes data.json
"""

import re
import json
import hashlib
from datetime import datetime, timezone

import requests
import feedparser
import yaml
from dateutil import parser as dtparse
from bs4 import BeautifulSoup
from langdetect import detect, LangDetectException
from deep_translator import GoogleTranslator

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

UA = {"User-Agent": "GSA-Collector/1.4 (+https://streamlit.app)"}

def strip_html(raw: str) -> str:
    if not raw:
        return ""
    try:
        return BeautifulSoup(raw, "html.parser").get_text(" ", strip=True)
    except Exception:
        return re.sub(r"<[^>]+>", "", raw or "")

def safe_detect(text: str) -> str:
    try:
        return detect(text) if text and text.strip() else "en"
    except LangDetectException:
        return "en"

def to_english(s: str) -> str:
    if not s:
        return s
    try:
        return GoogleTranslator(source="auto", target="en").translate(s)
    except Exception:
        return s  # best-effort

# ----------------------------- Feeds -----------------------------
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

MAJOR_DOMAINS = {
    "reuters.com","bbc.co.uk","apnews.com","theguardian.com","nytimes.com",
    "bloomberg.com","ft.com","cnn.com","aljazeera.com","sky.com","latimes.com",
    "cbc.ca","theglobeandmail.com","scmp.com","straitstimes.com","japantimes.co.jp",
    "avherald.com","gov.uk","faa.gov","easa.europa.eu","caa.co.uk","ntsb.gov",
    "bea.aero","atsb.gov.au","caa.govt.nz","caa.co.za","tc.gc.ca","noaa.gov",
    "nhc.noaa.gov","weather.gov"
}

# ----------------------------- Watch terms -----------------------------
with open("watch_terms.yaml", "r", encoding="utf-8") as f:
    TERMS = yaml.safe_load(f) or {}
CORE    = set(TERMS.get("core_terms", []))
DIPLO   = set(TERMS.get("diplomacy_terms", []))
EXCLUDE = set(TERMS.get("exclude_terms", []))

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

# ----------------------------- Airports (with lat/lon) -----------------------------
try:
    with open("airports.json", "r", encoding="utf-8") as f:
        AIRPORTS = json.load(f)
except FileNotFoundError:
    AIRPORTS = []

ALIASES = {}     # alias(lower) -> meta
IATA_TO_LL = {}  # IATA(upper) -> (lat, lon)
for a in AIRPORTS:
    meta = {
        "iata": a.get("iata"),
        "name": a.get("name"),
        "city": a.get("city"),
        "country": a.get("country"),
        "lat": a.get("lat", a.get("latitude")),
        "lon": a.get("lon", a.get("longitude")),
    }
    iata = (meta["iata"] or "").upper()
    if iata and isinstance(meta["lat"], (int, float)) and isinstance(meta["lon"], (int, float)):
        IATA_TO_LL[iata] = (meta["lat"], meta["lon"])
    for alias in (a.get("aliases") or []) + [a.get("iata", "")]:
        if alias:
            ALIASES[alias.lower()] = meta

def match_airport(text: str):
    t = (text or "").lower()
    for alias, meta in ALIASES.items():
        if alias and alias in t:
            iata = (meta.get("iata") or "").upper()
            lat, lon = None, None
            if iata and iata in IATA_TO_LL:
                lat, lon = IATA_TO_LL[iata]
            out = {
                "iata": meta.get("iata"),
                "name": meta.get("name"),
                "city": meta.get("city"),
                "country": meta.get("country"),
            }
            if lat is not None and lon is not None:
                out["lat"] = lat
                out["lon"] = lon
            return out
    return None

def classify_type(url: str, declared_type: str, src_domain: str) -> str:
    if (declared_type or "").lower() == "social":
        return "social"
    return "major news" if any(src_domain.endswith(d) for d in MAJOR_DOMAINS) else "local news"

# ----------------------------- Fetch/normalise -----------------------------
def fetch_feed(url: str):
    try:
        r = requests.get(url, headers=UA, timeout=20)
        r.raise_for_status()
        d = feedparser.parse(r.content)
        return d.feed.get("title", get_domain(url)), d.entries
    except Exception as ex:
        print("Feed error:", url, ex)
        return get_domain(url), []

def derive_title(raw_title: str, summary: str) -> str:
    t = strip_html(raw_title or "").strip()
    if t and t.lower() != "(no title)":
        return t
    # first non-empty line up to ~160 chars
    s = (summary or "").strip().splitlines()
    first = next((ln for ln in s if ln.strip()), "")
    return (first[:160] if first else "(no title)")

def normalise(entry, feedtitle: str, declared_type: str):
    url = entry.get("link", "") or entry.get("id", "") or ""
    raw_title = entry.get("title", "") or ""
    raw_summary = entry.get("summary", "") or ""

    # Clean HTML
    summary_clean = strip_html(raw_summary)
    title_clean = derive_title(raw_title, summary_clean)

    # Detect + translate
    lang = safe_detect(f"{title_clean} {summary_clean}")
    title_en = title_clean if lang == "en" else to_english(title_clean)
    summary_en = summary_clean if lang == "en" else to_english(summary_clean)

    text_for_filter = f"{title_en} {summary_en}"
    if should_exclude(text_for_filter):
        return None

    # Time
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

    # Tags & geo (geo ONLY from airport match)
    item_tags = tags_for(text_for_filter)
    geo = {}
    ap = match_airport(text_for_filter)
    if ap:
        geo = {
            "airport": ap.get("name"),
            "city": ap.get("city"),
            "country": ap.get("country"),
            "iata": ap.get("iata"),
        }
        if ap.get("lat") is not None and ap.get("lon") is not None:
            geo["lat"] = ap["lat"]
            geo["lon"] = ap["lon"]
        if ap.get("iata"):
            item_tags.append(ap["iata"])
        if ap.get("country"):
            item_tags.append(ap["country"])

    # Keep only relevant
    if not (("airport/security" in item_tags) or ("diplomatic" in item_tags)):
        return None

    item_type = classify_type(url, declared_type, src_dom)
    item_tags = sorted(set(item_tags))

    return {
        "id": sha1_16(url or title_en),
        # originals + translations
        "title_orig": title_clean,
        "summary_orig": summary_clean,
        "lang": lang,
        "title_en": title_en,
        "summary_en": summary_en,
        # legacy convenience (English by default)
        "title": title_en,
        "summary": summary_en,

        "url": url,
        "source": src_name,
        "published_at": pub.isoformat(),
        "tags": item_tags,
        "type": item_type,
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

    # De-dupe newest
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

