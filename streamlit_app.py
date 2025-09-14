import os
import json
from datetime import datetime
import pytz
import streamlit as st
import requests

# ---------------- Config ----------------
DATA_JSON_URL = os.environ.get(
    "DATA_JSON_URL",
    "https://raw.githubusercontent.com/Freeloader8521/News-ticker/main/data.json"
)

# ---------------- Utils ----------------
def pretty_dt(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        uk = dt.astimezone(pytz.timezone("Europe/London"))
        return uk.strftime("%H:%M, %A %d %B %Y")
    except Exception:
        return iso or ""

@st.cache_data(ttl=300)
def fetch_json():
    try:
        r = requests.get(DATA_JSON_URL, timeout=20)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {"generated_at": None, "items": []}

# ---------------- Layout ----------------
st.set_page_config(page_title="Global Situational Awareness Dashboard", layout="wide")

# CSS – force light mode, outlines on buttons
st.markdown(
    """
    <style>
    html, body, [class*="st-"] {
        color: #111 !important;
        background: #fff !important;
    }
    .block-container { padding-top: 1rem; padding-bottom: 1rem; }
    .stButton button {
        border: 1px solid #444 !important;
        padding: 0.4rem 1rem;
        border-radius: 4px;
    }
    .stCheckbox label {
        font-weight: 600;
    }
    h2 {
        margin-top: 1rem;
        border-bottom: 2px solid #ccc;
        padding-bottom: 0.3rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------- Header ----------------
data = fetch_json()
last = pretty_dt(data.get("generated_at"))

st.title("Global Situational Awareness Dashboard")

colTopA, colTopB = st.columns([6, 1])
with colTopA:
    st.markdown(f"**Last update:** {last}")

# Refresh button with spinner + rerun
with colTopB:
    if st.button("Refresh", use_container_width=True):
        with st.spinner("Refreshing feeds…"):
            st.cache_data.clear()
            st.rerun()

# Translate toggle
translate = st.checkbox("Translate to English", value=True)

# ---------------- Controls ----------------
colSearch, colType = st.columns([3, 2])
with colSearch:
    search = st.text_input("Search", "")
with colType:
    type_choices = ["major news", "local news", "social"]
    type_filter = st.multiselect("Type", type_choices, default=type_choices)

# ---------------- Content ----------------
items = data.get("items", [])
if search:
    items = [it for it in items if search.lower() in (it.get("title", "") + it.get("summary", "")).lower()]
if type_filter:
    items = [it for it in items if it.get("type") in type_filter]

colFeed, colSocial = st.columns([2, 1])

# Live feed (news)
with colFeed:
    st.subheader("Live feed")
    for it in items:
        if it.get("type") == "social":
            continue
        title = it.get("title_en") if translate else it.get("title_orig")
        summary = it.get("summary_en") if translate else it.get("summary_orig")
        st.markdown(f"### {title}")
        st.markdown(
            f"*{it.get('source')} | {pretty_dt(it.get('published_at'))}*  \n{summary}"
        )
        if it.get("url"):
            st.markdown(f"[Open source]({it['url']})")
        st.markdown("---")

# Social media
with colSocial:
    st.subheader("Social media")
    for it in items:
        if it.get("type") != "social":
            continue
        title = it.get("title_en") if translate else it.get("title_orig")
        summary = it.get("summary_en") if translate else it.get("summary_orig")
        st.markdown(f"### {title}")
        st.markdown(
            f"*{it.get('source')} | {pretty_dt(it.get('published_at'))}*  \n{summary}"
        )
        if it.get("url"):
            st.markdown(f"[Open source]({it['url']})")
        st.markdown("---")
