import os
import json
import time
from datetime import datetime
import pytz
import requests
import streamlit as st

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
def fetch_json(url):
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}

def poll_status_bar():
    """Poll status.json and update progress bar until finished."""
    status_container = st.empty()
    prog = status_container.progress(0, text="Starting…")

    while True:
        try:
            r = requests.get(STATUS_JSON_URL, timeout=10)
            if r.status_code == 200:
                status = r.json()
                cur = int(status.get("current", 0) or 0)
                tot = max(1, int(status.get("total", 1) or 1))
                stage = status.get("stage", "")
                state = status.get("state", "")

                prog.progress(
                    min(cur / tot, 1.0),
                    text=f"{cur}/{tot} feeds processed ({stage}, {state})"
                )

                if state.lower() == "done":
                    break
        except Exception:
            prog.progress(0, text="Waiting for status.json…")

        time.sleep(3)  # poll every 3s

    status_container.success("Refresh complete ✅")
    time.sleep(1)
    st.cache_data.clear()
    st.rerun()

# ---------------- Layout ----------------
st.set_page_config(page_title="Global Situational Awareness Dashboard", layout="wide")

# CSS tweaks
st.markdown(
    """
    <style>
    html, body, [class*="st-"] {
        color: #111 !important;
        background: #fff !important;
    }
    .stButton button {
        border: 1px solid #444 !important;
        padding: 0.4rem 1rem;
        border-radius: 4px;
        font-weight: 600;
    }
    .toggle-on {
        background: #28a745 !important;
        color: white !important;
    }
    .toggle-off {
        background: #dc3545 !important;
        color: white !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------- Header ----------------
data = fetch_json(DATA_JSON_URL) or {}
last = pretty_dt(data.get("generated_at"))

st.title("Global Situational Awareness Dashboard")

colTopA, colTopB = st.columns([6, 1])
with colTopA:
    st.markdown(f"**Last update:** {last}")

with colTopB:
    if st.button("Refresh", use_container_width=True):
        with st.spinner("Refreshing feeds…"):
            poll_status_bar()

# ---------------- Translate toggle ----------------
if "translate" not in st.session_state:
    st.session_state["translate"] = True

if st.session_state["translate"]:
    if st.button("Translate: ON", key="toggle_on"):
        st.session_state["translate"] = False
        st.rerun()
else:
    if st.button("Translate: OFF", key="toggle_off"):
        st.session_state["translate"] = True
        st.rerun()

translate = st.session_state["translate"]

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
