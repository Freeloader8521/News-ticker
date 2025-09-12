import os, json, requests, streamlit as st
from datetime import datetime

st.set_page_config(page_title="Airport & UK Missions Dashboard", layout="wide")
DATA_JSON_URL = os.getenv("DATA_JSON_URL", "").strip()

@st.cache_data(ttl=300)
def load_data():
    if DATA_JSON_URL:
        r = requests.get(DATA_JSON_URL, timeout=20)
        r.raise_for_status()
        return r.json()
    # fallback: local file if present
    try:
        with open("data/data.json","r",encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"generated_at": None, "items": [], "trends": {"top_terms": []}}

data = load_data()
st.title("Airport & UK Missions Situational Dashboard")
if data.get("generated_at"):
    ts = datetime.fromisoformat(data["generated_at"].replace("Z","+00:00"))
    st.caption(f"Last update: {ts.isoformat()}")
else:
    st.warning("No data yet. Check DATA_JSON_URL or generate data.json.")

# Filters
col1, col2, col3 = st.columns([2,2,2])
q = col1.text_input("Search", "")
tag_filter = col2.multiselect("Tags", ["airport/security","diplomatic","UK-focus","LHR","LGW","STN","LTN","MAN","BHX"])
type_filter = col3.multiselect("Type", ["news","social"], ["news","social"])

items = data.get("items", [])
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

st.subheader("Trends (last 12h)")
for term, count in data.get("trends",{}).get("top_terms", [])[:15]:
    st.write(f"- **{term}** ×{count}")

colH, colM, colL = st.columns(3)
def show(col, title, arr):
    col.subheader(title)
    for it in arr[:120]:
        with col.expander(it["title"]):
            col.caption(f"{it.get('source','')} | {it.get('published_at','')} | {', '.join(it.get('tags',[]))}")
            if it.get("summary"): col.write(it["summary"])
            col.write(f"[Open source]({it['url']})")

show(colH, "High confidence", buckets["high"])
show(colM, "Medium confidence", buckets["medium"])
show(colL, "Low confidence (social/unverified)", buckets["low"])
