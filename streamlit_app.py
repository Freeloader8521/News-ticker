import os# streamlit_app.py

import json
import base64
from datetime import datetime
from typing import Dict, Any, List

import requests
import streamlit as st
import pytz

# --------------------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------------------

APP_TITLE = "Global Situational Awareness Dashboard"

# If you use Streamlit Secrets, set DATA_JSON_URL in your app’s Secrets.
# Otherwise the app will try to read ./data.json from the repo.
DATA_JSON_URL = st.secrets.get("DATA_JSON_URL", "").strip()

# Country → flag emoji (only used when geo.country is present from an airport match)
COUNTRY_FLAGS = {
    "United Kingdom": "🇬🇧",
    "United States": "🇺🇸",
    "Canada": "🇨🇦",
    "Ireland": "🇮🇪",
    "France": "🇫🇷",
    "Germany": "🇩🇪",
    "Netherlands": "🇳🇱",
    "Spain": "🇪🇸",
    "Portugal": "🇵🇹",
    "Italy": "🇮🇹",
    "Switzerland": "🇨🇭",
    "Austria": "🇦🇹",
    "Belgium": "🇧🇪",
    "Poland": "🇵🇱",
    "Greece": "🇬🇷",
    "Türkiye": "🇹🇷",
    "United Arab Emirates": "🇦🇪",
    "Qatar": "🇶🇦",
    "Saudi Arabia": "🇸🇦",
    "Israel": "🇮🇱",
    "India": "🇮🇳",
    "Pakistan": "🇵🇰",
    "Bangladesh": "🇧🇩",
    "Thailand": "🇹🇭",
    "Malaysia": "🇲🇾",
    "Singapore": "🇸🇬",
    "Philippines": "🇵🇭",
    "Indonesia": "🇮🇩",
    "Japan": "🇯🇵",
    "South Korea": "🇰🇷",
    "China": "🇨🇳",
    "Australia": "🇦🇺",
    "New Zealand": "🇳🇿",
    "Mexico": "🇲🇽",
    "Brazil": "🇧🇷",
    "Argentina": "🇦🇷",
    "Chile": "🇨🇱",
    "South Africa": "🇿🇦",
    "Kenya": "🇰🇪",
    "Egypt": "🇪🇬",
    "Nigeria": "🇳🇬",
    "Ghana": "🇬🇭",
}

# Optional crest image (top-right). Put a public URL in secrets as CREST_URL, or leave blank.
CREST_URL = st.secrets.get("CREST_URL", "").strip()

# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------

def pretty_dt_uk(iso: str) -> str:
    """Return 'HH:MM, Weekday DD Month YYYY' in Europe/London (BST/GMT)."""
    try:
        dt_utc = datetime.fromisoformat((iso or "").replace("Z", "+00:00"))
        uk = pytz.timezone("Europe/London")
        dt_local = dt_utc.astimezone(uk)
        return dt_local.strftime("%H:%M, %A %d %B %Y")
    except Exception:
        return iso or ""

@st.cache_data(ttl=60)
def fetch_json(url: str) -> Dict[str, Any]:
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return r.json()

@st.cache_data(ttl=60)
def load_local_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def load_data() -> Dict[str, Any]:
    try:
        if DATA_JSON_URL:
            return fetch_json(DATA_JSON_URL)
        return load_local_json("data.json")
    except Exception as e:
        st.warning(f"Could not load data.json ({e}).")
        return {"generated_at": "", "items": [], "trends": {}}

def crest_html(url: str) -> str:
    if not url:
        return ""
    return f"""
    <div style="position:fixed; top:12px; right:14px; z-index:9999; opacity:.25;">
        <img src="{url}" alt="crest" style="height:58px;"/>
    </div>
    """

def is_relevant(it: Dict[str, Any]) -> bool:
    """Keep items that are already filtered by the collector (airport/security or diplomatic)."""
    tags = it.get("tags", [])
    return ("airport/security" in tags) or ("diplomatic" in tags)

def flag_for_country(name: str) -> str:
    return COUNTRY_FLAGS.get(name or "", "")

