# streamlit_app.py

import json
from datetime import datetime
from typing import Dict, Any, List

import requests
import streamlit as st
import pytz
import pandas as pd
import pydeck as pdk

# --------------------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------------------

APP_TITLE = "Global Situational Awareness Dashboard"

# If you use Streamlit Secrets, set DATA_JSON_URL in your app’s Secrets.
# Otherwise the app will try to read ./data.json from the repo.
DATA_JSON_URL = st.secrets.get("DATA_JSON_URL", "").strip()

# Country → flag emoji (only used when geo.country is present from an airport match)
COUNTRY_FLAGS = {
    "United Kingdom": "🇬🇧",
    "United States": "🇺🇸",
    "Canada": "🇨🇦",
    "Ireland": "🇮🇪",
    "France": "🇫🇷",
    "Germany": "🇩🇪",
    "Netherlands": "🇳🇱",
    "Spain": "🇪🇸",
    "Portugal": "🇵🇹",
    "Italy": "🇮🇹",
    "Switzerland": "🇨🇭",
    "Austria": "🇦🇹",
    "Belgium": "🇧🇪",
    "Poland": "🇵🇱",
    "Greece": "🇬🇷",
    "Türkiye": "🇹🇷",
    "United Arab Emirates": "🇦🇪",
    "Qatar": "🇶🇦",
    "Saudi Arabia": "🇸🇦",
    "Israel": "🇮🇱",
    "India": "🇮🇳",
    "Thailand": "🇹🇭",
    "Malaysia": "🇲🇾",
    "Singapore": "🇸🇬",
    "Philippines": "🇵🇭",
    "Indonesia": "🇮🇩",
    "Japan": "🇯🇵",
    "South Korea": "🇰🇷",
    "China": "🇨🇳",
    "Australia": "🇦🇺",
    "New Zealand": "🇳🇿",
    "Mexico": "🇲🇽",
    "Brazil": "🇧🇷",
    "Argentina": "🇦🇷",
    "Chile": "🇨🇱",
    "South Africa": "🇿🇦",
    "Kenya": "🇰🇪",
    "Egypt": "🇪🇬",
    "Nigeria": "🇳🇬",
    "Ghana": "🇬🇭",
}

# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------

def pretty_dt_uk(iso: str) -> str:
    """Return 'HH:MM, Weekday DD Month YYYY' in Europe/London (BST/GMT)."""
    try:
        dt_utc = datetime.fromisoformat((iso or "").replace("Z", "+00:00"))
        uk = pytz.timezone("Europe/London")
        dt_local = dt_utc.astimezone(uk)
        return dt_local.strftime("%H:%M, %A %d %B %Y")
    except Exception:
        return iso or ""

@st.cache_data(ttl=60)
def fetch_json(url: str) -> Dict[str, Any]:
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return r.json()

@st.cache_data(ttl=60)
def load_local_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def load_data() -> Dict[str, Any]:
    try:
        if DATA_JSON_URL:
            return fetch_json(DATA_JSON_URL)
        return load_local_json("data.json")
    except Exception as e:
        st.warning(f"Could not load data.json ({e}).")
        return {"generated_at": "", "items": [], "trends": {}}

def is_relevant(it: Dict[str, Any]) -> bool:
    """Items should already be filtered by the collector; keep a belt-and-braces check."""
    tags = it.get("tags", [])
    return ("airport/security" in tags) or ("diplomatic" in tags)

def flag_for_country(name: str) -> str:
    return COUNTRY_FLAGS.get(name or "", "")

def live_caption(it: Dict[str, Any]) -> str:
    """Build the small grey line under each headline with time | geo | tags."""
    parts: List[str] = []
    src = it.get("source")
    if src:
        parts.append(src)

    # time
    try:
        parts.append(pretty_dt_uk(it.get("published_at", "")))
    except Exception:
        pass

    # geo from airport match only (no inferred country)
    geo = it.get("geo", {}) or {}
    geo_bits: List[str] = []
    if geo.get("airport"):
        geo_bits.append(geo["airport"])
    if geo.get("city"):
        geo_bits.append(geo["city"])
    if geo.get("country"):
        f = flag_for_country(geo["country"])
        geo_bits.append(f if f else geo["country"])
    if geo.get("iata"):
        geo_bits.append(geo["iata"])
    if geo_bits:
        parts.append(" | ".join(geo_bits))

    # tags (short)
    tags = [t for t in it.get("tags", []) if t not in ("airport/security", "diplomatic")]
    if tags:
        parts.append(", ".join(tags))

    return " | ".join(parts)

# A tiny beep (short WAV) – base64
_BEEP_WAV = (
    "UklGRoQAAABXQVZFZm10IBAAAAABAAEAESsAACJWAAACABAAZGF0YYQAAAABAQEB"
    "AQEBAQEBAQEBAQEBAP///wD///8A////AP///wD///8A////AP///wD///8A////"
)

def play_beep():
    audio_tag = f"""
    <audio autoplay="true">
      <source src="data:audio/wav;base64,{_BEEP_WAV}">
    </audio>
    """
    st.markdown(audio_tag, unsafe_allow_html=True)

