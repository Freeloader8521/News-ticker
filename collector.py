#!/usr/bin/env python3
from __future__ import annotations

import json, re, hashlib, logging, os
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

import requests, feedparser, yaml
from dateutil import parser as dtparse
from bs4 import BeautifulSoup
from langdetect import detect, LangDetectException
from deep_translator import GoogleTranslator

# ----------------------------- Config -----------------------------
APP_NAME = "GSA-Collector"
APP_VER  = "1.9"
UA       = {"User-Agent": f"{APP_NAME}/{APP_VER} (+https://streamlit.app)"}

FAIL_HARD_CODES = {401, 403, 404}
FAIL_MAX_CONSEC = 3
FAIL_EMPTY_MAX  = 3

FEEDS_MAIN_FILE   = "feeds.yaml"
FEEDS_EXTRA_FILE  = "feeds-extra.yaml"
BROKEN_FILE       = "feeds-broken.yaml"
FAIL_DB_FILE      = "feeds-fail-counts.json"
STATUS_FILE       = "status.json"
DATA_OUT          = "data.json"
SOCIAL_FILTERS_YAML = "social_filters.yaml"

# ----------------------------- logging -----------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("collector")

# ----------------------------- helpers -----------------------------
def now_utc() -> datetime: return datetime.now(timezone.utc)
def sha1_16(s: str) -> str: return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]
def domain_of(url: str) -> str:
    m = re.search(r"https?://([^/]+)", url or "")
    return (m.group(1).lower() if m else "").replace("www.", "")
def strip_html(raw: str) -> str:
    if not raw: return ""
    try: return BeautifulSoup(raw, "html.parser").get_text(" ", strip=True)
    except Exception: return re.sub(r"<[^>]+>", "", raw or "")
def safe_detect(text: str) -> str:
    try: return detect(text) if text and text.strip() else "en"
    except LangDetectException: return "en"
def to_english(s: str) -> str:
    if not s: return s
    try: return GoogleTranslator(source="auto", target="en").translate(s)
    except Exception: return s
def write_status(obj: dict):
    try:
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, ensure_ascii=False)
    except Exception: pass

