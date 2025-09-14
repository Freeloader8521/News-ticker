#!/usr/bin/env python3
"""
Collector for the Global Situational Awareness Dashboard.

- Loads feeds from feeds.yaml (+ feeds-extra.yaml if present)
- Optional sharding via env: SHARD_INDEX, TOTAL_SHARDS (1-based)
- Merges & fetches feeds, writing progress to status.json
- Normalises items: HTML strip, language detect, EN translate
- Airport matching (aliases + IATA) to inject geo {iata,lat,lon,...}
- Tagging via watch_terms.yaml
- De-dupes by newest and writes data.json
"""

from __future__ import annotations
import os
import re
import json
import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

import requests
import feedparser
import yaml
from bs4 import BeautifulSoup
from dateutil import parser as dtparse
from langdetect import detect, LangDetectException
from deep_translator import GoogleTranslator

# ----------------------------- Config -----------------------------

APP_NAME = "GSA-Collector"
APP_VER  = "1.8"
UA = {"User-Agent": f"{APP_NAME}/{APP_VER} (+https://streamlit.app)"}

# Files we write
DATA_FILE   = "data.json"
STATUS_FILE = "status.json"

# Env toggles
SHARD_INDEX   = int(os.environ.get("SHARD_INDEX", "1"))  # 1-based
TOTAL_SHARDS  = int(os.environ.get("TOTAL_SHARDS", "1"))
PER_FEED_LIMIT = int(os.environ.get("PER_FEED_LIMIT", "80"))  # max entries read per feed

# Domains considered "major" for type classification
MAJOR_DOMAINS = {
    "reuters.com","bbc.co.uk","apnews.com","theguardian.com","nytimes.com",
    "bloomberg.com","ft.com","cnn.com","aljazeera.com","sky.com","latimes.com",
    "cbc.ca","theglobeandmail.com","scmp.com","straitstimes.com","japantimes.co.jp",
    "avherald.com","gov.uk","faa.gov","easa.europa.eu","caa.co.uk","ntsb.gov",
    "bea.aero","atsb.gov.au","caa.govt.nz","caa.co.za","tc.gc.ca","noaa.gov",
    "nhc.noaa.gov","weather.gov"
}

# Explicitly blocked (spam/self-promo etc.)
BLOCKED_DOMAINS = {
    "bigorre.org", "www.bigorre.org",
}

# ----------------------------- Logging -----------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("collector")

# ----------------------------- Small utils -----------------------------

def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()

def sha1_16(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]

def get_domain(url: str) -> str:
    m = re.search(r"https?://([^/]+)", url or "")
    return (m.group(1).lower() if m else "").replace("www.", "")

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
        return s  # best effort

def clean_source(feed_title: str, url: str) -> str:
    t = (feed_title or "").strip()
    if t:
        t = re.sub(r"\s*[-–—]\s*RSS.*$", "", t, flags=re.I)
        t = re.sub(r"\s*RSS\s*Feed.*$", "", t, flags=re.I)
        return t
    return get_domain(url)

# ----------------------------- Status I/O -----------------------------

def write_status(obj: Dict[str, Any]) -> None:
    try:
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
    except Exception as ex:
        log.warning("Could not write status.json: %s", ex)

def set_status_note(note: str) -> None:
    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            st = json.load(f)
    except Exception:
        st = {}
    st["note"] = note
    write_status(st)

# ----------------------------- Load config & terms -----------------------------

def load_yaml(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}

# Main feeds (curated)
FEEDS = load_yaml("feeds.yaml")
NEWS_FEEDS     = FEEDS.get("news", [])
AUTH_FEEDS     = FEEDS.get("aviation_auth", [])
OFFICIAL_FEEDS = FEEDS.get("official_announcements", [])
WEATHER_FEEDS  = FEEDS.get("weather_alerts", [])
SOCIAL_FEEDS   = FEEDS.get("social", [])

# Optional extra feeds discovered elsewhere
EXTRA = load_yaml("feeds-extra.yaml")
NEWS_FEEDS = list(NEWS_FEEDS) + list(EXTRA.get("news_extra", []))

# Watch terms for tagging
TERMS  = load_yaml("watch_terms.yaml")
CORE   = set(TERMS.get("core_terms", []))
DIPLO  = set(TERMS.get("diplomacy_terms", []))
EXCLUDE= set(TERMS.get("exclude_terms", []))

def should_exclude(text: str) -> bool:
    t = (text or "").lower()
    return any(x.lower() in t for x in EXCLUDE)