def live_caption(it: Dict[str, Any]) -> str:
    """Build the small grey line under each headline with time | geo | tags."""
    parts: List[str] = []
    src = it.get("source")
    if src:
        parts.append(src)

    # time
    try:
        parts.append(pretty_dt_uk(it.get("published_at", "")))
    except Exception:
        pass

    # geo from airport match only (no inferred country)
    geo = it.get("geo", {}) or {}
    geo_bits: List[str] = []
    if geo.get("airport"):
        geo_bits.append(geo["airport"])
    if geo.get("city"):
        geo_bits.append(geo["city"])
    if geo.get("country"):
        f = flag_for_country(geo["country"])
        if f:
            geo_bits.append(f)
        else:
            geo_bits.append(geo["country"])
    if geo.get("iata"):
        geo_bits.append(geo["iata"])

    if geo_bits:
        parts.append(" | ".join(geo_bits))

    # tags (short)
    tags = [t for t in it.get("tags", []) if t not in ("airport/security", "diplomatic")]
    if tags:
        parts.append(", ".join(tags))

    return " | ".join(parts)

# A tiny beep (440 Hz, 150 ms) – base64 WAV
_BEEP_WAV = (
    "UklGRoQAAABXQVZFZm10IBAAAAABAAEAESsAACJWAAACABAAZGF0YYQAAAABAQEB"
    "AQEBAQEBAQEBAQEBAP///wD///8A////AP///wD///8A////AP///wD///8A////"
)

def play_beep():
    audio_tag = f"""
    <audio autoplay="true">
      <source src="data:audio/wav;base64,{_BEEP_WAV}">
    </audio>
    """
    st.markdown(audio_tag, unsafe_allow_html=True)

# --------------------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------------------

st.set_page_config(page_title=APP_TITLE, page_icon="🛰️", layout="wide")
st.title(APP_TITLE)
if CREST_URL:
    st.markdown(crest_html(CREST_URL), unsafe_allow_html=True)

data = load_data()
last_updated = pretty_dt_uk(data.get("generated_at"))
st.markdown(
    f"""
    <div style="margin: 0.4rem 0 1.0rem 0;">
        <span style="font-size:1.1rem; font-weight:600;">Last update:</span>
        <span style="font-size:1.1rem;">{last_updated}</span>
    </div>
    """,
    unsafe_allow_html=True,
)

items = [it for it in (data.get("items") or []) if is_relevant(it)]

# --- New item alert (per session) ---
if "seen_ids" not in st.session_state:
    st.session_state.seen_ids = set()

current_ids = {it["id"] for it in items}
new_ids = sorted(list(current_ids - st.session_state.seen_ids))
if new_ids:
    st.success(f"New qualifying items: {len(new_ids)}")
    play_beep()
st.session_state.seen_ids = current_ids

# --- Controls ---
search = st.text_input("Search", "")
type_choices = ["major news", "local news", "social"]
type_filter = st.multiselect("Type", type_choices, default=type_choices)

def passes_filters(it: Dict[str, Any]) -> bool:
    if it.get("type") not in type_filter:
        return False
    if search:
        q = search.lower()
        blob = " ".join([
            it.get("title", ""), it.get("summary", ""),
            it.get("source", ""), json.dumps(it.get("geo", {})),
            " ".join(it.get("tags", []))
        ]).lower()
        if q not in blob:
            return False
    return True

items = [it for it in items if passes_filters(it)]

# Split into two panes
col_live, col_social = st.columns((2, 1))

with col_live:
    st.subheader("Live feed")
    live_items = [it for it in items if it.get("type") in ("major news", "local news")]
    for it in live_items:
        with st.container(border=True):
            st.markdown(f"**{it.get('title','(no title)')}**")
            st.caption(live_caption(it))
            summary = it.get("summary", "").strip()
            if summary:
                st.write(summary)
            url = it.get("url", "")
            if url:
                st.write(f"[Open source]({url})")