def load_yaml(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f: return yaml.safe_load(f) or {}
    except FileNotFoundError: return {}

def dedupe(seq: List[str]) -> List[str]:
    seen, out = set(), []
    for s in seq:
        if s not in seen:
            seen.add(s); out.append(s)
    return out

def load_all_feeds() -> Tuple[List[str], List[str], List[str], List[str], List[str]]:
    feeds_main  = load_yaml(FEEDS_MAIN_FILE)
    feeds_extra = load_yaml(FEEDS_EXTRA_FILE)
    feeds_broke = load_yaml(BROKEN_FILE)

    def g(src, key): return src.get(key, [])

    main_news   = g(feeds_main, "news");                 extra_news   = g(feeds_extra, "news_extra")
    main_auth   = g(feeds_main, "aviation_authorities"); extra_auth   = g(feeds_extra, "aviation_authorities_extra")
    main_off    = g(feeds_main, "official_announcements"); extra_off  = g(feeds_extra, "official_announcements_extra")
    main_weather= g(feeds_main, "weather_alerts");       extra_weather= g(feeds_extra, "weather_alerts_extra")
    main_social = g(feeds_main, "social");               extra_social = g(feeds_extra, "social_extra")

    broken_all  = set(dedupe(sum([feeds_broke.get(k, []) for k in feeds_broke], [])))
    def ok(lst): return [u for u in lst if u not in broken_all]

    NEWS     = dedupe(ok(main_news)   + ok(extra_news))
    AUTH     = dedupe(ok(main_auth)   + ok(extra_auth))
    OFFICIAL = dedupe(ok(main_off)    + ok(extra_off))
    WEATHER  = dedupe(ok(main_weather)+ ok(extra_weather))
    SOCIAL   = dedupe(ok(main_social) + ok(extra_social))
    return NEWS, AUTH, OFFICIAL, WEATHER, SOCIAL

def load_fail_db() -> Dict[str, dict]:
    try:
        with open(FAIL_DB_FILE, "r", encoding="utf-8") as f: return json.load(f)
    except FileNotFoundError: return {}
def save_fail_db(db: Dict[str, dict]):
    with open(FAIL_DB_FILE, "w", encoding="utf-8") as f: json.dump(db, f, indent=2, ensure_ascii=False)
def mark_broken(url: str):
    y = load_yaml(BROKEN_FILE); y.setdefault("broken", [])
    if url not in y["broken"]:
        y["broken"].append(url)
        with open(BROKEN_FILE, "w", encoding="utf-8") as f: yaml.safe_dump(y, f, sort_keys=False, allow_unicode=True)

# ----------------------------- watch terms & airports (unchanged) -----------------------------
try:
    with open("watch_terms.yaml", "r", encoding="utf-8") as f:
        TERMS = yaml.safe_load(f) or {}
except FileNotFoundError:
    TERMS = {}
CORE    = set(TERMS.get("core_terms", []))
DIPLO   = set(TERMS.get("diplomacy_terms", []))
EXCLUDE = set(TERMS.get("exclude_terms", []))

def should_exclude(text: str) -> bool:
    t = (text or "").lower()
    return any(x.lower() in t for x in EXCLUDE)
def tags_for(text: str) -> List[str]:
    t = (text or "").lower(); out=[]
    if any(x.lower() in t for x in CORE):  out.append("airport/security")
    if any(x.lower() in t for x in DIPLO): out.append("diplomatic")
    return out

try:
    with open("airports.json", "r", encoding="utf-8") as f: AIRPORTS = json.load(f)
except FileNotFoundError:
    AIRPORTS = []

ALIASES: Dict[str, Dict[str, Any]] = {}; IATA_TO_LL: Dict[str, tuple] = {}
for a in AIRPORTS:
    meta = {"iata": a.get("iata"), "name": a.get("name"), "city": a.get("city"),
            "country": a.get("country"), "lat": a.get("lat", a.get("latitude")),
            "lon": a.get("lon", a.get("longitude"))}
    iata = (meta["iata"] or "").upper()
    if iata and isinstance(meta["lat"], (int, float)) and isinstance(meta["lon"], (int, float)):
        IATA_TO_LL[iata] = (meta["lat"], meta["lon"])
    for alias in (a.get("aliases") or []) + [a.get("iata", "")]:
        if alias: ALIASES[alias.lower()] = meta

AIRPORT_CONTEXT = re.compile(r"\b(airport|intl|international|terminal|airfield|aerodrome)s?\b", re.I)
def _has_airport_context(text: str, pos: int, window: int = 48) -> bool:
    start = max(0, pos - window); end = min(len(text), pos + window)
    return bool(AIRPORT_CONTEXT.search(text[start:end]))

def match_airport(text: str):
    if not text: return None
    t_lower = text.lower(); t_upper = text.upper()

    for alias, meta in ALIASES.items():
        if not alias: continue
        if len(alias) == 3 and alias.isalpha(): continue
        for m in re.finditer(rf"\b{re.escape(alias)}\b", t_lower):
            if ("airport" in alias) or _has_airport_context(t_lower, m.start()):
                out = {"iata": (meta.get("iata") or "").upper() or None,
                       "name": meta.get("name"), "city": meta.get("city"),
                       "country": meta.get("country")}
                lat, lon = meta.get("lat"), meta.get("lon")
                if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
                    out["lat"], out["lon"] = lat, lon
                elif out["iata"] and out["iata"] in IATA_TO_LL:
                    out["lat"], out["lon"] = IATA_TO_LL[out["iata"]]
                return out

    for m in re.finditer(r"\b([A-Z]{3})\b", t_upper):
        token = m.group(1)
        if token in IATA_TO_LL and _has_airport_context(t_lower, m.start()):
            lat, lon = IATA_TO_LL[token]
            meta = next((a for a in AIRPORTS if (a.get("iata") or "").upper() == token), None)
            return {"iata": token, "name": meta.get("name") if meta else None,
                    "city": meta.get("city") if meta else None,
                    "country": meta.get("country") if meta else None,
                    "lat": lat, "lon": lon}
    return None

MAJOR_DOMAINS = {
    "reuters.com","bbc.co.uk","apnews.com","theguardian.com","nytimes.com","bloomberg.com",
    "ft.com","aljazeera.com","dw.com","france24.com","euronews.com","avherald.com","gov.uk","faa.gov",
    "easa.europa.eu","ncsc.gov.uk","noaa.gov"
}
def classify_type(url: str, declared: str, src_domain: str) -> str:
    if (declared or "").lower() == "social": return "social"
    return "major news" if any(src_domain.endswith(d) for d in MAJOR_DOMAINS) else "local news"

# ----------------------------- social filters -----------------------------
def load_social_filters():
    y = load_yaml(SOCIAL_FILTERS_YAML)
    blocked_post_domains = set((y.get("blocked_post_domains") or []))
    blocked_terms        = set((y.get("blocked_terms") or []))
    allowed_link_domains = set((y.get("allowed_link_domains") or []))
    allow_gov_like       = bool(y.get("allow_gov_like_tlds", True))
    min_text_chars       = int(y.get("min_text_chars", 0))
    return blocked_post_domains, blocked_terms, allowed_link_domains, allow_gov_like, min_text_chars

BLOCK_DOMAINS, BLOCK_TERMS, ALLOW_LINKS, ALLOW_GOV_TLDS, MIN_TEXT = load_social_filters()

URL_RE = re.compile(r"https?://[^\s)]+", re.I)
def extract_urls(text: str) -> List[str]:
    return URL_RE.findall(text or "")

def looks_gov_like(d: str) -> bool:
    return bool(re.search(r"\.(gov|mil|gob\.[a-z]{2}|go\.[a-z]{2})(?:$|/)", d))

def is_social_allowed(post_url: str, text: str) -> bool:
    # 1) hard block by the post host
    host = domain_of(post_url)
    if host in BLOCK_DOMAINS: return False

    # 2) text length gate
    if MIN_TEXT and len((text or "").strip()) < MIN_TEXT: return False

    # 3) term block
    lowered = (text or "").lower()
    if any(term.lower() in lowered for term in BLOCK_TERMS): return False

    # 4) link allow policy
    if ALLOW_LINKS:
        links = [domain_of(u) for u in extract_urls(text)]
        if any(ld in ALLOW_LINKS for ld in links): return True
        if ALLOW_GOV_TLDS and any(looks_gov_like(ld) for ld in links): return True
        # no allowed links → drop
        return False

    # default allow
    return True

# ----------------------------- fetching & bookkeeping -----------------------------
def fetch_feed(url: str, fail_db: Dict[str, dict]) -> Tuple[str, List[Any], str]:
    dom = domain_of(url)
    try:
        r = requests.get(url, headers=UA, timeout=25)
        if r.status_code in FAIL_HARD_CODES:
            log.warning("Feed error %s: %s", r.status_code, url)
            return dom, [], str(r.status_code)
        r.raise_for_status()
        d = feedparser.parse(r.content)
        entries = d.entries or []
        if not entries:
            log.warning("Feed parsed but empty: %s", url)
            return d.feed.get("title", dom), [], "empty"
        return d.feed.get("title", dom), entries, ""
    except requests.HTTPError as ex:
        code = getattr(ex.response, "status_code", None)
        reason = str(code) if code in FAIL_HARD_CODES else "other"
        log.warning("Feed HTTP error %s for %s", code, url)
        return dom, [], reason
    except Exception as ex:
        log.warning("Feed error %s: %s", type(ex).__name__, url)
        return dom, [], "other"

def update_fail_bookkeeping(url: str, reason: str, fail_db: Dict[str, dict]) -> bool:
    rec = fail_db.setdefault(url, {"hard": 0, "empty": 0})
    if reason in {"401","403","404"}: rec["hard"] += 1
    elif reason == "empty":          rec["empty"] += 1
    else:
        rec["hard"]  = max(0, rec["hard"]  - 1)
        rec["empty"] = max(0, rec["empty"] - 1)
    return (rec["hard"] >= FAIL_MAX_CONSEC) or (rec["empty"] >= FAIL_EMPTY_MAX)

def record_success(url: str, fail_db: Dict[str, dict]):
    if url in fail_db:
        fail_db[url]["hard"] = 0
        fail_db[url]["empty"] = 0

# ----------------------------- normalise -----------------------------
def derive_title(raw_title: str, summary: str) -> str:
    t = strip_html(raw_title or "").strip()
    if t and t.lower() != "(no title)": return t
    first = next((ln for ln in (summary or "").strip().splitlines() if ln.strip()), "")
    return (first[:160] if first else "(no title)")

def normalise(entry, feedtitle: str, declared_type: str):
    url = entry.get("link", "") or entry.get("id", "") or ""
    raw_title = entry.get("title", "") or ""
    raw_summary = entry.get("summary", "") or ""

    summary_clean = strip_html(raw_summary)
    title_clean   = derive_title(raw_title, summary_clean)

    lang = safe_detect(f"{title_clean} {summary_clean}")
    title_en   = title_clean   if lang == "en" else to_english(title_clean)
    summary_en = summary_clean if lang == "en" else to_english(summary_clean)
    text_for_filter = f"{title_en} {summary_en}"

    # kill excluded words early
    if should_exclude(text_for_filter): return None

    # time
    pub = None
    for k in ("published","updated","created"):
        if entry.get(k):
            try:
                pub = dtparse.parse(entry[k]).astimezone(timezone.utc); break
            except Exception: pass
    if not pub: pub = now_utc()

    src_dom  = domain_of(url)
    src_name = feedtitle or src_dom

    # social spam gate
    if (declared_type or "").lower() == "social":
        if not is_social_allowed(url, text_for_filter):
            return None

    # tags + airport hinting
    item_tags = tags_for(text_for_filter)
    geo = {}
    ap = match_airport(text_for_filter)
    if ap:
        geo = {"airport": ap.get("name"), "city": ap.get("city"), "country": ap.get("country"),
               "iata": ap.get("iata")}
        if ap.get("lat") is not None and ap.get("lon") is not None:
            geo["lat"], geo["lon"] = ap["lat"], ap["lon"]
        if ap.get("iata"):    item_tags.append(ap["iata"])
        if ap.get("country"): item_tags.append(ap["country"])

    # keep only if relevant
    if not (("airport/security" in item_tags) or ("diplomatic" in item_tags)):
        return None

    item_type = classify_type(url, declared_type, src_dom)
    item_tags = sorted(set(item_tags))

    return {
        "id": sha1_16(url or title_en),
        "title_orig": title_clean,
        "summary_orig": summary_clean,
        "lang": lang,
        "title_en": title_en,
        "summary_en": summary_en,
        "title": title_en,
        "summary": summary_en,
        "url": url,
        "source": src_name,
        "published_at": pub.isoformat(),
        "tags": item_tags,
        "type": item_type,
        "geo": geo
    }

# ----------------------------- collect -----------------------------
def collect_block(feed_urls: List[str], declared_type: str,
                  per_feed_limit: int, fail_db: Dict[str, dict], status: dict):
    items: List[Dict[str, Any]] = []
    for f in feed_urls:
        status["current"] = domain_of(f); write_status(status)
        title, entries, fail_reason = fetch_feed(f, fail_db)
        if fail_reason:
            if update_fail_bookkeeping(f, fail_reason, fail_db):
                log.warning("Quarantining broken feed: %s (%s)", f, fail_reason)
                mark_broken(f)
            continue
        else:
            record_success(f, fail_db)

        for e in entries[:80]:
            it = normalise(e, title, declared_type)
            if it: items.append(it)

        status["done"] = status.get("done", 0) + 1; write_status(status)
    return items

def collect_all():
    started = now_utc().isoformat()
    status = {"started_at": started, "version": APP_VER, "total": 0, "done": 0, "current": ""}
    write_status(status)

    NEWS, AUTH, OFFICIAL, WEATHER, SOCIAL = load_all_feeds()
    all_feeds = NEWS + AUTH + OFFICIAL + WEATHER + SOCIAL
    status["total"] = len(all_feeds); write_status(status)

    fail_db = load_fail_db()

    items: List[Dict[str, Any]] = []
    items += collect_block(NEWS,     "news",   80, fail_db, status)
    items += collect_block(AUTH,     "news",   80, fail_db, status)
    items += collect_block(OFFICIAL, "news",   80, fail_db, status)
    items += collect_block(WEATHER,  "news",   80, fail_db, status)
    items += collect_block(SOCIAL,   "social", 80, fail_db, status)

    save_fail_db(fail_db)

    best: Dict[str, Dict[str, Any]] = {}
    for it in items:
        k = it["id"]
        if (k not in best) or (it["published_at"] > best[k]["published_at"]):
            best[k] = it
    out = list(best.values()); out.sort(key=lambda x: x["published_at"], reverse=True)
    out = out[:500]

    with open(DATA_OUT, "w", encoding="utf-8") as f:
        json.dump({"generated_at": now_utc().isoformat(), "items": out, "trends": {}}, f,
                  indent=2, ensure_ascii=False)

    status.update({"finished_at": now_utc().isoformat(), "note": f"Collected {len(out)} items"})
    write_status(status); log.info("Done. Items=%d", len(out))

def main(): collect_all()
if __name__ == "__main__": main()