def tags_for(text: str) -> List[str]:
    t = (text or "").lower()
    out: List[str] = []
    if any(x.lower() in t for x in CORE):
        out.append("airport/security")
    if any(x.lower() in t for x in DIPLO):
        out.append("diplomatic")
    return out

# ----------------------------- Airports -----------------------------

try:
    with open("airports.json", "r", encoding="utf-8") as f:
        AIRPORTS = json.load(f)
except FileNotFoundError:
    AIRPORTS = []

ALIASES: Dict[str, Dict[str, Any]] = {}     # alias(lower) -> meta
IATA_TO_LL: Dict[str, Tuple[float,float]] = {}

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
    lat, lon = meta.get("lat"), meta.get("lon")
    if iata and isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        IATA_TO_LL[iata] = (lat, lon)
    for alias in (a.get("aliases") or []) + [a.get("iata", "")]:
        if alias:
            ALIASES[alias.lower()] = meta

# Require nearby “airport/intl/terminal” context for bare IATA
AIRPORT_CONTEXT = re.compile(r"\b(airport|intl|international|terminal|airfield|aerodrome)s?\b", re.I)

def _has_airport_ctx(text: str, pos: int, window: int = 48) -> bool:
    start = max(0, pos - window)
    end   = min(len(text), pos + window)
    return bool(AIRPORT_CONTEXT.search(text[start:end]))

def match_airport(text: str):
    if not text:
        return None
    tl = text.lower()
    tu = text.upper()

    # 1) Prefer full-name aliases (“Istanbul Airport”, “Heathrow”)
    for alias, meta in ALIASES.items():
        if not alias:
            continue
        if len(alias) == 3 and alias.isalpha():
            continue  # pure IATA handled below
        for m in re.finditer(rf"\b{re.escape(alias)}\b", tl):
            pos = m.start()
            if ("airport" in alias) or _has_airport_ctx(tl, pos):
                iata = (meta.get("iata") or "").upper()
                out = {
                    "iata": iata or None,
                    "name": meta.get("name"),
                    "city": meta.get("city"),
                    "country": meta.get("country"),
                }
                lat, lon = meta.get("lat"), meta.get("lon")
                if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
                    out["lat"], out["lon"] = lat, lon
                elif iata and iata in IATA_TO_LL:
                    out["lat"], out["lon"] = IATA_TO_LL[iata]
                return out

    # 2) Bare IATA tokens, only if airport-context nearby
    for m in re.finditer(r"\b([A-Z]{3})\b", tu):
        tok = m.group(1)
        if tok in IATA_TO_LL and _has_airport_ctx(tl, m.start()):
            lat, lon = IATA_TO_LL[tok]
            meta = next((a for a in AIRPORTS if (a.get("iata") or "").upper() == tok), None)
            return {
                "iata": tok,
                "name": meta.get("name") if meta else None,
                "city": meta.get("city") if meta else None,
                "country": meta.get("country") if meta else None,
                "lat": lat, "lon": lon,
            }
    return None

# ----------------------------- Fetch/normalise -----------------------------

def fetch_feed(url: str) -> Tuple[str, List[Any]]:
    try:
        dom = get_domain(url)
        if dom in BLOCKED_DOMAINS:
            return dom, []
        r = requests.get(url, headers=UA, timeout=25)
        r.raise_for_status()
        d = feedparser.parse(r.content)
        return d.feed.get("title", dom), d.entries
    except Exception as ex:
        log.warning("Feed error %s: %s", url, ex)
        return get_domain(url), []

def derive_title(raw_title: str, summary: str) -> str:
    t = strip_html(raw_title or "").strip()
    if t and t.lower() != "(no title)":
        return t
    lines = [ln.strip() for ln in (summary or "").splitlines() if ln.strip()]
    return lines[0][:160] if lines else "(no title)"

def classify_type(url: str, declared: str, src_dom: str) -> str:
    if (declared or "").lower() == "social":
        return "social"
    return "major news" if any(src_dom.endswith(d) for d in MAJOR_DOMAINS) else "local news"

