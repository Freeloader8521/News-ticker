#!/usr/bin/env python3
"""
Collector for the Global Situational Awareness Dashboard
- Reads feeds from feeds.yaml (news, aviation authorities, official, weather, social)
- Reads airport aliases + lat/lon from airports.json
- Reads watch terms from watch_terms.yaml
- Normalises each entry, detects/optionally translates language, tags for relevance
- Matches airports safely and injects geo (iata, airport, city, country, lat, lon)
- Classifies type (major news / local news / social)
- Falls back to first line when title is missing
- De-duplicates and writes data.json
- Writes status.json as it progresses so the UI can show a progress bar
"""

from __future__ import annotations

import os
import re
import json
import time
import hashlib
from typing import Any, Dict, List, Tuple, Callable
from datetime import datetime, timezone

import requests
import feedparser
import yaml
from dateutil import parser as dtparse
from bs4 import BeautifulSoup
from langdetect import detect, LangDetectException
from deep_translator import GoogleTranslator

# ----------------------------- Config -----------------------------

APP_NAME = "GSA-Collector"
APP_VER  = "1.7"
UA = {"User-Agent": f"{APP_NAME}/{APP_VER} (+https://streamlit.app)"}

DATA_FILE   = os.environ.get("DATA_FILE", "data.json")
STATUS_FILE = os.environ.get("STATUS_FILE", "status.json")

# If you ever want to block spammy domains outright:
BLOCKED_DOMAINS = {
    "bigorre.org",
    "www.bigorre.org",
}

MAJOR_DOMAINS = {
    "reuters.com","bbc.co.uk","apnews.com","theguardian.com","nytimes.com",
    "bloomberg.com","ft.com","cnn.com","aljazeera.com","sky.com","latimes.com",
    "cbc.ca","theglobeandmail.com","scmp.com","straitstimes.com","japantimes.co.jp",
    "avherald.com","gov.uk","faa.gov","easa.europa.eu","caa.co.uk","ntsb.gov",
    "bea.aero","atsb.gov.au","caa.govt.nz","caa.co.za","tc.gc.ca","noaa.gov",
    "nhc.noaa.gov","weather.gov",
}

# ----------------------------- Small utils -----------------------------

def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def iso(dt: datetime) -> str:
    return (dt or now_utc()).isoformat()

def sha1_16(s: str) -> str:
    return hashlib.sha1((s or "").encode("utf-8")).hexdigest()[:16]

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
        return s

def derive_title(raw_title: str, summary: str) -> str:
    t = strip_html(raw_title or "").strip()
    if t and t.lower() != "(no title)":
        return t
    lines = [ln.strip() for ln in (summary or "").splitlines() if ln.strip()]
    return (lines[0][:160] if lines else "(no title)")

# ----------------------------- Load config files -----------------------------

def load_yaml(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}

FEEDS = load_yaml("feeds.yaml")
NEWS_FEEDS     = FEEDS.get("news", [])
AUTH_FEEDS     = FEEDS.get("aviation_authorities", [])
OFFICIAL_FEEDS = FEEDS.get("official_announcements", [])
WEATHER_FEEDS  = FEEDS.get("weather_alerts", [])
SOCIAL_FEEDS   = FEEDS.get("social", [])

TERMS = load_yaml("watch_terms.yaml")
CORE    = set(TERMS.get("core_terms", []))
DIPLO   = set(TERMS.get("diplomacy_terms", []))
EXCLUDE = set(TERMS.get("exclude_terms", []))

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

# ----------------------------- Airports + matching -----------------------------

try:
    with open("airports.json", "r", encoding="utf-8") as f:
        AIRPORTS = json.load(f)
except FileNotFoundError:
    AIRPORTS = []

IATA_TO_LL: Dict[str, Tuple[float, float]] = {}
ALIASES: Dict[str, Dict[str, Any]] = {}

