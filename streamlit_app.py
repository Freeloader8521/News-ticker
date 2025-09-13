import json
from typing import Any, Dict, List, Tuple
from datetime import datetime

import streamlit as st
import pytz

# ────────────────────────── Page config / theme ──────────────────────────
st.set_page_config(page_title="Global Situational Awareness Dashboard", layout="wide")

# Force white background and tidy spacing
st.markdown(
    """
st.markdown(
    """
    <style>
      /* Force light theme colours */
      html, body, [class*="st-"] {
        color: #111 !important;
        background: #ffffff !important;
      }

      /* Container spacing */
      .block-container { padding-top: 1.5rem; padding-bottom: 2rem; }

      /* Links */
      a, a:visited { color: #0b5ed7 !important; text-decoration: none; }
      a:hover { text-decoration: underline; }

      /* Headings */
      h1, h2, h3, h4, h5, h6 { color: #111 !important; }

      /* Markdown text inside Streamlit containers */
      div[data-testid="stMarkdownContainer"] p,
      div[data-testid="stMarkdownContainer"] span,
      div[data-testid="stMarkdownContainer"] li {
        color: #111 !important;
      }

      /* Inputs */
      input, textarea, .stTextInput input {
        color: #111 !important;
        background: #fff !important;
      }

      /* Cards */
      .story-card { padding: 0.85rem 1rem; border: 1px solid #E6E6E6; border-radius: 10px; margin-bottom: 0.8rem; background: #fff; }
      .story-title { font-size: 1.05rem; font-weight: 700; margin: 0 0 0.35rem 0; color: #111 !important; }
      .story-meta { color: #555 !important; font-size: 0.9rem; margin-bottom: 0.35rem; }
      .story-summary { font-size: 0.98rem; line-height: 1.35rem; color: #111 !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Global Situational Awareness Dashboard")

# ────────────────────────── Helpers ──────────────────────────
UK = pytz.timezone("Europe/London")

def pretty_dt_uk(iso: str) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        dt_uk = dt.astimezone(UK)
        return dt_uk.strftime("%H:%M, %A %d %B %Y")
    except Exception:
        return iso

def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def safe_date(it: Dict[str, Any]) -> str:
    return it.get("published_at") or ""

def caption_line(it: Dict[str, Any]) -> str:
    src = it.get("source", "")
    ts = pretty_dt_uk(it.get("published_at", ""))
    geo = it.get("geo", {}) or {}
    loc_bits = [geo.get("airport"), geo.get("city"), geo.get("country"), geo.get("iata")]
    loc = " | ".join([x for x in loc_bits if x])
    tags = ", ".join([t for t in it.get("tags", []) if t not in ("airport/security", "diplomatic")])
    parts = [s for s in (src, ts, loc if loc else None, tags if tags else None) if s]
    return " | ".join(parts)

# ────────────────────────── Load data ──────────────────────────
data = load_json("data.json")
generated = data.get("generated_at")
items: List[Dict[str, Any]] = data.get("items", [])

# Header: last update + refresh + translate toggle
hdr_left, hdr_right = st.columns([3, 1])
with hdr_left:
    st.markdown(
        f"""
        <div style="margin: 0.4rem 0 0.75rem 0;">
            <span style="font-size:1.15rem; font-weight:700;">Last update:</span>
            <span style="font-size:1.05rem;">{pretty_dt_uk(generated)}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
with hdr_right:
    if st.button("Refresh", use_container_width=True):
        st.rerun()

translate_toggle = st.checkbox("Translate to English", value=True, help="Show English translations when available")

# Controls
ctl1, ctl2 = st.columns([2, 1])
with ctl1:
    q = st.text_input("Search", "")
with ctl2:
    type_choices = ["major news", "local news", "social"]
    type_filter = st.multiselect("Type", type_choices, default=type_choices)

def passes_filters(it: Dict[str, Any]) -> bool:
    if type_filter and it.get("type") not in type_filter:
        return False
    if q:
        hay = " ".join([
            it.get("title_en") or it.get("title_orig") or it.get("title",""),
            it.get("summary_en") or it.get("summary_orig",""),
            " ".join(it.get("tags", [])),
            it.get("source","")
        ]).lower()
        return q.lower() in hay
    return True

filtered = [it for it in items if passes_filters(it)]
filtered = sorted(filtered, key=safe_date, reverse=True)

# ────────────────────────── Layout: Live feed & Social ──────────────────────────
col_live, col_social = st.columns((2, 1))

def render_column(col, header: str, arr: List[Dict[str, Any]]):
    col.subheader(header)
    for it in arr:
        # choose translated vs original
        title_txt = (it.get("title_en") if translate_toggle else it.get("title_orig")) or it.get("title") or ""
        summary_txt = (it.get("summary_en") if translate_toggle else it.get("summary_orig")) or it.get("summary","")
        # fallback: if still no title, use first line of summary
        if not title_txt and summary_txt:
            title_txt = summary_txt.split(".")[0].split("\n")[0] or "(no title)"
        if not title_txt:
            title_txt = "(no title)"

        meta = caption_line(it)
        url = it.get("url")

        with col.container():
            st.markdown('<div class="story-card">', unsafe_allow_html=True)
            # Title (always visible and clickable if URL exists)
            if url:
                st.markdown(f'<div class="story-title"><a href="{url}" target="_blank">{title_txt}</a></div>', unsafe_allow_html=True)
            else:
                st.markdown(f'<div class="story-title">{title_txt}</div>', unsafe_allow_html=True)
            # Meta line
            if meta:
                st.markdown(f'<div class="story-meta">{meta}</div>', unsafe_allow_html=True)
            # Summary
            if summary_txt:
                st.markdown(f'<div class="story-summary">{summary_txt}</div>', unsafe_allow_html=True)
            # Link (secondary)
            if url:
                st.markdown(f'[Open source]({url})')
            st.markdown('</div>', unsafe_allow_html=True)

with col_live:
    live_items = [it for it in filtered if it.get("type") in ("major news", "local news")]
    render_column(st, "Live feed", live_items)

with col_social:
    social_items = [it for it in filtered if it.get("type") == "social"]
    render_column(st, "Social media", social_items)
