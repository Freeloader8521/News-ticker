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
        "severe weather, evacuations, protests with security impact). "
        "Be concise and specific. Group by theme. Use bullet points. "
        "Each bullet: [Severity: low|moderate|high] + short title + one-line detail with where/when. "
        "Do NOT invent facts; if uncertain, mark Severity: low."
    )
    user_msg = "Recent items:\n" + "\n".join(lines)

    try:
        from openai import OpenAI

        client = OpenAI(api_key=OPENAI_API_KEY)
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.2,
            max_tokens=800,
        )
        return resp.choices[0].message.content.strip()
    except Exception as ex:
        return f"⚠️ OpenAI error: {ex}"


# ---------------- Layout / Styling ----------------
st.set_page_config(
    page_title="Global Situational Awareness Dashboard",
    layout="wide",
)

st.markdown(
    """
    <style>
    html, body, [class*="st-"] { color: #111 !important; background: #fff !important; }
    .block-container { padding-top: 1rem; padding-bottom: 1rem; }
    .stButton button, .stDownloadButton button {
        border: 1px solid #444 !important; padding: 0.4rem 1rem; border-radius: 4px;
    }
    h2, h3 {
        margin-top: 0.8rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------- Data fetch ----------------
data = fetch_json(DATA_JSON_URL)
items = data.get("items", []) or []
generated_at = data.get("generated_at")
last_update = pretty_dt(generated_at) if generated_at else "n/a"

# ---------------- Header ----------------
st.title("Global Situational Awareness Dashboard")

headA, headB = st.columns([6, 1])
with headA:
    st.markdown(f"**Last update:** {last_update}")
with headB:
    if st.button("Refresh", use_container_width=True):
        with st.spinner("Refreshing feeds…"):
            st.cache_data.clear()
            st.rerun()

# Translate toggle
pill_col1, pill_col2 = st.columns([1, 5])
with pill_col1:
    translate = st.toggle(
        "Translate",
        value=True,
        help="Switch between original language and English where available.",
    )
with pill_col2:
    st.write("")

# Status / progress
status = fetch_json(STATUS_JSON_URL)
if status:
    cur = status.get("current", "")
    done = int(status.get("done", 0))
    tot = max(1, int(status.get("total", 0)) or 1)
    finished = status.get("finished_at")
    state_line = f"Processed {done}/{tot}"
    if not finished and cur:
        state_line += f" · fetching: **{cur}**"
    progA, progB = st.columns([0.7, 0.3])
    with progA:
        st.progress(min(1.0, done / float(tot)))
    with progB:
        st.caption(state_line)

# ---------------- Risk summary (AI) ----------------
with st.container(border=True):
    topL, topR = st.columns([0.7, 0.3])
    with topL:
        st.subheader("Risk summary (AI)")
        st.caption("Auto-extracted physical safety and operations risks from the latest items.")
    with topR:
        model = st.selectbox("Model", [DEFAULT_MODEL, "gpt-4o", "gpt-4.1-mini"], index=0)
        gen_now = st.button("Generate summary")
    memo_key = f"{generated_at}|{model}|{int(bool(translate))}"
    if gen_now:
        with st.spinner("Analysing items with OpenAI…"):
            st.session_state["ai_summary"] = ai_risk_summary(
                memo_key, items, model, translate
            )
    if "ai_summary" in st.session_state:
        st.markdown(st.session_state["ai_summary"])
    else:
        st.info("Click **Generate summary** to create an AI overview of key risks.")

# ---------------- Filters ----------------
colSearch, colType = st.columns([3, 2])
with colSearch:
    search = st.text_input("Search", "")
with colType:
    type_choices = ["major news", "local news", "social"]
    type_filter = st.multiselect("Type", type_choices, default=type_choices)


def filter_items(items_in: List[Dict]) -> List[Dict]:
    out = items_in
    if search:
        s = search.lower()
        out = [
            it
            for it in out
            if s
            in (
                it.get("title", "")
                + it.get("summary", "")
                + it.get("title_en", "")
                + it.get("summary_en", "")
            ).lower()
        ]
    if type_filter:
        out = [it for it in out if it.get("type") in type_filter]
    return out


items = filter_items(items)

# ---------------- Map of incidents ----------------
st.subheader("Map of incidents")

map_points = []
for it in items:
    geo = it.get("geo") or {}
    lat, lon = extract_lat_lon(geo)
    if lat is None or lon is None:
        continue

    title, summary = pick_language_text(it, translate)
    city = geo.get("city") or ""
    country = geo.get("country") or ""
    iata = geo.get("iata") or ""

    map_points.append(
        {
            "lat": lat,
            "lon": lon,
            "title": clamp_txt(title, 120),
            "summary": clamp_txt(first_paragraph(summary, 260), 260),
            "source": it.get("source") or "",
            "published": pretty_dt(it.get("published_at") or ""),
            "type": it.get("type") or "",
            "location": " / ".join(x for x in [city, country, iata] if x),
        }
    )

if map_points:
    df_map = pd.DataFrame(map_points)

    if MAPBOX_API_KEY:
        # Dark, high-contrast style using Mapbox
        view_state = pdk.ViewState(
            latitude=float(df_map["lat"].median()),
            longitude=float(df_map["lon"].median()),
            zoom=2,
            min_zoom=1,
            max_zoom=15,
            pitch=0,
        )

        layer = pdk.Layer(
            "ScatterplotLayer",
            data=df_map,
            get_position="[lon, lat]",
            get_radius=70000,
            pickable=True,
            get_fill_color=[255, 85, 0, 220],  # bright orange/red against dark map
            get_line_color=[255, 255, 255, 200],
            line_width_min_pixels=1,
        )

        tooltip = {
            "html": (
                "<b>{title}</b><br/>"
                "{published}<br/>"
                "{source}<br/>"
                "{location}<br/><br/>"
                "{summary}"
            ),
            "style": {"backgroundColor": "black", "color": "white"},
        }

        deck = pdk.Deck(
            layers=[layer],
            initial_view_state=view_state,
            map_style="mapbox://styles/mapbox/dark-v11",
            tooltip=tooltip,
        )

        st.pydeck_chart(deck)
    else:
        # Fallback: Streamlit's built-in map (light tiles, but no token needed)
        st.map(df_map, latitude="lat", longitude="lon", zoom=2)
else:
    st.info("No items with usable event coordinates to plot on the map.")

# ---------------- Feeds ----------------
colFeed, colSocial = st.columns([2, 1])

# Live feed (news)
with colFeed:
    st.subheader("Live feed")
    for it in items:
        if it.get("type") == "social":
            continue
        title, summary = pick_language_text(it, translate)
        st.markdown(f"### {title}")
        meta = f"{it.get('source') or ''} | {pretty_dt(it.get('published_at') or '')}"
        st.caption(meta)
        fp = first_paragraph(summary, max_chars=600)
        if fp:
            st.markdown(fp)
        if it.get("url"):
            st.markdown(f"[Read more →]({it['url']})")
        st.markdown("---")

# Social media
with colSocial:
    st.subheader("Social media")
    for it in items:
        if it.get("type") != "social":
            continue
        title, summary = pick_language_text(it, translate)
        st.markdown(f"### {title}")
        meta = f"{it.get('source') or ''} | {pretty_dt(it.get('published_at') or '')}"
        st.caption(meta)
        fp = first_paragraph(summary, max_chars=400)
        if fp:
            st.markdown(fp)
        if it.get("url"):
            st.markdown(f"[Open source]({it['url']})")
        st.markdown("---")





