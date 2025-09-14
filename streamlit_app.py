# streamlit_app.py
import os
import json
import time
from datetime import datetime
import pytz
import requests
import streamlit as st

# ------------------------ Config ------------------------

APP_TITLE = "Global Situational Awareness Dashboard"
LOCAL_TZ = "Europe/London"

DATA_URL = st.secrets.get("DATA_JSON_URL", "").strip()
STATUS_URL = st.secrets.get("STATUS_JSON_URL", "").strip()

DATA_FILE_FALLBACK = "data.json"
STATUS_FILE_FALLBACK = "status.json"

# ------------------------ Small helpers ------------------------

def pretty_dt_iso(iso: str) -> str:
    """
    Render ISO8601 timestamp as: 14:55, Friday 13 August 2025 (UK time with DST).
    Falls back gracefully on errors.
    """
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        tz = pytz.timezone(LOCAL_TZ)
        dt_uk = dt.astimezone(tz)
        return dt_uk.strftime("%H:%M, %A %d %B %Y")
    except Exception:
        return iso or ""

@st.cache_data(show_spinner=False, ttl=60)
def fetch_json_from_url(url: str):
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return r.json()

def load_data():
    # Try remote first (if configured), then local fallback
    if DATA_URL:
        try:
            return fetch_json_from_url(DATA_URL)
        except Exception as ex:
            st.warning(f"Couldn’t fetch DATA_JSON_URL ({ex}). Falling back to local {DATA_FILE_FALLBACK}.")
    try:
        with open(DATA_FILE_FALLBACK, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as ex:
        st.error(f"No data found. Make sure data.json exists or secrets DATA_JSON_URL is set. ({ex})")
        return {"generated_at": "", "items": [], "trends": {}}

def load_status():
    # Optional progress file (status.json)
    if STATUS_URL:
        try:
            return fetch_json_from_url(STATUS_URL)
        except Exception:
            pass
    try:
        with open(STATUS_FILE_FALLBACK, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def classify(it):
    """Use the collector’s field if present; else infer."""
    t = (it.get("type") or "").lower()
    if t in ("major news", "local news", "social"):
        return t
    # Fallback inference
    src = (it.get("source") or "").lower()
    if any(src.endswith(d) for d in (
        "reuters.com","bbc.co.uk","apnews.com","theguardian.com","nytimes.com",
        "bloomberg.com","ft.com","cnn.com","aljazeera.com","sky.com","latimes.com",
        "cbc.ca","theglobeandmail.com","scmp.com","straitstimes.com","japantimes.co.jp",
        "avherald.com","gov.uk","faa.gov","easa.europa.eu","caa.co.uk","ntsb.gov",
        "bea.aero","atsb.gov.au","caa.govt.nz","tc.gc.ca","noaa.gov","nhc.noaa.gov",
        "weather.gov"
    )):
        return "major news"
    return "local news"

def item_matches_search(it, q):
    if not q:
        return True
    q = q.lower()
    fields = [
        it.get("title_en") or it.get("title_orig") or "",
        it.get("summary_en") or it.get("summary_orig") or "",
        it.get("source") or "",
        it.get("url") or "",
        " ".join(it.get("tags") or []),
        json.dumps(it.get("geo") or {}, ensure_ascii=False)
    ]
    return any(q in (f or "").lower() for f in fields)

# ------------------------ Page setup & CSS ------------------------

st.set_page_config(page_title=APP_TITLE, layout="wide")

# Force a light palette and readable borders
st.markdown(
    """
    <style>
    html, body, [class*="st-"] { color: #111 !important; background: #fff !important; }

    /* Inputs, selects, pills */
    .stTextInput > div > div > input,
    .stMultiSelect [data-baseweb="select"] div,
    .stSelectbox [data-baseweb="select"] div {
        border: 1px solid #d0d7de !important;
        background: #fff !important;
        color: #111 !important;
    }

    /* Buttons */
    .stButton > button {
        border: 1px solid #1f6feb !important;
        color: #1f6feb !important;
        background: #fff !important;
        padding: 0.4rem 0.9rem;
        border-radius: 6px;
        font-weight: 600;
    }
    .stButton > button:hover { background: #f6f8fa !important; }

    /* Checkbox/Toggle label visibility */
    label, .stCheckbox label { color: #111 !important; }

    /* Card-ish feel for items */
    .item-card {
        border: 1px solid #e6e6e6;
        border-radius: 8px;
        padding: 0.8rem 1rem;
        margin-bottom: 0.75rem;
        background: #fff;
    }
    .meta { color: #5f6a6a; font-size: 0.9rem; margin-bottom: 0.25rem; }
    .source { font-weight: 600; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ------------------------ Header ------------------------

st.title(APP_TITLE)

# Top right: Refresh
col_title, col_refresh = st.columns([0.8, 0.2])
with col_refresh:
    if st.button("Refresh", use_container_width=True):
        # Clear cached fetches so we re-download; also give the user a feeling of live progress
        fetch_json_from_url.clear()
        st.session_state["_request_refresh"] = True
        st.rerun()

# Last update time
data = load_data()
last = pretty_dt_iso(data.get("generated_at", ""))

st.markdown(
    f"**Last update:** {last}"
)

# Translate toggle (actual visible checkbox)
translate = st.checkbox("Translate to English", value=True, help="Show English translations when available")

# ------------------------ Live status / progress ------------------------

# If the collector is running, status.json will advance current/total.
status = load_status()
if status:
    state = status.get("state")            # starting | running | done | error
    stage = status.get("stage", "")
    cur = int(status.get("current", 0))
    tot = max(1, int(status.get("total", 1)))

    colA, colB = st.columns([0.7, 0.3])
    with colA:
        st.progress(min(1.0, cur / tot))
    with colB:
        st.write(f"{cur} of {tot} • {stage} • {state or ''}")

    # If the user pressed Refresh, give a short, visible polling loop (3s) so they
    # can see progress tick without waiting a whole rerun cycle.
    if st.session_state.get("_request_refresh"):
        for _ in range(3):
            time.sleep(1)
            status = load_status()
            cur = int(status.get("current", 0))
            tot = max(1, int(status.get("total", 1)))
            st.session_state["_live_cur"] = cur
            st.session_state["_live_tot"] = tot
        # clear the flag; next rerun is manual
        st.session_state["_request_refresh"] = False

st.divider()

# ------------------------ Controls ------------------------

q = st.text_input("Search", "")
type_choices = ["major news", "local news", "social"]
type_filter = st.multiselect("Type", type_choices, default=type_choices)

# ------------------------ Buckets & rendering ------------------------

def pick_title(it):
    return (it.get("title_en") if translate else it.get("title_orig")) \
           or it.get("title") or "(no title)"

def pick_summary(it):
    return (it.get("summary_en") if translate else it.get("summary_orig")) \
           or it.get("summary") or ""

def render_item(it):
    title = pick_title(it)
    url = it.get("url") or "#"
    src = it.get("source") or "open source"
    when = pretty_dt_iso(it.get("published_at", ""))
    geo = it.get("geo") or {}
    geo_bits = " | ".join([x for x in [geo.get("airport"), geo.get("city"), geo.get("country"), geo.get("iata")] if x])

    st.markdown('<div class="item-card">', unsafe_allow_html=True)
    st.markdown(f'**[{title}]({url})**  ', unsafe_allow_html=True)
    st.markdown(
        f'<div class="meta">'
        f'<span class="source">{src}</span> | {when}'
        f'{(" | " + geo_bits) if geo_bits else ""}'
        f'</div>',
        unsafe_allow_html=True
    )
    st.write(pick_summary(it))
    st.markdown('</div>', unsafe_allow_html=True)

items = data.get("items", [])

# Filter
items = [it for it in items if classify(it) in type_filter and item_matches_search(it, q)]

colL, colR = st.columns(2)
with colL:
    st.subheader("Live feed")
    for it in [i for i in items if classify(i) != "social"][:150]:
        render_item(it)

with colR:
    st.subheader("Social media")
    for it in [i for i in items if classify(i) == "social"][:150]:
        render_item(it)
