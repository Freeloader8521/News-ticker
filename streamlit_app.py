import os
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
