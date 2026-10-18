import os
import re
import time
import streamlit as st
from agents import build_search_agent, build_reader_agent, writer_chain, critic_chain
from tools import scrape_url

st.set_page_config(page_title="Research Relay", page_icon="🔎", layout="centered")

# ---------- styling ----------
st.markdown("""
<style>
#MainMenu, footer, [data-testid="stToolbar"] {visibility: hidden;}
.block-container {padding-top: 2.5rem; max-width: 960px;}
.hero h1 {font-size: 2.7rem; letter-spacing: -0.02em; margin: 0 0 4px 0; padding: 0;}
.hero p {color: #93A5B0; font-size: 1.05rem; margin: 0 0 8px 0; max-width: 58ch;}
.agents {display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 22px 0 8px 0;}
@media (max-width: 700px) {.agents {grid-template-columns: repeat(2, 1fr);}}
.agent {background: #16242D; border: 1px solid #273944; border-radius: 12px; padding: 14px 14px 12px 14px;}
.agent .ico {font-size: 1.5rem;}
.agent .nm {font-weight: 600; margin-top: 6px;}
.agent .ds {color: #93A5B0; font-size: .86rem;}
.agent .bd {font-size: .82rem; margin-top: 10px; color: #6F8591;}
.agent.run {border-color: #3DB8B0; animation: pulse 1.4s ease-in-out infinite;}
.agent.run .bd {color: #3DB8B0;}
.agent.done {border-color: #3DB8B0; background: #16363A;}
.agent.done .bd {color: #3DB8B0;}
.agent.warn {border-color: #E0A84B;}
.agent.warn .bd {color: #E0A84B;}
@keyframes pulse {50% {box-shadow: 0 0 0 5px rgba(61, 184, 176, .18);}}
@media (prefers-reduced-motion: reduce) {.agent.run {animation: none;}}
div[data-testid="stMetric"] {background: #16242D; border: 1px solid #273944; border-radius: 12px; padding: 14px 16px;}
.stTabs [data-baseweb="tab-list"] {gap: 6px;}
.foot {color: #6F8591; font-size: .85rem; margin-top: 40px; text-align: center;}
</style>
""", unsafe_allow_html=True)

AGENTS = [
    ("search", "🔎", "Search agent", "Finds sources on the web"),
    ("read", "📖", "Reader agent", "Opens the best page"),
    ("write", "✍️", "Writer", "Drafts the report"),
    ("critic", "🧐", "Critic", "Scores and reviews it"),
]
BADGES = {"wait": "Waiting", "run": "Working…", "done": "Done", "warn": "Skipped, used search results"}
EXAMPLES = ["Solid-state batteries in EVs", "How do vaccines train the immune system?", "Future of remote work"]


def stepper(states: dict) -> str:
    cards = ""
    for key, icon, name, desc in AGENTS:
        s = states.get(key, "wait")
        cards += (f'<div class="agent {s}"><div class="ico">{icon}</div>'
                  f'<div class="nm">{name}</div><div class="ds">{desc}</div>'
                  f'<div class="bd">{BADGES[s]}</div></div>')
    return f'<div class="agents">{cards}</div>'


def _text(msg) -> str:
    c = msg.content
    if isinstance(c, list):
        return "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in c)
    return c


def extract_urls(text: str, limit: int = 3) -> list:
    urls = re.findall(r"https?://[^\s)\]>\"']+", text)
    return list(dict.fromkeys(u.rstrip(".,;:") for u in urls))[:limit]