with col_social:
    st.subheader("Social media")
    soc_items = [it for it in items if it.get("type") == "social"]
    for it in soc_items:
        with st.container(border=True):
            st.markdown(f"**{it.get('title','(no title)')}**")
            st.caption(live_caption(it))
            summary = it.get("summary", "").strip()
            if summary:
                st.write(summary)
            url = it.get("url", "")
            if url:
                st.write(f"[Open source]({url})")

import json
import base64
from datetime import datetime
import re
import requests
import streamlit as st

# ------------------------- Page setup -------------------------
st.set_page_config(page_title="Global Situational Awareness Dashboard", layout="wide")
st.markdown("<meta http-equiv='refresh' content='60'>", unsafe_allow_html=True)

DATA_JSON_URL = os.getenv("DATA_JSON_URL", "").strip()                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             

# ------------------------- Country → flag (emoji) -------------------------
COUNTRY_FLAGS = {
    "United Kingdom": "🇬🇧", "United States": "🇺🇸", "Canada": "🇨🇦",
    "France": "🇫🇷", "Germany": "🇩🇪", "Netherlands": "🇳🇱", "Spain": "🇪🇸",
    "Italy": "🇮🇹", "Ireland": "🇮🇪", "Switzerland": "🇨🇭", "Austria": "🇦🇹",
    "Belgium": "🇧🇪", "Luxembourg": "🇱🇺", "Denmark": "🇩🇰", "Norway": "🇳🇴",
    "Sweden": "🇸🇪", "Finland": "🇫🇮", "Iceland": "🇮🇸", "Poland": "🇵🇱",
    "Czech Republic": "🇨🇿", "Slovakia": "🇸🇰", "Hungary": "🇭🇺",
    "Romania": "🇷🇴", "Bulgaria": "🇧🇬", "Greece": "🇬🇷", "Croatia": "🇭🇷",
    "Slovenia": "🇸🇮", "Türkiye": "🇹🇷",

    "United Arab Emirates": "🇦🇪", "Qatar": "🇶🇦", "Saudi Arabia": "🇸🇦",
    "Iran": "🇮🇷", "Iraq": "🇮🇶", "Jordan": "🇯🇴", "Lebanon": "🇱🇧",
    "Israel": "🇮🇱", "Palestine": "🇵🇸",

    "Singapore": "🇸🇬", "Hong Kong": "🇭🇰", "China": "🇨🇳", "Japan": "🇯🇵",
    "South Korea": "🇰🇷", "North Korea": "🇰🇵", "India": "🇮🇳",
    "Thailand": "🇹🇭", "Malaysia": "🇲🇾", "Philippines": "🇵🇭",
    "Indonesia": "🇮🇩", "Australia": "🇦🇺", "New Zealand": "🇳🇿",

    "Brazil": "🇧🇷", "Argentina": "🇦🇷", "Chile": "🇨🇱", "Mexico": "🇲🇽",

    "South Africa": "🇿🇦", "Kenya": "🇰🇪", "Egypt": "🇪🇬",
    "Nigeria": "🇳🇬", "Ghana": "🇬🇭",
}

