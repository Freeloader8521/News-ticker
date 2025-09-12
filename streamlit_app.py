import json
from typing import Any, Dict, List, Tuple

import pandas as pd
import pydeck as pdk
import streamlit as st
from datetime import datetime
import pytz

# --------- Title ---------
st.set_page_config(page_title="Global Situational Awareness Dashboard", layout="wide")
st.title("Global Situational Awareness Dashboard")

# --------- Helpers ---------
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

# Always read latest airports.json (no cache)
def load_airports_index() -> Tuple[Dict[str, Tuple[float,float]], Dict[str,str]]:
    try:
        airports = load_json("airports.json")
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

def item_latlon(it: Dict[str, Any], iata_to_ll: Dict[str, Tuple[float,float]]):
    geo = it.get("geo", {}) or {}
    lat = geo.get("lat") or geo.get("latitude")
    lon = geo.get("lon") or geo.get("longitude")
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        return (lat, lon)
    iata = (geo.get("iata") or "").upper()
    if iata and iata in iata_to_ll:
        return iata_to_ll[iata]
    return None

def safe_date(it: Dict[str, Any]) -> str:
    return it.get("published_at") or ""

# --------- Load data ---------
data = load_json("data.json")
generated = data.get("generated_at")
items: List[Dict[str, Any]] = data.get("items", [])

# Header: last update + refresh
st.markdown(
    f"""
    <div style="margin: 0.5rem 0 0.75rem 0;">
        <span style="font-size:1.2rem; font-weight:600;">Last update:</span>
        <span style="font-size:1.1rem;">{pretty_dt_uk(generated)}</span>
    </div>
    """,
    unsafe_allow_html=True,
)
if st.button("Refresh"):
    st.rerun()

# Controls
colA, colB = st.columns([2, 1])
with colA:
    q = st.text_input("Search", "")
with colB:
    type_choices = ["major news", "local news", "social"]
    type_filter = st.multiselect("Type", type_choices, default=type_choices)

# Translation toggle (uses pre-translated fields from the collector)
translate_toggle = st.checkbox("Translate to English", value=True, help="Show English translations when available")

# Filter helpers
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

# --------- Map (latest 15 items with airport coords) ---------
st.subheader("Map (latest 15 items)")
iata_to_ll, alias_to_iata = load_airports_index()
latest15 = sorted(filtered, key=safe_date, reverse=True)[:15]

coords = []
for it in latest15:
    ll = item_latlon(it, iata_to_ll)
    if not ll:
        continue
    lat, lon = ll
    title = (it.get("title_en") if translate_toggle else it.get("title_orig")) or it.get("title") or "(no title)"
    info = f"{it.get('source','')} — {pretty_dt_uk(it.get('published_at',''))}"
    coords.append({"lat": lat, "lon": lon, "title": title, "info": info})

if coords:
    df = pd.DataFrame(coords)
    layer = pdk.Layer(
        "ScatterplotLayer",
        df,
        get_position=["lon", "lat"],
        get_radius=60000,
        get_fill_color=[255, 100, 0, 200],  # visible on dark maps
        pickable=True,
    )
    view = pdk.ViewState(latitude=20, longitude=0, zoom=1.5)
    st.pydeck_chart(pdk.Deck(layers=[layer], initial_view_state=view, tooltip={"text": "{title}\n{info}"}))
else:
    st.caption("No airport coordinates available to plot yet.")

# --------- Layout: Live feed & Social ---------
col1, col2 = st.columns(2)

def show_card(col, title: str, arr: List[Dict[str, Any]]):
    col.subheader(title)
    for it in arr[:120]:
        # choose translated vs original
        title_txt = (it.get("title_en") if translate_toggle else it.get("title_orig")) or it.get("title") or "(no title)"
        summary_txt = (it.get("summary_en") if translate_toggle else it.get("summary_orig")) or it.get("summary","")
        # fallback: if still no title, use first line of summary
        if (not title_txt) and summary_txt:
            title_txt = summary_txt.split(".")[0] or "(no title)"

        with col.expander(title_txt):
            geo = it.get("geo", {}) or {}
            loc_bits = [geo.get("airport"), geo.get("city"), geo.get("country")]
            loc = " | ".join([x for x in loc_bits if x])
            tags = ", ".join(it.get("tags", []))
            col.caption(
                f"{it.get('source','')} | {pretty_dt_uk(it.get('published_at',''))}"
                + (f" | {loc}" if loc else "")
                + (f" | {tags}" if tags else "")
            )
            if summary_txt:
                col.write(summary_txt)
            if it.get("url"):
                col.write(f"[Open source]({it['url']})")

with col1:
    live = [it for it in filtered if it.get("type") in ("major news","local news")]
    show_card(col1, "Live feed", live)

with col2:
    social = [it for it in filtered if it.get("type") == "social"]
    show_card(col2, "Social media", social)
