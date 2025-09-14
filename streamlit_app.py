# streamlit_app.py

from __future__ import annotations

import json
import requests
from datetime import datetime
from typing import Dict, Any, List, Tuple

import streamlit as st

# Optional (for nice local time stamps)
try:
    import pytz
    LONDON = pytz.timezone("Europe/London")
except Exception:
    LONDON = None

# ------------------------ App config ------------------------

st.set_page_config(
    page_title="Global Situational Awareness Dashboard",
    layout="wide",
)

# Force light palette + button outlines (keeps text readable on white)
st.markdown(
    """
<style>
html, body, [class*="st-"] { color:#111 !important; background:#ffffff !important; }
.block-container { padding-top:1.25rem; padding-bottom:2rem; }
.stButton>button, .stDownloadButton>button { border:1px solid #bdbdbd !important; box-shadow:none !important; }
.stButton>button:hover { border-color:#888 !important; }
.stCheckbox>label { font-weight:500; }
.card { padding:0.75rem 1rem; border:1px solid #e6e6e6; border-radius:10px; background:#fff; }
.card + .card { margin-top:0.75rem; }
.meta { color:#666; font-size:0.9rem; margin-bottom:0.25rem; }
.title-link { font-weight:700; font-size:1.02rem; text-decoration:none; }
.title-link:hover { text-decoration:underline; }
.action-row { display:flex; gap:.75rem; align-items:center; }
.smallmuted { color:#777; font-size:.9rem; }
.badge { display:inline-block; border:1px solid #ddd; border-radius:999px; padding:.1rem .5rem; font-size:.75rem; color:#555; }
</style>
    """,
    unsafe_allow_html=True,
)

# ------------------------ Secrets / URLs ------------------------

DATA_JSON_URL = st.secrets.get("DATA_JSON_URL", "").strip()
STATUS_JSON_URL = st.secrets.get("STATUS_JSON_URL", "").strip()

if not DATA_JSON_URL:
    st.error("DATA_JSON_URL secret is missing. Add it in Streamlit → Manage app → Settings → Secrets.")
    st.stop()

# ------------------------ Helpers ------------------------

@st.cache_data(ttl=60, show_spinner=False)
def fetch_json(url: str) -> Dict[str, Any]:
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return r.json()

def pretty_time(iso: str) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if LONDON:
            dt = dt.astimezone(LONDON)
        return dt.strftime("%H:%M, %A %d %B %Y")
    except Exception:
        return iso

def choose_text(item: Dict[str, Any], translate_on: bool) -> Tuple[str, str]:
    """Return (title, summary) based on toggle, falling back gracefully."""
    if translate_on:
        title = item.get("title_en") or item.get("title") or item.get("title_orig") or "(no title)"
        summ = item.get("summary_en") or item.get("summary") or item.get("summary_orig") or ""
    else:
        title = item.get("title_orig") or item.get("title") or item.get("title_en") or "(no title)"
        summ = item.get("summary_orig") or item.get("summary") or item.get("summary_en") or ""
    return title, summ

def caption_line(it: Dict[str, Any]) -> str:
    geo = it.get("geo", {}) or {}
    loc_bits: List[str] = []
    if geo.get("airport"):
        loc_bits.append(str(geo.get("airport")))
    if geo.get("city"):
        loc_bits.append(str(geo.get("city")))
    if geo.get("country"):
        loc_bits.append(str(geo.get("country")))
    loc = " | ".join(loc_bits)
    when = pretty_time(it.get("published_at", ""))
    src = it.get("source", "")
    parts = []
    if src:
        parts.append(src)
    if when:
        parts.append(when)
    if loc:
        parts.append(loc)
    if it.get("iata"):
        parts.append(it["iata"])
    if it.get("type"):
        parts.append(it["type"])
    return " | ".join(parts)

def filtered(items: List[Dict[str, Any]], q: str, allowed: List[str]) -> List[Dict[str, Any]]:
    q = (q or "").strip().lower()
    out = []
    for it in items:
        if allowed and (it.get("type") not in allowed):
            continue
        hay = " ".join([
            it.get("title", ""),
            it.get("title_en", ""),
            it.get("title_orig", ""),
            it.get("summary", ""),
            it.get("summary_en", ""),
            it.get("summary_orig", ""),
            caption_line(it)
        ]).lower()
        if q and q not in hay:
            continue
        out.append(it)
    return out