# ------------------------- Floating crest -------------------------
def _crest_html():
    for fname, mime in (("crest.png","image/png"), ("crest.jpg","image/jpeg"), ("crest.jpeg","image/jpeg")):
        if os.path.exists(fname):
            with open(fname, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            return f'<img class="crest" src="data:{mime};base64,{b64}" width="80">'
    return ""  # no crest file present

st.markdown("""
<style>
.crest { position: fixed; top: 10px; right: 20px; z-index: 9999; }
</style>
""", unsafe_allow_html=True)

# ------------------------- Data loader -------------------------
@st.cache_data(ttl=30)
def load_data():
    if DATA_JSON_URL:
        r = requests.get(DATA_JSON_URL, timeout=20)
        r.raise_for_status()
        return r.json()
    try:
        with open("data.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"generated_at": None, "items": [], "trends": {"top_terms": []}}

# ------------------------- Beep -------------------------
_BEEP = "SUQzAwAAAAAFI1RTU0UAAAAPAAACc2RhdGEAAAAA"
def play_beep():
    st.markdown(
        f"<audio autoplay><source src='data:audio/wav;base64,{_BEEP}'></audio>",
        unsafe_allow_html=True,
    )

# ------------------------- Helpers -------------------------
def get_domain(url: str) -> str:
    m = re.search(r"https?://([^/]+)", url or "")
    return (m.group(1).lower() if m else "").replace("www.", "")

def classify_type(item) -> str:
    """
    Map each item into one of: 'major news', 'local news', 'social'
    """
    itype = (item.get("type") or "news").lower()
    if itype == "social":
        return "social"
    dom = get_domain(item.get("url", ""))
    MAJOR_DOMAINS = {
        "reuters.com","bbc.co.uk","apnews.com","avherald.com","gov.uk",
        "theguardian.com","sky.com","cnn.com","nytimes.com","aljazeera.com",
        "ft.com","bloomberg.com"
    }
    return "major news" if any(dom.endswith(d) for d in MAJOR_DOMAINS) else "local news"

def is_relevant(item) -> bool:
    tags = set(item.get("tags", []))
    return ("airport/security" in tags) or ("diplomatic" in tags)

# ------------------------- Load data -------------------------
data = load_data()
generated = data.get("generated_at")
items = data.get("items", [])

# ------------------------- Alert on new relevant items -------------------------
if "seen_ids" not in st.session_state:
    st.session_state.seen_ids = set()

current_ids = {it["id"] for it in items if is_relevant(it)}
new_ids = current_ids - st.session_state.seen_ids
if new_ids:
    st.success(f"New qualifying items: {len(new_ids)}")
    play_beep()
st.session_state.seen_ids |= current_ids

# ------------------------- Header -------------------------
st.title("Global Situational Awareness Dashboard")
st.markdown(_crest_html(), unsafe_allow_html=True)

from datetime import datetime

def pretty_dt(iso):
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%H:%M, %A %d %B %Y")
    except Exception:
        return iso or ""

data = load_data()
last = pretty_dt(data.get("generated_at"))

st.markdown(
    f"""
    <div style="margin: 0.5rem 0 1rem 0;">
        <span style="font-size:1.1rem; font-weight:600;">Last update:</span>
        <span style="font-size:1.1rem;">{last}</span>
    </div>
    """,
    unsafe_allow_html=True,
)

# ------------------------- Controls -------------------------
colA, colB = st.columns([2, 2])
q = colA.text_input("Search", "")
type_choices = ["major news", "local news", "social"]
type_filter = colB.multiselect("Type", type_choices, default=type_choices)

def passes_filters(it) -> bool:
    if type_filter and classify_type(it) not in type_filter:
        return False
    if q:
        txt = (it.get("title", "") + " " + it.get("summary", "")).lower()
        if q.lower() not in txt:
            return False
    return True

# Split items
live_items, social_items = [], []
for it in items:
    if not passes_filters(it):
        continue
    if classify_type(it) == "social":
        social_items.append(it)
    else:
        live_items.append(it)

live_items.sort(key=lambda x: x.get("published_at", ""), reverse=True)
social_items.sort(key=lambda x: x.get("published_at", ""), reverse=True)

# ------------------------- Render -------------------------
colLive, colSocial = st.columns([2, 1])

def render_card(col, it):
    title = it.get("title") or "(no title)"
    with col.expander(title):
        geo = it.get("geo", {}) or {}
        country = geo.get("country")
        flag = COUNTRY_FLAGS.get(country, "") if country else ""
        locbits = [
            geo.get("airport"),
            geo.get("city"),
            f"{country} {flag}" if country else None,
        ]
        loc = " | ".join([x for x in locbits if x])
        tags = ", ".join(it.get("tags", []))

        col.caption(
            f"{it.get('source','')} | {it.get('published_at','')}"
            + (f" | {loc}" if loc else "")
            + (f" | {tags}" if tags else "")
        )
        if it.get("summary"):
            col.write(it["summary"])
        if it.get("url"):
            col.write(f"[Open source]({it['url']})")

colLive.subheader("Live feed")
colSocial.subheader("Social media")

for it in live_items[:200]:
    render_card(colLive, it)

for it in social_items[:200]:
    render_card(colSocial, it)
