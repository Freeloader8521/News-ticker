import os
import json
from textwrap import shorten
from datetime import datetime
from typing import List, Dict

import pytz
import requests
import pandas as pd
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

# OpenAI (optional – for AI risk summary)
OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY", "")
DEFAULT_MODEL = st.secrets.get("OPENAI_MODEL", "gpt-4o-mini")

# ---------------- Utils ----------------
def pretty_dt(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        uk = dt.astimezone(pytz.timezone("Europe/London"))
        return uk.strftime("%H:%M, %A %d %B %Y")
    except Exception:
        return iso or ""

@st.cache_data(ttl=300)
def fetch_json(url: str) -> Dict:
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}

def clamp_txt(s: str, limit: int) -> str:
    return shorten(s or "", width=limit, placeholder="…")

def first_paragraph(s: str, max_chars: int = 500) -> str:
    if not s:
        return ""
    p = s.split("\n\n")[0].strip()
    if not p:
        p = s.split("\n")[0].strip()
    if len(p) > max_chars:
        p = p[:max_chars].rsplit(" ", 1)[0] + "…"
    return p

def pick_language_text(it: Dict, translate_on: bool) -> (str, str):
    if translate_on:
        return (
            it.get("title_en") or it.get("title") or it.get("title_orig") or "",
            it.get("summary_en") or it.get("summary") or it.get("summary_orig") or "",
        )
    else:
        return (
            it.get("title_orig") or it.get("title") or it.get("title_en") or "",
            it.get("summary_orig") or it.get("summary") or it.get("summary_en") or "",
        )

def extract_lat_lon(geo: Dict):
    if not geo:
        return None, None
    lat = geo.get("lat") or geo.get("l