def normalise(entry, feedtitle: str, declared_type: str):
    url = entry.get("link", "") or entry.get("id", "") or ""
    summary_clean = strip_html(entry.get("summary", ""))
    title_clean   = derive_title(entry.get("title", ""), summary_clean)

    # Language & translation
    lang = safe_detect(f"{title_clean} {summary_clean}")
    title_en   = title_clean if lang == "en" else to_english(title_clean)
    summary_en = summary_clean if lang == "en" else to_english(summary_clean)

    # text for filters
    text_en = f"{title_en} {summary_en}"
    if should_exclude(text_en):
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

    src_dom  = get_domain(url)
    if src_dom in BLOCKED_DOMAINS:
        return None
    src_name = clean_source(feedtitle, url)

    # Tags & geo
    tags = tags_for(text_en)
    geo = {}
    ap = match_airport(text_en)
    if ap:
        geo = {
            "airport": ap.get("name"),
            "city": ap.get("city"),
            "country": ap.get("country"),
            "iata": ap.get("iata"),
        }
        if ap.get("lat") is not None and ap.get("lon") is not None:
            geo["lat"], geo["lon"] = ap["lat"], ap["lon"]
        if ap.get("iata"):
            tags.append(ap["iata"])
        if ap.get("country"):
            tags.append(ap["country"])

    # Keep only relevant (airport/security or diplomacy)
    if not (("airport/security" in tags) or ("diplomatic" in tags)):
        return None

    item_type = classify_type(url, declared_type, src_dom)
    tags = sorted(set(tags))

    return {
        "id": sha1_16(url or title_en),
        # store originals + translations for UI toggle
        "title_orig": title_clean, "summary_orig": summary_clean, "lang": lang,
        "title_en": title_en, "summary_en": summary_en,
        # legacy convenience (default EN)
        "title": title_en, "summary": summary_en,
        "url": url, "source": src_name, "published_at": pub.isoformat(),
        "tags": tags, "type": item_type, "geo": geo
    }

# ----------------------------- Sharding helpers -----------------------------

def shard(items: List[str], shard_index: int, total_shards: int) -> List[str]:
    if total_shards <= 1:
        return items
    shard_index = max(1, min(shard_index, total_shards))
    return [u for i, u in enumerate(items) if (i % total_shards) == (shard_index - 1)]

# ----------------------------- Collect -----------------------------

def collect_block(feed_urls: List[str], declared_type: str,
                  status_prefix: str, per_feed_limit: int) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    total = len(feed_urls)
    done = 0
    for url in feed_urls:
        done += 1
        write_status({
            "started_at": iso(STARTED_AT),
            "total": total, "done": done,
            "current": get_domain(url),
            "note": f"{status_prefix}: {done}/{total}",
            "version": APP_VER
        })
        feedtitle, entries = fetch_feed(url)
        for e in entries[:per_feed_limit]:
            it = normalise(e, feedtitle, declared_type)
            if it:
                items.append(it)
    return items

def collect_all() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []

    # NEWS shardable
    news_urls = shard(list(dict.fromkeys(NEWS_FEEDS)), SHARD_INDEX, TOTAL_SHARDS)
    items += collect_block(news_urls, "news", "News", PER_FEED_LIMIT)

    # The rest are usually small – run on every shard
    items += collect_block(list(dict.fromkeys(AUTH_FEEDS)), "news", "Authorities", PER_FEED_LIMIT)
    items += collect_block(list(dict.fromkeys(OFFICIAL_FEEDS)), "news", "Official", PER_FEED_LIMIT)
    items += collect_block(list(dict.fromkeys(WEATHER_FEEDS)), "news", "Weather", PER_FEED_LIMIT)
    items += collect_block(list(dict.fromkeys(SOCIAL_FEEDS)), "social", "Social", PER_FEED_LIMIT)

    # De-dupe newest by id
    best: Dict[str, Dict[str, Any]] = {}
    for it in items:
        k = it["id"]
        if (k not in best) or (it["published_at"] > best[k]["published_at"]):
            best[k] = it
    out = list(best.values())
    out.sort(key=lambda x: x["published_at"], reverse=True)
    return out[:500]

# ----------------------------- Main -----------------------------

def main():
    global STARTED_AT
    STARTED_AT = now_utc()
    write_status({
        "started_at": iso(STARTED_AT),
        "total": 0, "done": 0, "current": None,
        "note": "Starting…", "version": APP_VER
    })

    items = collect_all()

    data = {"generated_at": iso(now_utc()), "items": items, "trends": {}}
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    write_status({
        "started_at": iso(STARTED_AT),
        "finished_at": iso(now_utc()),
        "total": len(NEWS_FEEDS),
        "done": len(NEWS_FEEDS) if TOTAL_SHARDS <= 1 else len(shard(NEWS_FEEDS, SHARD_INDEX, TOTAL_SHARDS)),
        "current": None,
        "note": f"Collected {len(items)} items",
        "version": APP_VER
    })
    log.info("Wrote %s (%d items) and status.json", DATA_FILE, len(items))

if __name__ == "__main__":
    main()
