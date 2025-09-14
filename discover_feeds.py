#!/usr/bin/env python3
import concurrent.futures as fut
import re
import sys
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
import feedparser
import yaml

SEEDS_FILE = "seeds.txt"           # one site/URL per line
OUT_YAML   = "feeds-extra.yaml"    # will be created/updated
TIMEOUT    = 10
UA = {"User-Agent": "GSA-FeedDiscovery/1.0 (+https://streamlit.app)"}

COMMON_HINTS = [
    "/rss", "/rss.xml", "/feed", "/feeds", "/atom", "/index.xml",
    "/category/news/feed", "/?feed=rss2", "/?feed=atom",
]
RSS_MIME = {"application/rss+xml", "application/atom+xml", "application/xml", "text/xml"}

def norm(u: str) -> str:
    return re.sub(r"#.*$", "", u.strip())

def homepage(url: str) -> str:
    p = urlparse(url)
    if not p.scheme:
        url = "https://" + url
        p = urlparse(url)
    if not p.netloc:
        return ""
    return f"{p.scheme}://{p.netloc}/"

def find_rel_alternate(url: str) -> list[str]:
    out = []
    try:
        r = requests.get(url, headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for ln in soup.find_all("link"):
            rels = " ".join((ln.get("rel") or [])).lower()
            typ = (ln.get("type") or "").lower()
            href = ln.get("href")
            if not href:
                continue
            if ("alternate" in rels) and (typ in RSS_MIME or "rss" in typ or "atom" in typ):
                out.append(urljoin(url, href))
    except Exception:
        pass
    return out

def try_common(url: str) -> list[str]:
    root = homepage(url)
    if not root:
        return []
    return [root.rstrip("/") + path for path in COMMON_HINTS]

def is_working_feed(url: str) -> bool:
    try:
        r = requests.get(url, headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        d = feedparser.parse(r.content)
        return bool(getattr(d, "entries", []))
    except Exception:
        return False

def discover_for_seed(seed: str) -> set[str]:
    cand = set()

    # home
    root = homepage(seed)
    if root:
        cand.update(find_rel_alternate(root))
        for hint in try_common(root):
            cand.add(hint)

    # if seed already looks like a feed, include it directly
    if re.search(r"(rss|atom|feed)(\.xml|\/)?($|\?)", seed, re.I):
        cand.add(seed)

    # validate
    good = set()
    for u in cand:
        if is_working_feed(u):
            good.add(u)
    return good

def domain(u: str) -> str:
    try:
        return urlparse(u).netloc.lower().replace("www.", "")
    except Exception:
        return ""

def main():
    try:
        with open(SEEDS_FILE, "r", encoding="utf-8") as f:
            seeds = [norm(x) for x in f.readlines() if norm(x)]
    except FileNotFoundError:
        print("seeds.txt not found. Create it with one website per line.")
        sys.exit(1)

    t0 = time.time()
    all_good = set()

    with fut.ThreadPoolExecutor(max_workers=24) as ex:
        for feeds in ex.map(discover_for_seed, seeds):
            all_good.update(feeds)

    # Deduplicate by (domain, path)
    deduped = {}
    for u in sorted(all_good):
        d = domain(u)
        if not d:
            continue
        # keep first we saw from a given (domain, canonical path)
        key = (d, urlparse(u).path.lower())
        deduped.setdefault(key, u)

    feeds = sorted(deduped.values())

    # Write YAML in the same shape your app expects (appendable)
    out = {"news_extra": feeds}

    with open(OUT_YAML, "w", encoding="utf-8") as f:
        yaml.safe_dump(out, f, sort_keys=False, allow_unicode=True)

    print(f"Discovered {len(feeds)} working feeds in {time.time()-t0:.1f}s → {OUT_YAML}")

if __name__ == "__main__":
    main()
