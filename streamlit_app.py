import os, json, requests, streamlit as st
from datetime import datetime
import base64

st.set_page_config(page_title="Airport & UK Missions Dashboard", layout="wide")

# --- Auto refresh every 60s ---
st.markdown("<meta http-equiv='refresh' content='60'>", unsafe_allow_html=True)

DATA_JSON_URL = os.getenv("DATA_JSON_URL", "").strip()

@st.cache_data(ttl=30)
def load_data():
    if DATA_JSON_URL:
        r = requests.get(DATA_JSON_URL, timeout=20)
        r.raise_for_status()
        return r.json()
    try:
        with open("data.json","r",encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"generated_at": None, "items": [], "trends": {"top_terms": []}}

# --- Short embedded beep sound ---
_BEEP = (
    "SUQzAwAAAAAFI1RTU0UAAAAPAAACc2RhdGEAAAAA"
)

def play_beep():
    audio_html = f"""
    <audio autoplay>
      <source src="data:audio/wav;base64,{_BEEP}">
    </audio>
    """
    st.markdown(audio_html, unsafe_allow_html=True)


# --- Load data ---
data = load_data()
generated = data.get("generated_at")
items = data.get("items", [])

# --- Alert logic ---
if "seen_ids" not in st.session_state:
    st.session_state.seen_ids = set()

def is_qualifying(it):
    tags = set(it.get("tags", []))
    conf = it.get("confidence", "low")
    return (("airport/security" in tags) or ("diplomatic" in tags)) and (conf in {"high","medium"})

current_ids = {it["id"] for it in items if is_qualifying(it)}
new_ids = current_ids - st.session_state.seen_ids

if new_ids:
    st.success(f"New qualifying items: {len(new_ids)}")
    play_beep()

st.session_state.seen_ids |= current_ids


# --- Page header with floating crest ---
st.title("Airport & UK Missions Situational Dashboard")

# CSS to float crest in top-right
crest_css = """
<style>
.crest {
    position: fixed;
    top: 10px;
    right: 20px;
    z-index: 9999;
}
</style>
"""
st.markdown(crest_css, unsafe_allow_html=True)

st.markdown(
    '<img src="crest.png" class="crest" width="80">', 
    unsafe_allow_html=True
)


# --- Timestamp ---
if generated:
    ts = datetime.fromisoformat(generated.replace("Z","+00:00"))
    st.caption(f"Last update: {ts.isoformat()}")
else:
    st.warning("No data found yet. Check DATA_JSON_URL or generate data.json.")


# --- Filters ---
col1, col2, col3 = st.columns([2,2,2])
q = col1.text_input("Search", "")
tag_filter = col2.multiselect("Tags", ["airport/security","diplomatic","UK-focus","LHR","LGW","STN","LTN","MAN","BHX"])
type_filter = col3.multiselect("Type", ["news","social"], ["news","social"])

def match(it):
    txt = (it.get("title","") + " " + it.get("summary","")).lower()
    if q and q.lower() not in txt: return False
    if tag_filter and not any(t in it.get("tags",[]) for t in tag_filter): return False
    if type_filter and it.get("type") not in type_filter: return False
    return True

buckets = {"high": [], "medium": [], "low": []}
for it in items:
    if match(it):
        buckets.get(it.get("confidence","low"), buckets["low"]).append(it)


# --- Trends ---
st.subheader("Trends (last 12h)")
for term, count in data.get("trends",{}).get("top_terms", [])[:15]:
    st.write(f"- **{term}** ×{count}")


# --- Columns ---
colH, colM, colL = st.columns(3)

def show(col, title, arr):
    col.subheader(title)
    for it in arr[:120]:
        with col.expander(it["title"]):
           geo = it.get("geo", {}) or {}
locbits = [geo.get("airport"), geo.get("city"), geo.get("country")]
loc = " | ".join([x for x in locbits if x])
tags = ", ".join(it.get("tags",[]))
col.caption(f"{it.get('source','')} | {it.get('published_at','')}" + (f" | {loc}" if loc else "") + (f" | {tags}" if tags else ""))

            if it.get("summary"):
                col.write(it["summary"])
            col.write(f"[Open source]({it['url']})")

show(colH, "High confidence", buckets["high"])
show(colM, "Medium confidence", buckets["medium"])
show(colL, "Low confidence (social/unverified)", buckets["low"])
