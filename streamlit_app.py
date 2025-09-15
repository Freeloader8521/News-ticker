import os
import json
from textwrap import shorten
from datetime import datetime
from typing import List, Dict

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

# OpenAI
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

def pick_language_text(it: Dict, translate_on: bool) -> (str, str):
    if translate_on:
        return it.get("title_en") or it.get("title") or it.get("title_orig") or "", \
               it.get("summary_en") or it.get("summary") or it.get("summary_orig") or ""
    else:
        # Prefer originals when translate is OFF; fall back to English
        return it.get("title_orig") or it.get("title") or it.get("title_en") or "", \
               it.get("summary_orig") or it.get("summary") or it.get("summary_en") or ""

# ---------------- OpenAI: risk summary ----------------
@st.cache_data(ttl=300, show_spinner=False)
def ai_risk_summary(cache_key: str, items: List[Dict], model: str, translate_on: bool) -> str:
    """
    cache_key is usually data['generated_at'] so we re-summarize only when new data arrives.
    We keep the prompt small for cost—top 80 relevant items, each truncated.
    """
    if not OPENAI_API_KEY:
        return "Set OPENAI_API_KEY in your Streamlit secrets to enable the AI summary."

    # Select the most relevant items: keep airport/security & diplomatic first
    def is_risk(it):
        tags = it.get("tags", [])
        return ("airport/security" in tags) or ("diplomatic" in tags)

    risk_items = [it for it in items if is_risk(it)]
    if not risk_items:
        risk_items = items[:60]
    else:
        risk_items = risk_items[:80]

    # Build compact lines
    lines = []
    for it in risk_items:
        title, summary = pick_language_text(it, translate_on)
        src = it.get("source") or ""
        when = pretty_dt(it.get("published_at") or "")
        typ = it.get("type") or ""
        geo = it.get("geo") or {}
        loc = " / ".join(x for x in [geo.get("city"), geo.get("country"), geo.get("iata")] if x)
        line = f"- {clamp_txt(title, 160)} | {typ} | {src} | {when}"
        if loc:
            line += f" | {loc}"
        if summary:
            line += f"\n  {clamp_txt(summary, 280)}"
        lines.append(line)

    # Prompt
    sys = (
        "You are an analyst for an aviation/physical security dashboard. "
        "Given recent items, extract concrete, near-term risks to PHYSICAL well-being: "
        "e.g., attacks near airports/transport, airspace closures, strikes causing safety gaps, "
        "severe weather disrupting operations, evacuations, diplomatic incidents that may trigger protests. "
        "Ignore finance/celebrity/politics unless it implies a physical security or operations impact. "
        "Be concise and specific. Group by theme. Use bullet points. For each bullet add: "
        "[Severity: low|moderate|high] and a crisp 3–7 word title, then 1 line detail with where/when if present. "
        "Do NOT hallucinate. If uncertain, mark Severity: low."
    )
    user = "Recent items:\n" + "\n".join(lines)

    # OpenAI call (chat.completions)
    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": sys},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
            max_tokens=800,
        )
        return resp.choices[0].message.content.strip()
    except Exception as ex:
        return f"⚠️ OpenAI error: {ex}"

# ---------------- Layout ----------------
st.set_page_config(page_title="Global Situational Awareness Dashboard", layout="wide")

# CSS – force light mode, outlines on buttons, tidy headings
st.markdown(
    """
    <style>
    html, body, [class*="st-"] { color: #111 !important; background: #fff !important; }
    .block-container { padding-top: 1rem; padding-bottom: 1rem; }
    .stButton button, .stDownloadButton button {
        border: 1px solid #444 !important; padding: 0.4rem 1rem; border-radius: 4px;
    }
    .chip { display:inline-block; padding: 0.12rem 0.5rem; border:1px solid #ddd; border-radius:999px; font-size:0.8rem; margin-left:0.3rem; }
    h2 { margin-top: 1rem; border-bottom: 2px solid #eee; padding-bottom: 0.3rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

# -------- Data fetch
data = fetch_json(DATA_JSON_URL)
items = data.get("items", [])
generated_at = data.get("generated_at")
last = pretty_dt(generated_at) if generated_at else "n/a"

# -------- Header Row
st.title("Global Situational Awareness Dashboard")
headA, headB = st.columns([6, 1])
with headA:
    st.markdown(f"**Last update:** {last}")
with headB:
    if st.button("Refresh", use_container_width=True):
        with st.spinner("Refreshing feeds…"):
            st.cache_data.clear()
            st.rerun()

# -------- Translate toggle (ON/OFF pill)
pill_col1, pill_col2 = st.columns([1, 5])
with pill_col1:
    translate = st.toggle("Translate", value=True, help="Switch between original and English.")
with pill_col2:
    st.write("")  # spacer

# -------- Status / progress (from status.json if available)
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

# -------- NEW: Risk summary (AI)
with st.container(border=True):
    topL, topR = st.columns([0.7, 0.3])
    with topL:
        st.subheader("Risk summary (AI)")
        st.caption("Auto-extracted, near-term physical safety/operations risks from the latest items.")
    with topR:
        model = st.selectbox("Model", [DEFAULT_MODEL, "gpt-4o", "gpt-4.1-mini"], index=0)
        gen_now = st.button("Generate summary", help="Uses your OpenAI key (set in Secrets).")

    memo_key = f"{generated_at}|{model}|{int(bool(translate))}"
    if gen_now:
        with st.spinner("Analyzing items with OpenAI…"):
            summary = ai_risk_summary(memo_key, items, model, translate)
            st.session_state["ai_summary"] = summary

    if "ai_summary" in st.session_state:
        st.markdown(st.session_state["ai_summary"])
    else:
        st.info("Click **Generate summary** to create an AI overview of key risks.")

# -------- Controls
colSearch, colType = st.columns([3, 2])
with colSearch:
    search = st.text_input("Search", "")
with colType:
    type_choices = ["major news", "local news", "social"]
    type_filter = st.multiselect("Type", type_choices, default=type_choices)

# -------- Filter items
def filter_items(items_in: List[Dict]) -> List[Dict]:
    out = items_in
    if search:
        s = search.lower()
        out = [it for it in out if s in (it.get("title","")+it.get("summary","")+it.get("title_en","")+it.get("summary_en","")).lower()]
    if type_filter:
        out = [it for it in out if it.get("type") in type_filter]
    return out

items = filter_items(items)

# -------- Columns
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
        if summary:
            st.markdown(summary)
        if it.get("url"):
            st.markdown(f"[Open source]({it['url']})")
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
        if summary:
            st.markdown(summary)
        if it.get("url"):
            st.markdown(f"[Open source]({it['url']})")
        st.markdown("---")
