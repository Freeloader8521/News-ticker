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

STATUS_JSON_URL = os.environ.get(
    "STATUS_JSON_URL",
    "https://raw.githubusercontent.com/Freeloader8521/News-ticker/main/status.json"
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

def _safe_int(x, default=0):
    try:
        return int(x)
    except Exception:
        return default

@st.cache_data(ttl=15)
def fetch_status():
    """Read status.json from GitHub (or your custom URL)."""
    try:
        r = requests.get(STATUS_JSON_URL, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}

def render_status():
    """Draw the status/progress panel."""
    s = fetch_status()
    st.markdown("#### Collector status")

    if not s:
        st.info("Waiting for status.json…")
        return

    state = (s.get("state") or "unknown").lower()
    stage = s.get("stage", "")
    cur   = _safe_int(s.get("current"), 0)
    tot   = max(1, _safe_int(s.get("total"), 1))
    pct   = min(1.0, max(0.0, cur / tot))
    msg   = s.get("message", "")
    last  = s.get("last_run")

    # Progress bar + state badge
    colA, colB = st.columns([0.75, 0.25])
    with colA:
        st.progress(pct, text=f"{stage or 'progress'} — {cur} of {tot}")
    with colB:
        badge = {
            "running": "🟡 RUNNING",
            "success": "🟢 SUCCESS",
            "failed":  "🔴 FAILED",
        }.get(state, state.upper())
        st.markdown(f"**{badge}**")

    if last:
        st.caption(f"Last run: {pretty_dt(last)}")
    if msg:
        st.write(msg)

    errs = s.get("errors") or []
    if errs:
        with st.expander(f"Errors ({len(errs)})"):
            for e in errs:
                st.write(f"- {e}")

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
with colTopB:
    if st.button("Refresh", use_container_width=True):
        with st.spinner("Refreshing feeds…"):
            st.cache_data.clear()
            st.rerun()

# ⬇️ Show the collector status panel here
render_status()

# Translate toggle (acts like ON/OFF switch)
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