def run_pipeline(topic: str, show) -> dict:
    t0, states = time.time(), {}

    def mark(key, value):
        states[key] = value
        show(states)

    mark("search", "run")
    r = build_search_agent().invoke({"messages": [(
        "user", f"Find recent, reliable and detailed information about: {topic}")]})
    search_results = _text(r["messages"][-1])
    all_text = "\n".join(_text(m) for m in r["messages"])  # includes the raw tool output
    mark("search", "done")

    mark("read", "run")
    urls = extract_urls(all_text)
    scraped, reader_error = "(No scraped content available.)", None
    try:
        r = build_reader_agent().invoke({"messages": [(
            "user",
            f"Pick the most relevant of these URLs for the topic '{topic}' "
            f"and scrape it for deeper content:\n" + "\n".join(urls))]})
        scraped = _text(r["messages"][-1])[:8000]
    except Exception as e:
        reader_error = str(e)[:300]
        for u in urls:  # fallback: scrape directly, without the model
            page = scrape_url.invoke({"url": u})
            if not page.startswith(("Could not scrape", "The page had no")):
                scraped = f"Source: {u}\n{page}"
                break
    mark("read", "warn" if scraped.startswith("(No") else "done")

    mark("write", "run")
    research = (f"SEARCH RESULTS:\n{search_results}\n\n"
                f"DETAILED SCRAPED CONTENT:\n{scraped}")
    report = writer_chain.invoke({"topic": topic, "research": research})
    mark("write", "done")

    mark("critic", "run")
    feedback = critic_chain.invoke({"report": report})
    mark("critic", "done")

    return {"topic": topic, "search": search_results, "scraped": scraped,
            "report": report, "feedback": feedback, "seconds": time.time() - t0,
            "reader_error": reader_error}


def set_topic(value: str):
    st.session_state.topic = value


# ---------- page ----------
st.markdown(
    '<div class="hero"><h1>Research Relay</h1>'
    '<p>Four AI agents pass your topic along, one after another, and hand you a finished, '
    'reviewed report with sources.</p></div>',
    unsafe_allow_html=True,
)

topic = st.text_input("Research topic", key="topic", placeholder="What should we research?",
                      label_visibility="collapsed")

cols = st.columns(len(EXAMPLES))
for col, ex in zip(cols, EXAMPLES):
    col.button(ex, key=f"ex_{ex}", on_click=set_topic, args=(ex,), use_container_width=True)

start = st.button("Start research", type="primary", use_container_width=True,
                  disabled=not topic.strip())

stepper_box = st.empty()
stepper_box.markdown(stepper(st.session_state.get("states", {})), unsafe_allow_html=True)

if start:
    try:
        def show(states):
            st.session_state["states"] = dict(states)
            stepper_box.markdown(stepper(states), unsafe_allow_html=True)

        st.session_state["result"] = run_pipeline(topic.strip(), show)
    except Exception as e:
        st.error(f"Something went wrong: {e}")
        st.caption("Common causes: a rate limit (wait a minute and retry) or a missing API key in .env.")

result = st.session_state.get("result")
if result:
    report, feedback = result["report"], result["feedback"]
    m = re.search(r"Score:\s*(\d+(?:\.\d+)?)\s*/\s*10", feedback, re.I)
    urls = list(dict.fromkeys(u.rstrip(".,;:") for u in re.findall(r"https?://[^\s)\]>\"']+", report)))

    if result.get("reader_error"):
        st.info(f"The reader agent hit a problem ({result['reader_error']}). "
                "The page was scraped directly instead, or search results were used.")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Critic score", f"{m.group(1)}/10" if m else "n/a")
    c2.metric("Words", f"{len(report.split()):,}")
    c3.metric("Sources", len(urls))
    c4.metric("Time", f"{result['seconds']:.0f}s")

    tab_report, tab_review, tab_sources, tab_raw = st.tabs(
        ["Report", "Critic’s review", "Sources", "Raw research"])

    with tab_report:
        st.markdown(report)
        st.download_button("Download report (.md)", report,
                           file_name="report.md", mime="text/markdown")

    with tab_review:
        st.markdown(re.sub(r"^\s*Score:.*$", "", feedback, flags=re.I | re.M))

    with tab_sources:
        if urls:
            for u in urls:
                st.markdown(f"- [{u}]({u})")
        else:
            st.caption("No links were found in the report.")

    with tab_raw:
        with st.expander("Search results"):
            st.text(result["search"])
        with st.expander("Scraped page content"):
            st.text(result["scraped"])

model = os.getenv("LLM_MODEL", "default model")
st.markdown(f'<div class="foot">Built with LangChain, Tavily and Streamlit. Model: {model}</div>',
            unsafe_allow_html=True)