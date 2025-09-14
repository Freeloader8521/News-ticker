# streamlit_app.py
import os
from datetime import datetime
import pytz
import requests
import streamlit as st

# ---------------- Config ----------------
DATA_JSON_URL = os.environ.get(
    "DATA_JSON_URL",
    "https://raw.githubusercontent.com/Freeloader8521/News-ticker/main/data.json",
)
STATUS_JSON_URL = os.environ.get(
    "STATUS_JSON_URL",
    "https://raw.githubusercontent.com/Freeloader8521/News-ticker/main/status.json",
)

# ---------------- Helpers ----------------
def pretty_dt(iso: str) -> str:
    """Format ISO8601 -> 'HH:MM, Weekday DD Month YYYY' in UK time."""
    try:
        dt = datetime.fromisoformat((iso or "").replace("Z", "+00:00"))
        uk = dt.astimezone(pytz.timezone("Europe/London"))
        return uk.strftime("%H:%M, %A %d %B %Y")
    except Exception:
        return iso or ""

@st.cache_data(ttl=300)
def fetch_json(url: str):
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}

@st.cache_data(ttl=15)
def fetch_status(url: str):
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}

# ---------------- Page setup ----------------
st.set_page_config(page_title="Global Situational Awareness Dashboard", layout="wide")

# Force light theme & tidy UI
st.markdown(
    """
    <style>
      html, body, [class*="st-"] { color:#111 !important; background:#fff !important; }
      .block-container { padding-top: 1rem; padding-bottom: 1.25rem; }
      .stButton button, .stDownloadButton button {
        border: 1px solid #444 !important; border-radius: 6px;
        padding: .45rem 1rem; font-weight: 600;
      }
      .stToggle { padding-top:.25rem; }
      h2 { margin-top: 1rem; border-bottom: 2px solid #ddd; padding-bottom: .35rem; }
      .item-divider { margin: .6rem 0 1.1rem; border-bottom: 1px solid #eee; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------- Header ----------------
data = fetch_json(DATA_JSON_URL)
generated = pretty_dt(data.get("generated_at"))
st.title("Global Situational Awareness Dashboard")

top_a, top_b = st.columns([6, 1])
with top_a:
    st.markdown(f"**Last update:** {generated}")
with top_b:
    if st.button("Refresh", use_container_width=True):
        with st.spinner("Refreshing feeds…"):
            st.cache_data.clear()
        st.rerun()

# ---------------- Status panel ----------------
st.subheader("Collector status")
status = fetch_status(STATUS_JSON_URL)

started = status.get("started_at", "N/A")
finished = status.get("finished_at", "N/A")
total = status.get("total", 0) or 0
done = status.get("done", 0) or 0
current = status.get("current", "")
note = status.get("note", "")

# Show progress if we have counts; otherwise a small info message
if isinstance(total, (int, float)) and isinstance(done, (int, float)) and total >= 0:
    pct = int(round((done / max(1, total)) * 100))
    st.progress(pct, text=f"{int(done)}/{int(total)} feeds ({pct}%)")
else:
    st.info("No progress information yet.")

left_s, right_s = st.columns([2.2, 2])
with left_s:
    st.markdown(f"**Started:** {started}")
    st.markdown(f"**Finished:** {finished}")
with right_s:
    if current:
        st.markdown(f"**Current feed:** `{current}`")
    if note:
        st.markdown(f"**Note:** {note}")

# ---------------- Translate toggle ----------------
translate = st.toggle("Translate to English", value=True)

# ---------------- Controls ----------------
c_search, c_types = st.columns([3, 2])
with c_search:
    query = st.text_input("Search", "")
with c_types:
    type_choices = ["major news", "local news", "social"]
    type_filter = st.multiselect("Type", type_choices, default=type_choices)

# ---------------- Content ----------------
items = data.get("items", [])

# Filter by type
if type_filter:
    items = [it for it in items if it.get("type") in type_filter]

# Filter by query
if query:
    q = query.lower()
    def txt(it):
        # prefer translated fields when the toggle is on
        title = (it.get("title_en") if translate else it.get("title_orig")) or it.get("title", "")
        summary = (it.get("summary_en") if translate else it.get("summary_orig")) or it.get("summary", "")
        return f"{title} {summary}".lower()
    items = [it for it in items if q in txt(it)]

# Two-column layout: news (left), social (right)
col_news, col_social = st.columns([2, 1])

with col_news:
    st.subheader("Live feed")
    for it in items:
        if it.get("type") == "social":
            continue
        title = (it.get("title_en") if translate else it.get("title_orig")) or it.get("title") or "(no title)"
        summary = (it.get("summary_en") if translate else it.get("summary_orig")) or it.get("summary") or ""
        meta = f"*{it.get('source','')} | {pretty_dt(it.get('published_at'))}*"
        st.markdown(f"### {title}")
        if meta.strip("* "):
            st.markdown(meta)
        if summary:
            st.markdown(summary)
        if it.get("url"):
            st.markdown(f"[Open source]({it['url']})")
        st.markdown('<div class="item-divider"></div>', unsafe_allow_html=True)

with col_social:
    st.subheader("Social media")
    for it in items:
        if it.get("type") != "social":
            continue
        title = (it.get("title_en") if translate else it.get("title_orig")) or it.get("title") or "(no title)"
        summary = (it.get("summary_en") if translate else it.get("summary_orig")) or it.get("summary") or ""
        meta = f"*{it.get('source','')} | {pretty_dt(it.get('published_at'))}*"
        st.markdown(f"### {title}")
        if meta.strip("* "):
            st.markdown(meta)
        if summary:
            st.markdown(summary)
        if it.get("url"):
            st.markdown(f"[Open source]({it['url']})")
        st.markdown('<div class="item-divider"></div>', unsafe_allow_html=True)
