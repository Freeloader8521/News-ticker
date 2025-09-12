import os
import json
import base64
from datetime import datetime
import re
import requests
import streamlit as st

# ------------------------- Page setup -------------------------
st.set_page_config(page_title="Airport & UK Missions Dashboard", layout="wide")
st.markdown("<meta http-equiv='refresh' content='60'>", unsafe_allow_html=True)

DATA_JSON_URL = os.getenv("DATA_JSON_URL", "").strip()

# Country → flag (emoji)
COUNTRY_FLAGS = {
    "United Kingdom": "🇬🇧", "United States": "🇺🇸", "Canada": "🇨🇦",
    "France": "🇫🇷", "Germany": "🇩🇪", "Netherlands": "🇳🇱", "Spain": "🇪🇸",
    "Italy": "🇮🇹", "Ireland": "🇮🇪", "Switzerland": "🇨🇭", "Austria": "🇦🇹",
    "United Arab Emirates": "🇦🇪", "Qatar": "🇶🇦", "Türkiye": "🇹🇷",
    "Singapore": "🇸🇬", "Hong Kong": "🇭🇰", "Japan": "🇯🇵", "South Korea": "🇰🇷",
    "Thailand": "🇹🇭", "Malaysia": "🇲🇾", "India": "🇮🇳", "China": "🇨🇳",
    "Philippines": "🇵🇭", "Indonesia": "🇮🇩", "Australia": "🇦🇺", "New Zealand": "🇳🇿",
    "South Africa": "🇿🇦", "Kenya": "🇰🇪", "Egypt": "🇪🇬", "Brazil": "🇧🇷",
    "Argentina": "🇦🇷", "Mexico": "🇲🇽"
}

# Domains we treat as "major" wires/outlets
MAJOR_DOMAINS = {
    "reuters.com", "bbc.co.uk", "apnews.com", "avherald.com", "gov.uk",
    # add more here any time (cnn.com, theguardian.com, etc.)
}

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
    - If item['type'] == 'social' -> 'social'
    - Else (news): look at domain
    """
    itype = (item.get("type") or "news").lower()
    if itype == "social":
        return "social"
    dom = get_domain(item.get("url", ""))
    return "major news" if any(dom.endswith(d) for d in MAJOR_DOMAINS) else "local news"

def is_relevant(item) -> bool:
    """Relevant = tagged airport/security or diplomatic."""
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

# ------------------------- Header + crest -------------------------
st.title("Airport & UK Missions Situational Dashboard")

st.markdown(
    """
<style>
.crest { position: fixed; top: 10px; right: 20px; z-index: 9999; }
</style>
""",
    unsafe_allow_html=True,
)
# Safe to leave even if the image isn't present
st.markdown('<img src="crest.png" class="crest" width="80">', unsafe_allow_html=True)

# Timestamp
if generated:
    try:
        ts = datetime.fromisoformat(generated.replace("Z", "+00:00"))
        st.caption(f"Last update: {ts.isoformat()}")
    except Exception:
        st.caption(f"Last update: {generated}")
else:
    st.warning("No data yet. Check DATA_JSON_URL or wait for the collector to run.")

# ------------------------- Controls -------------------------
colA, colB = st.columns([2, 2])
q = colA.text_input("Search", "")
type_choices = ["major news", "local news", "social"]
type_filter = colB.multiselect("Type", type_choices, default=type_choices)

def passes_filters(it) -> bool:
    if type_filter:
        if classify_type(it) not in type_filter:
            return False
    if q:
        txt = (it.get("title", "") + " " + it.get("summary", "")).lower()
        if q.lower() not in txt:
            return False
    return True

# Split into live vs social
live_items = []
social_items = []
for it in items:
    if not passes_filters(it):
        continue
    bucket = classify_type(it)
    if bucket == "social":
        social_items.append(it)
    else:
        live_items.append(it)

# Sort both newest first
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

        # Header line
        col.caption(
            f"{it.get('source','')} | {it.get('published_at','')}"
            + (f" | {loc}" if loc else "")
            + (f" | {tags}" if tags else "")
        )
        # Summary + link
        if it.get("summary"):
            col.write(it["summary"])
        if it.get("url"):
            col.write(f"[Open source]({it['url']})")

# Column headers
colLive.subheader("Live feed")
colSocial.subheader("Social media")

# Render lists
for it in live_items[:200]:
    render_card(colLive, it)

for it in social_items[:200]:
    render_card(colSocial, it)

