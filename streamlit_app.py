import os
from textwrap import shorten
from datetime import datetime
from typing import List, Dict

import pytz
import requests
import pandas as pd
import pydeck as pdk
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

# Optional: OpenAI for AI risk summary
OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY", "")
DEFAULT_MODEL = st.secrets.get("OPENAI_MODEL", "gpt-4o-mini")

# Optional: Mapbox for dark map background
MAPBOX_API_KEY = st.secrets.get("MAPBOX_API_KEY", "")
if MAPBOX_API_KEY:
    pdk.settings.mapbox_api_key = MAPBOX_API_KEY

# ---------------- Utils ----------------
def pretty_dt(iso: str) -> str:
    """Format ISO timestamp into UK local time string."""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        uk = dt.astimezone(pytz.timezone("Europe/London"))
        return uk.strftime("%H:%M, %A %d %B %Y")
    except Exception:
        return iso or ""


@st.cache_data(ttl=300)
def fetch_json(url: str) -> Dict:
    """Fetch JSON with simple caching."""
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}


def clamp_txt(s: str, limit: int) -> str:
    return shorten(s or "", width=limit, placeholder="…")


def first_paragraph(s: str, max_chars: int = 500) -> str:
    """Return the first paragraph or line, trimmed."""
    if not s:
        return ""
    p = s.split("\n\n")[0].strip()
    if not p:
        p = s.split("\n")[0].strip()
    if len(p) > max_chars:
        p = p[:max_chars].rsplit(" ", 1)[0] + "…"
    return p


def pick_language_text(it: Dict, translate_on: bool) -> (str, str):
    """Pick title/summary based on translation toggle."""
    if translate_on:
        title = it.get("title_en") or it.get("title") or it.get("title_orig") or ""
        summary = it.get("summary_en") or it.get("summary") or it.get("summary_orig") or ""
    else:
        title = it.get("title_orig") or it.get("title") or it.get("title_en") or ""
        summary = it.get("summary_orig") or it.get("summary") or it.get("summary_en") or ""
    return title, summary


def extract_lat_lon(geo: Dict):
    """
    Extract latitude and longitude from the event geo field.

    Tries a few common key names so we always use event location,
    not publisher location.
    """
    if not geo:
        return None, None

    lat = (
        geo.get("lat")
        or geo.get("latitude")
        or geo.get("lat_deg")
    )
    lon = (
        geo.get("lon")
        or geo.get("lng")
        or geo.get("longitude")
        or geo.get("lon_deg")
    )

    try:
        if lat is not None and lon is not None:
            return float(lat), float(lon)
    except Exception:
        return None, None

    return None, None


# ---------------- OpenAI: risk summary (optional) ----------------
@st.cache_data(ttl=300, show_spinner=False)
def ai_risk_summary(cache_key: str, items: List[Dict], model: str, translate_on: bool) -> str:
    """Generate a short risk summary from recent items."""
    if not OPENAI_API_KEY:
        return "Set OPENAI_API_KEY in your Streamlit secrets to enable the AI summary."

    def is_risk(it: Dict) -> bool:
        tags = it.get("tags", [])
        return ("airport/security" in tags) or ("diplomatic" in tags)

    risk_items = [it for it in items if is_risk(it)]
    if not risk_items:
        risk_items = items[:60]
    else:
        risk_items = risk_items[:80]

    lines = []
    for it in risk_items:
        title, summary = pick_language_text(it, translate_on)
        src = it.get("source") or ""
        when = pretty_dt(it.get("published_at") or "")
        typ = it.get("type") or ""
        geo = it.get("geo") or {}
        loc = " / ".join(
            x for x in [geo.get("city"), geo.get("country"), geo.get("iata")] if x
        )
        line = f"- {clamp_txt(title, 160)} | {typ} | {src} | {when}"
        if loc:
            line += f" | {loc}"
        fp = first_paragraph(summary, max_chars=280)
        if fp:
            line += f"\n  {fp}"
        lines.append(line)

    system_msg = (
        "You are an analyst for an aviation/physical security dashboard. "
        "Given the recent items, extract concrete, near-term risks to PHYSICAL well-being "
        "and operations (airports/transport, airspace closures, strikes creating safety gaps, "
        "severe weather, evacuations, protests with security impac