for a in AIRPORTS:
    lat = a.get("lat") or a.get("latitude")
    lon = a.get("lon") or a.get("longitude")
    meta = {
        "iata": a.get("iata"),
        "name": a.get("name"),
        "city": a.get("city"),
        "country": a.get("country"),
        "lat": lat,
        "lon": lon,
    }
    iata = (meta["iata"] or "").upper()
    if iata and isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        IATA_TO_LL[iata] = (lat, lon)

    for alias in (a.get("aliases") or []) + [a.get("iata", "")]:
        if alias:
            ALIASES[alias.lower()] = meta

AIRPORT_CONTEXT = re.compile(r"\b(airport|intl|international|terminal|airfield|aerodrome)s?\b", re.I)

def _has_airport_context(text: str, pos: int, window: int = 48) -> bool:
    start = max(0, pos - window)
    end   = min(len(text), pos + window)
    return bool(AIRPORT_CONTEXT.search(text[start:end]))

def match_airport(text: str):
    """Safer airport matcher (prefers full aliases; IATA needs nearby 'airport' context)."""
    if not text:
        return None

    t_lower = text.lower()
    t_upper = text.upper()

    # 1) Try full-name aliases (allow without 'airport' if alias contains it)
    for alias, meta in ALIASES.items():
        if not alias:
            continue
        if len(alias) == 3 and alias.isalpha():
            continue
        for m in re.finditer(rf"\b{re.escape(alias)}\b", t_lower):
            pos = m.start()
            if ("airport" in alias) or _has_airport_context(t_lower, pos):
                iata = (meta.get("iata") or "").upper()
                lat = meta.get("lat"); lon = meta.get("lon")
                out = {
                    "iata": iata or None,
                    "name": meta.get("name"),
                    "city": meta.get("city"),
                    "country": meta.get("country"),
                }
                if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
                    out["lat"] = lat; out["lon"] = lon
                elif iata and iata in IATA_TO_LL:
                    out["lat"], out["lon"] = IATA_TO_LL[iata]
                return out

    # 2) Standalone IATA tokens with airport context
    for m in re.finditer(r"\b([A-Z]{3})\b", t_upper):
        token = m.group(1)
        if token in IATA_TO_LL and _has_airport_context(t_lower, m.start()):
            lat, lon = IATA_TO_LL[token]
            meta = next((a for a in AIRPORTS if (a.get("iata") or "").upper() == token), None)
            return {
                "iata": token,
                "name": meta.get("name") if meta else None,
                "city": meta.get("city") if meta else None,
                "country": meta.get("country") if meta else None,
                "lat": lat,
                "lon": lon,
            }
    return None

# ----------------------------- Status writing -----------------------------

def _atomic_write(path: str, obj: dict):
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def write_status(state: dict):
    """Best-effort status writer."""
    try:
        _atomic_write(STATUS_FILE, state)
    except Exception:
        pass

# ----------------------------- Fetch + normalise -----------------------------

def fetch_feed(url: str) -> Tuple[str, List[dict]]:
    try:
        dom = get_domain(url)
        if dom in BLOCKED_DOMAINS:
            return dom, []
        r = requests.get(url, headers=UA, timeout=25)
        r.raise_for_status()
        d = feedparser.parse(r.content)
        return d.feed.get("title", dom), d.entries
    except Exception:
        return get_domain(url), []

def classify_type(url: str, declared_type: str, src_domain: str) -> str:
    if (declared_type or "").lower() == "social":
        return "social"
    return "major news" if any(src_domain.endswith(d) for d in MAJOR_DOMAINS) else "local news"

