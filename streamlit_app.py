import os
from textwrap import shorten
from datetime import datetime, timezone
from typing import List, Dict, Tuple, Optional

import pytz
import requests
import pandas as pd
import pydeck as pdk
import streamlit as st
import streamlit.components.v1 as components

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

# Optional: Discord for breaking news banner
DISCORD_BOT_TOKEN = st.secrets.get("DISCORD_BOT_TOKEN", "")
DISCORD_CHANNEL_ID = st.secrets.get("DISCORD_CHANNEL_ID", "")


# ---------------- Utils ----------------
def pretty_dt(iso: str) -> str:
    """Format ISO timestamp into UK local time string."""
    if not iso:
        return ""
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


def pick_language_text(it: Dict, translate_on: bool) -> Tuple[str, str]:
    """Pick title/summary based on translation toggle."""
    if translate_on:
        title = it.get("title_en") or it.get("title") or it.get("title_orig") or ""
        summary = it.get("summary_en") or it.get("summary") or it.get("summary_orig") or ""
    else:
        title = it.get("title_orig") or it.get("title") or it.get("title_en") or ""
        summary = it.get("summary_orig") or it.get("summary") or it.get("summary_en") or ""
    return title, summary


def extract_lat_lon(geo: Optional[Dict]) -> Tuple[Optional[float], Optional[float]]:
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


# ---------------- Discord: breaking news ----------------
@st.cache_data(ttl=30)
def fetch_discord_breaking() -> Dict:
    """
    Fetch the latest message from a specific Discord channel.

    Requires:
      - DISCORD_BOT_TOKEN in st.secrets
      - DISCORD_CHANNEL_ID in st.secrets

    Returns a dict with keys:
      id, content, author, created_at (ISO), created_at_pretty

    If not configured or on error, returns {}.
    """
    if not DISCORD_BOT_TOKEN or not DISCORD_CHANNEL_ID:
        return {}

    url = f"https://discord.com/api/v10/channels/{DISCORD_CHANNEL_ID}/messages"
    headers = {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
        "User-Agent": "situational-awareness-dashboard/1.0",
    }
    params = {"limit": 1}

    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        if not data:
            return {}
        msg = data[0]
        content = msg.get("content", "").strip()
        author = msg.get("author", {}).get("username", "Unknown")
        ts = msg.get("timestamp", "")
        msg_id = msg.get("id", "")
        return {
            "id": msg_id,
            "content": content,
            "author": author,
            "created_at": ts,
            "created_at_pretty": pretty_dt(ts),
        }
    except Exception:
        return {}