# ---- Airports index for lat/lon (optional fallback) ----
def load_airports_index():
    """No cache: always read the latest airports.json."""
    try:
        with open("airports.json", "r", encoding="utf-8") as f:
            airports = json.load(f)
    except Exception:
        return {}, {}

    iata_to_ll, alias_to_iata = {}, {}
    for a in airports:
        iata = (a.get("iata") or "").upper()
        lat = a.get("lat", a.get("latitude"))
        lon = a.get("lon", a.get("longitude"))
        if iata and isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            iata_to_ll[iata] = (lat, lon)
        for alias in (a.get("aliases") or []):
            if iata and alias:
                alias_to_iata[alias.lower()] = iata
        if iata:
            alias_to_iata[iata.lower()] = iata
    return iata_to_ll, alias_to_iata

iata_to_ll, alias_to_iata = load_airports_index()

def item_latlon(it: Dict[str, Any]) -> tuple | None:
    """Use collector-provided geo.lat/lon first; otherwise try IATA->airports.json."""
    geo = it.get("geo", {}) or {}
    lat = geo.get("lat") or geo.get("latitude")
    lon = geo.get("lon") or geo.get("longitude")
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        return (lat, lon)
    iata = (geo.get("iata") or "").upper()
    if iata and iata in iata_to_ll:
        return iata_to_ll[iata]
    return None

# Refresh button (use st.rerun)
if st.button("Refresh"):
    st.rerun()

# --- Map (latest 15 items, airport coordinates only) ---
st.subheader("Map (latest 15 items)")
items_sorted = sorted(items, key=lambda x: x.get("published_at", ""), reverse=True)[:15]

coords = []
for it in items_sorted:
    ll = item_latlon(it)
    if not ll:
        continue
    lat, lon = ll
    title = it.get("title", "") or "(no title)"
    info = f"{it.get('source','')} — {pretty_dt_uk(it.get('published_at',''))}"
    coords.append({"lat": lat, "lon": lon, "title": title, "info": info})

if coords:
    df = pd.DataFrame(coords)
    layer = pdk.Layer(
        "ScatterplotLayer",
        df,
        get_position=["lon", "lat"],
        get_radius=60000,
        get_fill_color=[255, 100, 0, 200],  # visible on dark/light maps
        pickable=True,
    )
    view = pdk.ViewState(latitude=20, longitude=0, zoom=1.5)
    st.pydeck_chart(pdk.Deck(layers=[layer], initial_view_state=view, tooltip={"text": "{title}\n{info}"}))
else:
    st.caption("No airport coordinates available yet.")

# --------------------------------------------------------------------------------------
# Controls
# --------------------------------------------------------------------------------------
search = st.text_input("Search", "")
type_choices = ["major news", "local news", "social"]
type_filter = st.multiselect("Type", type_choices, default=type_choices)

def passes_filters(it: Dict[str, Any]) -> bool:
    if it.get("type") not in type_filter:
        return False
    if search:
        q = search.lower()
        blob = " ".join([
            it.get("title", ""), it.get("summary", ""),
            it.get("source", ""), json.dumps(it.get("geo", {})),
            " ".join(it.get("tags", []))
        ]).lower()
        if q not in blob:
            return False
    return True

items = [it for it in items if passes_filters(it)]

# --------------------------------------------------------------------------------------
# Columns: Live feed / Social media
# --------------------------------------------------------------------------------------
col_live, col_social = st.columns((2, 1))

def live_caption(it: Dict[str, Any]) -> str:
    parts: List[str] = []
    src = it.get("source")
    if src:
        parts.append(src)
    try:
        parts.append(pretty_dt_uk(it.get("published_at", "")))
    except Exception:
        pass
    geo = it.get("geo", {}) or {}
    geo_bits: List[str] = []
    if geo.get("airport"):
        geo_bits.append(geo["airport"])
    if geo.get("city"):
        geo_bits.append(geo["city"])
    if geo.get("country"):
        f = COUNTRY_FLAGS.get(geo["country"], "")
        geo_bits.append(f if f else geo["country"])
    if geo.get("iata"):
        geo_bits.append(geo["iata"])
    if geo_bits:
        parts.append(" | ".join(geo_bits))
    tags = [t for t in it.get("tags", []) if t not in ("airport/security", "diplomatic")]
    if tags:
        parts.append(", ".join(tags))
    return " | ".join(parts)

with col_live:
    st.subheader("Live feed")
    live_items = [it for it in items if it.get("type") in ("major news", "local news")]
    for it in live_items:
        with st.container(border=True):
            st.markdown(f"**{it.get('title','(no title)')}**")
            st.caption(live_caption(it))
            summary = (it.get("summary") or "").strip()
            if summary:
                st.write(summary)
            url = it.get("url", "")
            if url:
                st.write(f"[Open source]({url})")

with col_social:
    st.subheader("Social media")
    soc_items = [it for it in items if it.get("type") == "social"]
    for it in soc_items:
        with st.container(border=True):
            st.markdown(f"**{it.get('title','(no title)')}**")
            st.caption(live_caption(it))
            summary = (it.get("summary") or "").strip()
            if summary:
                st.write(summary)
            url = it.get("url", "")
            if url:
                st.write(f"[Open source]({url})")
