# streamlit_app.py

import json
from typing import Any, Dict, List
from datetime import datetime
import pytz
import streamlit as st

# ----------------------------- Page Config -----------------------------
st.set_page_config(
    page_title="Global Situational Awareness Dashboard",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ----------------------------- Custom CSS -----------------------------
st.markdown(
    """
    <style>
    /* Force light theme colours */
    html, body, [class*="st-"] {
        color: #111 !important;
        background: #ffffff !important;
    }

    /* Container spacing */
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 2rem;
    }

    /* Links */
    a, a:visited { color: #0b5ed7 !important; text-decoration: none; }
    a:hover { text-decoration: underline; }

    /* Headings */
    h1, h2, h3, h4, h5, h6 { color: #111 !important; }

    /* Inputs */
    input, textarea, .stTextInput input, .stMultiSelect, .stSelectbox {
      color: #111 !important;
      background: #fff !important;
    }

    /* Style Refresh button */
    button[kind="secondary"] {
      border: 1px solid #333 !important;
      border-radius: 6px !important;
      background: #f8f8f8 !important;
      color: #111 !important;
      font-weight: 500;
    }

    /* Checkbox outline ("Translate to English") */
    div[data-testid="stCheckbox"] {
      border: 1px solid #333 !important;
      border-radius: 6px !important;
      padding: 6px 10px !important;
      margin-bottom: 10px !important;
      background: #f8f8f8 !important;
    }

    /* Article cards */
    .article-card {
      border: 1px solid #ddd;
      border-radius: 8px;
      background: #f9f9f9;
      padding: 1rem;
      margin-bottom: 1rem;
      box-shadow: 0 1px 2px rgba(0,0,0,0.05);
    }
    .article-card h3 {
      margin-top: 0;
      margin-bottom: 0.5rem;
      font-size: 1.1rem;
      font-weight: 700;
      color: #111 !important;
    }
    .article-card p { margin: 0.2rem 0; color: #333 !important; }
    .story-meta { color: #555 !important; font-size: 0.9rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ----------------------------- Header -----------------------------
st.title("Global Situational Awareness Dashboard")

# ----------------------------- Helpers -----------------------------
UK_TZ = pytz.timezone("Europe/London")

def pretty_dt_iso(iso: str) -> str:
    """ISO UTC -> 'HH:MM, Friday 13 September 2025' in UK local time (with DST)."""
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        dt_uk = dt.astimezone(UK_TZ)
        return dt_uk.strftime("%H:%M, %A %d %B %Y")
    except Exception:
        return iso

def load_data() -> Dict[str, Any]:
    try:
        with open("data.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"generated_at": "", "items": []}

def choose_text(it: Dict[str, Any], translate: bool, key: str) -> str:
    """Return translated or original field with sensible fallback."""
    if translate:
        if key == "title":
            return it.get("title_en") or it.get("title") or it.get("title_orig") or "(no title)"
        if key == "summary":
            return it.get("summary_en") or it.get("summary") or it.get("summary_orig") or ""
    else:
        if key == "title":
            return it.get("title") or it.get("title_orig") or it.get("title_en") or "(no title)"
        if key == "summary":
            return it.get("summary") or it.get("summary_orig") or it.get("summary_en") or ""
    return ""

def meta_line(it: Dict[str, Any]) -> str:
    src = it.get("source", "Unknown")
    when = pretty_dt_iso(it.get("published_at"))
    geo = it.get("geo") or {}
    loc_bits = [x for x in [geo.get("airport"), geo.get("city"), geo.get("country"), geo.get("iata")] if x]
    loc = " | ".join(loc_bits)
    parts = [src, when] + ([loc] if loc else [])
    return " | ".join(parts)

def render_card(it: Dict[str, Any], translate: bool):
    title = choose_text(it, translate, "title")
    summary = choose_text(it, translate, "summary")
    if not title and summary:
        title = (summary.split("\n")[0].split(".")[0] or "(no title)")
    title = title or "(no title)"
    url = it.get("url") or "#"
    meta = meta_line(it)

    st.markdown(
        f"""
        <div class="article-card">
          <h3>{title}</h3>
          <p class="story-meta"><em>{meta}</em></p>
          <p class="story-summary">{summary}</p>
          <p style="margin-top:.4rem;"><a href="{url}" target="_blank">Open source</a></p>
        </div>
        """,
        unsafe_allow_html=True,
    )

# ----------------------------- Data & Header Row -----------------------------
data = load_data()
last_gen = pretty_dt_iso(data.get("generated_at"))

hdr_left, hdr_right = st.columns([3, 1])
with hdr_left:
    st.markdown(
        f"""
        <div style="margin: 0.4rem 0 0.6rem 0;">
            <span style="font-size:1.05rem; font-weight:700;">Last update:</span>
            <span style="font-size:1.0rem;">{last_gen}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
with hdr_right:
    if st.button("Refresh", type="secondary", use_container_width=True):
        st.rerun()

# ----------------------------- Controls -----------------------------
translate = st.checkbox("Translate to English", value=True, help="Show translated titles and summaries when available.")
ctl1, ctl2 = st.columns([2, 1])
with ctl1:
    q = st.text_input("Search", "")
with ctl2:
    type_choices = ["major news", "local news", "social"]
    type_filter = st.multiselect("Type", type_choices, default=type_choices)

def keep_item(it: Dict[str, Any]) -> bool:
    if type_filter and it.get("type") not in type_filter:
        return False
    if q:
        blob = " ".join([
            choose_text(it, translate, "title"),
            choose_text(it, translate, "summary"),
            it.get("source", ""),
            " ".join(it.get("tags", [])),
            json.dumps(it.get("geo", {})),
        ]).lower()
        return q.lower() in blob
    return True

items: List[Dict[str, Any]] = [it for it in (data.get("items") or []) if keep_item(it)]
items.sort(key=lambda x: x.get("published_at", ""), reverse=True)

# ----------------------------- Layout -----------------------------
col_live, col_social = st.columns((2, 1))

with col_live:
    st.subheader("Live feed")
    for it in items:
        if it.get("type") in ("major news", "local news"):
            render_card(it, translate)

with col_social:
    st.subheader("Social media")
    for it in items:
        if it.get("type") == "social":
            render_card(it, translate)

