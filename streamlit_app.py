# streamlit_app.py
import time
import json
from datetime import datetime
from typing import Any, Dict, List
from urllib.parse import urlparse

import pytz
import requests
import pandas as pd
import streamlit as st

# --------------------------- Config ---------------------------
st.set_page_config(
    page_title="Global Situational Awareness Dashboard",
    layout="wide",
)

# Theme nudge: white background + visible control outlines
st.markdown("""
<style>
/* Light, readable UI */
html, body, [class*="st-"] {
  background: #ffffff !important;
  color: #111 !important;
}
/* Inputs / selects / buttons: subtle outline so they don't disappear on white */
.stTextInput>div>div>input,
.stMultiSelect [data-baseweb="select"] div[role="combobox"],
.stToggleSwitch label {
  border: 1px solid #cbd5e1 !important;
  border-radius: 6px !important;
}
.stButton button {
  border: 1px solid #cbd5e1 !important;
  border-radius: 8px !important;
}
/* Cards */
.block-container .card {
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  padding: .9rem 1rem;
  margin-bottom: .9rem;
  background: #fff;
}
</style>
""", unsafe_allow_html=True)

# Required secrets:
# - DATA_JSON_URL: raw URL to data.json (your repo's raw GitHub link)
# Optional secrets:
# - STATUS_JSON_URL: raw URL to status.json (same repo; see collector instructions below)
DATA_URL = st.secrets.get("DATA_JSON_URL", "").strip()
STATUS_URL = st.secrets.get("STATUS_JSON_URL", "").strip()

if not DATA_URL:
    st.error("Missing secret: DATA_JSON_URL")
    st.stop()

# If STATUS_JSON_URL not set, assume it's the same folder as data.json
if not STATUS_URL:
    p = urlparse(DATA_URL)
    if p.path.endswith("/data.json"):
        STATUS_URL = DATA_URL[:-len("data.json")] + "status.json"

# --------------------------- Helpers ---------------------------
@st.cache_data(ttl=60)
def fetch_json(url: str, timeout: int = 15) -> Dict[str, Any]:
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "GSA/streamlit"})
    r.raise_for_status()
    return r.json()

def uk_dt_str(iso: str) -> str:
    """Format ISO time in Europe/London as 'HH:MM, Friday 13 September 2025'."""
    if not iso:
        return ""
    try:
        dt_utc = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        uk = pytz.timezone("Europe/London")
        dt_uk = dt_utc.astimezone(uk)
        return dt_uk.strftime("%H:%M, %A %d %B %Y")
    except Exception:
        return iso

def get_text(it: Dict[str, Any], field: str, translate_on: bool) -> str:
    if translate_on:
        return it.get(f"{field}_en") or it.get(field) or ""
    return it.get(f"{field}_orig") or it.get(field) or ""

def passes_filters(it: Dict[str, Any], search: str, types: List[str], translate_on: bool) -> bool:
    if types and it.get("type") not in types:
        return False
    if search:
        hay = (get_text(it, "title", translate_on) + " " +
               get_text(it, "summary", translate_on)).lower()
        if search.lower() not in hay:
            return False
    return True

def render_item(it: Dict[str, Any], translate_on: bool) -> None:
    title = get_text(it, "title", translate_on) or "(no title)"
    summary = get_text(it, "summary", translate_on)
    with st.container():
        st.markdown(f"**{title}**")
        meta_bits = []
        if it.get("source"):
            meta_bits.append(it["source"])
        if it.get("published_at"):
            meta_bits.append(uk_dt_str(it["published_at"]))
        if it.get("geo") and isinstance(it["geo"], dict):
            g = it["geo"]
            loc = " | ".join([x for x in [g.get("airport"), g.get("city"), g.get("country")] if x])
            if loc:
                meta_bits.append(loc)
        if meta_bits:
            st.caption(" | ".join(meta_bits))
        if summary:
            st.write(summary)
        if it.get("url"):
            st.markdown(f"[Open source]({it['url']})")
        st.divider()

# --------------------------- Header ---------------------------
left, right = st.columns([0.85, 0.15])
with left:
    st.title("Global Situational Awareness Dashboard")
with right:
    # Refresh with visible feedback
    if st.button("🔄 Refresh", use_container_width=True):
        st.toast("Refreshing…")
        with st.spinner("Rebuilding view…"):
            try:
                st.cache_data.clear()
            except Exception:
                pass
            time.sleep(0.2)
            try:
                st.rerun()
            except Exception:
                st.experimental_rerun()

# Load data.json (always show *current* data)
try:
    data = fetch_json(DATA_URL)
except Exception as ex:
    st.error(f"Failed to load data.json: {ex}")
    st.stop()

generated = data.get("generated_at", "")
st.caption(f"**Last update:** {uk_dt_str(generated)}")

# --------------------------- Controls ---------------------------
controls_left, controls_right = st.columns([0.55, 0.45])

with controls_left:
    # Proper on/off switch for translation
    if "translate_to_en" not in st.session_state:
        st.session_state.translate_to_en = False
    st.session_state.translate_to_en = st.toggle(
        "Translate to English",
        value=st.session_state.translate_to_en,
        help="Show machine-translated titles and summaries where available."
    )
    search = st.text_input("Search", "")

with controls_right:
    type_choices = ["major news", "local news", "social"]
    selected_types = st.multiselect(
        "Type",
        type_choices,
        default=type_choices,
    )

# --------------------------- Live progress (status.json) ---------------------------
# If the collector is running and writing status.json in your repo during the job,
# show a progress bar. (See instructions below to enable this in collector/workflow.)
if STATUS_URL:
    try:
        status = fetch_json(STATUS_URL, timeout=8)
    except Exception:
        status = {}

    # Expected shape:
    # {"state":"running"|"idle"|"done",
    #  "stage":"news"/"official"/"weather"/"social",
    #  "current": 17, "total": 53,
    #  "last_feed":"example.com/rss",
    #  "updated_at":"…ISO…"}
    state = status.get("state", "idle")
    if state == "running":
        cur = int(status.get("current", 0))
        tot = max(int(status.get("total", 1)), 1)
        pct = min(max(cur / tot, 0.0), 1.0)
        prog = st.progress(pct, text=f"Collecting feeds ({cur}/{tot}) — {status.get('stage','')}")
        # Also show last touched feed
        if status.get("last_feed"):
            st.caption(f"Last feed: {status['last_feed']}")
    elif state == "done":
        st.info("Collector finished. Press **Refresh** to load the latest items.")
    # else: idle → no bar

st.divider()

# --------------------------- Body ---------------------------
live_col, social_col = st.columns(2)

items: List[Dict[str, Any]] = data.get("items", [])
translate_on = st.session_state.translate_to_en

with live_col:
    st.subheader("Live feed")
    for it in items:
        if it.get("type") == "social":
            continue
        if passes_filters(it, search, selected_types, translate_on):
            render_item(it, translate_on)

with social_col:
    st.subheader("Social media")
    for it in items:
        if it.get("type") != "social":
            continue
        if passes_filters(it, search, selected_types, translate_on):
            render_item(it, translate_on)