# ------------------------ Header / Controls ------------------------

st.title("Global Situational Awareness Dashboard")

# Last update
data = fetch_json(DATA_JSON_URL)
last = pretty_time(data.get("generated_at", ""))

colH, colBtn = st.columns([0.85, 0.15])
with colH:
    st.markdown(f"**Last update:** {last}")

# refresh → clear caches and rerun
def do_refresh():
    st.cache_data.clear()   # clear all cached functions safely
    st.experimental_rerun()

with colBtn:
    st.button("Refresh", on_click=do_refresh, use_container_width=True))

with colBtn:
    st.button("Refresh", on_click=do_refresh, use_container_width=True)

# Translate toggle (use st.toggle if available; fallback to checkbox)
try:
    translate_on = st.toggle("Translate to English", value=st.session_state.get("translate_on", True))
except Exception:
    translate_on = st.checkbox("Translate to English", value=st.session_state.get("translate_on", True))
st.session_state.translate_on = translate_on

# Search & Type filter
q = st.text_input("Search", "", placeholder="Find by keyword, airport, city, country, source…")

type_choices = ["major news", "local news", "social"]
type_filter = st.multiselect("Type", type_choices, default=type_choices)

# ------------------------ Progress from status.json ------------------------

if STATUS_JSON_URL:
    try:
        status = fetch_json(STATUS_JSON_URL)
    except Exception:
        status = {}
else:
    status = {}

if status:
    done = 0
    tot = 1
    label = ""
    note = ""
    try:
        done = int(status.get("done", 0))
        tot = max(1, int(status.get("total", 1)))
    except Exception:
        done, tot = 0, 1
    label = status.get("current", "") or ""
    note = status.get("note", "") or status.get("stage", "")

    pc = min(1.0, max(0.0, done / float(tot or 1)))
    cA, cB = st.columns([0.7, 0.3])
    with cA:
        st.progress(pc, text=f"{done} of {tot} • {label}")
    with cB:
        if note:
            st.caption(note)

st.divider()

# ------------------------ Body: two columns ------------------------

left, right = st.columns(2)

items: List[Dict[str, Any]] = data.get("items", [])
# ensure newest first
items = sorted(items, key=lambda x: x.get("published_at", ""), reverse=True)

# left: live feed (news only)
with left:
    st.subheader("Live feed")
    lf = filtered(items, q, [t for t in type_filter if t in ("major news", "local news")])
    for it in lf:
        title, summ = choose_text(it, translate_on)
        src_line = caption_line(it)
        st.markdown('<div class="card">', unsafe_allow_html=True)
        link = it.get("url") or "#"
        st.markdown(f'<a href="{link}" target="_blank" class="title-link">{title}</a>', unsafe_allow_html=True)
        if src_line:
            st.markdown(f'<div class="meta">{src_line}</div>', unsafe_allow_html=True)
        if summ:
            st.write(summ)
        # footer
        with st.container():
            st.markdown(
                f'<div class="action-row"><span class="badge">open source</span>'
                f' <a href="{link}" target="_blank" class="smallmuted"> {it.get("source","")} </a></div>',
                unsafe_allow_html=True,
            )
        st.markdown("</div>", unsafe_allow_html=True)

# right: social only
with right:
    st.subheader("Social media")
    sf = filtered(items, q, ["social"] if "social" in type_filter else [])
    for it in sf:
        title, summ = choose_text(it, translate_on)
        if (not title) or title.strip().lower() in ("(no title)", "no title"):
            # fallback: first line of the post
            first = (summ or "").strip().splitlines()
            title = next((ln for ln in first if ln.strip()), "(no title)")
        src_line = caption_line(it)
        st.markdown('<div class="card">', unsafe_allow_html=True)
        link = it.get("url") or "#"
        st.markdown(f'<a href="{link}" target="_blank" class="title-link">{title}</a>', unsafe_allow_html=True)
        if src_line:
            st.markdown(f'<div class="meta">{src_line}</div>', unsafe_allow_html=True)
        if summ:
            st.write(summ)
        with st.container():
            st.markdown(
                f'<div class="action-row"><span class="badge">open source</span>'
                f' <a href="{link}" target="_blank" class="smallmuted"> {it.get("source","")} </a></div>',
                unsafe_allow_html=True,
            )
        st.markdown("</div>", unsafe_allow_html=True)