def is_breaking_active(breaking: Dict, max_age_hours: float = 3.0) -> bool:
    """
    Decide whether a breaking message should be treated as active:
    - It must exist
    - It must be newer than max_age_hours
    """
    if not breaking:
        return False
    ts = breaking.get("created_at")
    if not ts:
        return False
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)
        now_utc = datetime.now(timezone.utc)
        age_hours = (now_utc - dt).total_seconds() / 3600.0
        return age_hours <= max_age_hours
    except Exception:
        return False


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

    lines: List[str] = []
    for it in risk_items:
        title, summary = pick_language_text(it, translate_on)
        src = it.get("source") or ""
        when = pretty_dt(it.get("published_at") or "")
        typ = it.get("type") or ""
        geo = it.get("geo") or {}
        loc_bits = [geo.get("city"), geo.get("country"), geo.get("iata")]
        loc = " / ".join(x for x in loc_bits if x)
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
    html, body, [class*="st-"] { color: #f5f5f5 !important; background: #050711 !important; }
    .block-container { padding-top: 0.5rem; padding-bottom: 1rem; }
    .stButton button, .stDownloadButton button {
        border: 1px solid #f97316 !important;
        padding: 0.5rem 1.4rem;
        border-radius: 999px;
        background: #111827 !important;
        color: #f9fafb !important;
        font-weight: 600;
    }
    h1, h2, h3, h4 {
        color: #f9fafb !important;
    }
    /* Style A: full-width red breaking bar */
    .breaking-banner {
        background: #b91c1c;
        color: #f9fafb;
        padding: 0.65rem 0.9rem;
        border-radius: 6px;
        font-weight: 600;
        display: flex;
        align-items: center;
        gap: 0.9rem;
        margin-bottom: 0.9rem;
        border: 1px solid #fecaca;
        box-shadow: 0 10px 24px rgba(0,0,0,0.6);
    }
    .breaking-label-pill {
        background: #7f1d1d;
        padding: 0.2rem 0.7rem;
        border-radius: 999px;
        font-size: 0.8rem;
        text-transform: uppercase;
        letter-spacing: 0.12em;
        display: flex;
        align-items: center;
        gap: 0.4rem;
    }
    .breaking-main-text {
        font-size: 1rem;
    }
    .breaking-main-text strong {
        font-weight: 700;
    }
    .breaking-meta {
        font-size: 0.75rem;
        opacity: 0.9;
        margin-top: 0.1rem;
    }
    /* Central modal-style alert */
    .breaking-alert {
        margin: 1.0rem auto;
        max-width: 620px;
        background: #020617;
        border-radius: 14px;
        padding: 1.2rem 1.4rem;
        border: 1px solid #f97316;
        box-shadow: 0 18px 40px rgba(0,0,0,0.85);
    }
    .breaking-alert-title {
        font-size: 1.0rem;
        text-transform: uppercase;
        letter-spacing: 0.14em;
        color: #fed7aa;
        margin-bottom: 0.5rem;
    }
    .breaking-alert-text {
        font-size: 0.95rem;
        margin-bottom: 0.5rem;
    }
    .breaking-alert-meta {
        font-size: 0.8rem;
        color: #9ca3af;
        margin-bottom: 0.7rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def play_double_ping():
    """
    Use the Web Audio API to play a double ping (no external audio file).
    Plays once per rerun when called.
    """
    js = """
    <script>
    (function() {
        try {
            const AudioContext = window.AudioContext || window.webkitAudioContext;
            if (!AudioContext) return;
            const ctx = new AudioContext();
            function beep(freq, startOffset) {
                const osc = ctx.createOscillator();
                const gain = ctx.createGain();
                osc.type = "sine";
                osc.frequency.value = freq;
                osc.connect(gain);
                gain.connect(ctx.destination);
                const now = ctx.currentTime;
                const start = now + startOffset;
                const duration = 0.18;
                gain.gain.setValueAtTime(0, now);
                gain.gain.linearRampToValueAtTime(0.5, start);
                gain.gain.linearRampToValueAtTime(0.0, start + duration);
                osc.start(start);
                osc.stop(start + duration + 0.02);
            }
            // Double ping: lower then higher
            beep(880, 0.0);
            beep(1320, 0.32);
        } catch (e) {
            console.log("Audio error", e);
        }
    })();
    </script>
    """
    st.markdown(js, unsafe_allow_html=True)


# ---------------- Session state ----------------
if "ack_breaking_id" not in st.session_state:
    st.session_state["ack_breaking_id"] = None

# ---------------- Data fetch ----------------
data = fetch_json(DATA_JSON_URL)
items: List[Dict] = data.get("items", []) or []
generated_at = data.get("generated_at")
last_update = pretty_dt(generated_at) if generated_at else "n/a"

# ---------------- Header ----------------
st.title("Global Situational Awareness Dashboard")

# Fetch Discord breaking + decide if active
breaking = fetch_discord_breaking()
breaking_active = breaking if is_breaking_active(breaking) else None

# Top breaking banner (Style A)
if breaking_active:
    content = breaking_active.get("content", "")
    author = breaking_active.get("author", "")
    ts_pretty = breaking_active.get("created_at_pretty", "")
    st.markdown(
        f"""
        <div class="breaking-banner">
            <div class="breaking-label-pill">
                <span>⚡</span>
                <span>BREAKING</span>
            </div>
            <div>
                <div class="breaking-main-text">{clamp_txt(content, 260)}</div>
                <div class="breaking-meta">
                    via {author}{(" · " + ts_pretty) if ts_pretty else ""}
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    st.caption("No active breaking item in the last 3 hours, or Discord is not configured.")

# Central alert with big acknowledge button + sound,
# only if breaking is active and this message not yet acknowledged
if breaking_active and breaking_active.get("id") != st.session_state["ack_breaking_id"]:
    # Play the double ping once per rerun while alert is visible
    play_double_ping()

    st.markdown(
        f"""
        <div class="breaking-alert">
            <div style="text-align:center;">
                <div class="breaking-alert-title">🚨 BREAKING INCIDENT</div>
                <div class="breaking-alert-text">
                    {clamp_txt(breaking_active.get("content", ""), 280)}
                </div>
                <div class="breaking-alert-meta">
                    Source: {breaking_active.get("author", "Unknown")}
                    {(" · " + breaking_active.get("created_at_pretty", "")) if breaking_active.get("created_at_pretty") else ""}
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Centre the acknowledge button
    ack_col1, ack_col2, ack_col3 = st.columns([3, 1, 3])
    with ack_col2:
        if st.button("Acknowledge breaking alert", key="ack_breaking_button"):
            st.session_state["ack_breaking_id"] = breaking_active.get("id")
            st.rerun()

# Header info row (last update + refresh)
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

map_points: List[Dict] = []
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
        get_radius=80000,
        pickable=True,
        get_fill_color=[255, 90, 0, 230],  # bright orange against dark map
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
        "style": {"backgroundColor": "#020617", "color": "white"},
    }

    deck_kwargs = {
        "layers": [layer],
        "initial_view_state": view_state,
        "tooltip": tooltip,
    }
    if MAPBOX_API_KEY:
        deck_kwargs["map_style"] = "mapbox://styles/mapbox/dark-v11"

    deck = pdk.Deck(**deck_kwargs)
    st.pydeck_chart(deck)
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

# Social media + X OSINT tabs on the right
with colSocial:
    st.subheader("Social media")

    # Existing social items from your JSON feed
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

    st.markdown("#### X / OSINT feeds")

    tab1, tab2, tab3, tab4 = st.tabs(
        ["SentDefender", "IntelDoge", "BNO News", "OSINTdefender"]
    )

    sentdef_html = """
    <a class="twitter-timeline"
       data-theme="dark"
       data-chrome="nofooter noheader transparent"
       href="https://twitter.com/sentdefender">
       Tweets by @sentdefender
    </a>
    <script async src="https://platform.twitter.com/widgets.js" charset="utf-8"></script>
    """

    inteldoge_html = """
    <a class="twitter-timeline"
       data-theme="dark"
       data-chrome="nofooter noheader transparent"
       href="https://twitter.com/IntelDoge">
       Tweets by @IntelDoge
    </a>
    <script async src="https://platform.twitter.com/widgets.js" charset="utf-8"></script>
    """

    bno_html = """
    <a class="twitter-timeline"
       data-theme="dark"
       data-chrome="nofooter noheader transparent"
       href="https://twitter.com/BNONews">
       Tweets by @BNONews
    </a>
    <script async src="https://platform.twitter.com/widgets.js" charset="utf-8"></script>
    """

    osintdef_html = """
    <a class="twitter-timeline"
       data-theme="dark"
       data-chrome="nofooter noheader transparent"
       href="https://twitter.com/OSINTdefender">
       Tweets by @OSINTdefender
    </a>
    <script async src="https://platform.twitter.com/widgets.js" charset="utf-8"></script>
    """

    with tab1:
        components.html(sentdef_html, height=600, scrolling=True)
    with tab2:
        components.html(inteldoge_html, height=600, scrolling=True)
    with tab3:
        components.html(bno_html, height=600, scrolling=True)
    with tab4:
        components.html(osintdef_html, height=600, scrolling=True)