def normalise(entry: dict, feedtitle: str, declared_type: str) -> dict | None:
    url = entry.get("link", "") or entry.get("id", "") or ""
    raw_title = entry.get("title", "") or ""
    raw_summary = entry.get("summary", "") or ""

    summary_clean = strip_html(raw_summary)
    title_clean   = derive_title(raw_title, summary_clean)

    lang = safe_detect(f"{title_clean} {summary_clean}")
    title_en   = title_clean   if lang == "en" else to_english(title_clean)
    summary_en = summary_clean if lang == "en" else to_english(summary_clean)

    # filter on English text
    filter_text = f"{title_en} {summary_en}"
    if should_exclude(filter_text):
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

    src_dom  = get_domain(url)
    if src_dom in BLOCKED_DOMAINS:
        return None
    src_name = clean_source(feedtitle, url)

    # tags + geo (ONLY from airport match)
    item_tags = tags_for(filter_text)
    geo = {}
    ap = match_airport(filter_text)
    if ap:
        geo = {
            "airport": ap.get("name"),
            "city": ap.get("city"),
            "country": ap.get("country"),
            "iata": ap.get("iata"),
        }
        if ap.get("lat") is not None and ap.get("lon") is not None:
            geo["lat"] = ap["lat"]; geo["lon"] = ap["lon"]
        if ap.get("iata"):
            item_tags.append(ap["iata"])
        if ap.get("country"):
            item_tags.append(ap["country"])

    # keep only relevant
    if not (("airport/security" in item_tags) or ("diplomatic" in item_tags)):
        return None

    item_type = classify_type(url, declared_type, src_dom)
    item_tags = sorted(set(item_tags))

    return {
        "id": sha1_16(url or title_en),

        # originals + translations (UI can toggle)
        "title_orig": title_clean,
        "summary_orig": summary_clean,
        "lang": lang,
        "title_en": title_en,
        "summary_en": summary_en,

        # convenience (default English)
        "title": title_en,
        "summary": summary_en,

        "url": url,
        "source": src_name,
        "published_at": pub.isoformat(),
        "tags": item_tags,
        "type": item_type,
        "geo": geo,
    }

# ----------------------------- Collect with progress -----------------------------

def collect_block(feed_urls: List[str], declared_type: str,
                  step_cb: Callable[[str, int], None]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for f in feed_urls:
        step_cb(f, 0)   # announce which feed we’re starting (done increment in caller)
        feedtitle, entries = fetch_feed(f)
        for e in entries[:120]:
            it = normalise(e, feedtitle, declared_type)
            if it:
                items.append(it)
        step_cb(f, 1)   # mark this feed as done
    return items

def collect_all(progress_cb: Callable[[str, int], None]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    items += collect_block(NEWS_FEEDS,     "news",   progress_cb)
    items += collect_block(AUTH_FEEDS,     "news",   progress_cb)
    items += collect_block(OFFICIAL_FEEDS, "news",   progress_cb)
    items += collect_block(WEATHER_FEEDS,  "news",   progress_cb)
    items += collect_block(SOCIAL_FEEDS,   "social", progress_cb)

    # de-dupe by newest
    best: Dict[str, Dict[str, Any]] = {}
    for it in items:
        k = it["id"]
        if (k not in best) or (it["published_at"] > best[k]["published_at"]):
            best[k] = it
    out = list(best.values())
    out.sort(key=lambda x: x["published_at"], reverse=True)
    return out[:600]

# ----------------------------- Main -----------------------------

def all_feeds() -> List[str]:
    return list(NEWS_FEEDS) + list(AUTH_FEEDS) + list(OFFICIAL_FEEDS) + list(WEATHER_FEEDS) + list(SOCIAL_FEEDS)

def main():
    feeds = all_feeds()
    total = len(feeds)
    done  = 0

    status = {
        "started_at": iso(now_utc()),
        "finished_at": "",
        "total": total,
        "done": 0,
        "current": "",
        "note": "Collecting feeds…",
        "version": APP_VER,
    }
    write_status(status)

    def progress_cb(feed_url: str, inc: int):
        # inc = 0 when starting a feed, 1 when finishing
        nonlocal done, status
        if inc == 1:
            done += 1
        status["done"]    = done
        status["current"] = get_domain(feed_url) or feed_url
        write_status(status)

    try:
        items = collect_all(progress_cb)
        data = {"generated_at": iso(now_utc()), "items": items, "trends": {}}
        _atomic_write(DATA_FILE, data)
        status["note"] = f"Collected {len(items)} items"
    except Exception as ex:
        status["note"] = f"ERROR: {ex}"
        # still try to write whatever state we have
    finally:
        status["finished_at"] = iso(now_utc())
        write_status(status)

if __name__ == "__main__":
    main()
