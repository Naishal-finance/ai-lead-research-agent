"""
Web app for the AI Lead Research Agent.
Run:  streamlit run app.py
Opens in your browser. Free with a Gemini key or local Ollama.
"""

import io
import os
import time

import pandas as pd
import streamlit as st

import lead_agent as agent

st.set_page_config(page_title="AI Lead Research Agent", page_icon="🎯", layout="wide")
st.title("🎯 AI Lead Research Agent")
st.caption("Paste companies → AI reads their websites → scores fit → drafts personal emails. Built by Naishal Parmar.")

# ── Sidebar: settings ───────────────────────────────────────────────────────
with st.sidebar:
    st.header("Settings")
    provider = st.selectbox("AI engine", ["demo", "gemini", "ollama", "claude"],
                            help="demo = no AI, for testing. gemini & ollama are free.")
    if provider == "gemini":
        key = st.text_input("Gemini API key (free at aistudio.google.com)", type="password",
                            value=os.environ.get("GEMINI_API_KEY", ""))
        if key:
            os.environ["GEMINI_API_KEY"] = key
    if provider == "claude":
        key = st.text_input("Claude API key", type="password",
                            value=os.environ.get("ANTHROPIC_API_KEY", ""))
        if key:
            os.environ["ANTHROPIC_API_KEY"] = key
    sender = st.text_input("Sign emails as", "Naishal")
    st.markdown("---")
    st.caption("Your key stays on your computer and is never saved.")

# ── Inputs ──────────────────────────────────────────────────────────────────
col1, col2 = st.columns(2)
with col1:
    st.subheader("1. What do you offer?")
    default_offer = open("offer.txt", encoding="utf-8").read() if os.path.exists("offer.txt") else ""
    offer = st.text_area("Describe your product/service and ideal customer", default_offer, height=220)
with col2:
    st.subheader("2. Who should we research?")
    uploaded = st.file_uploader("Upload CSV with columns: company,website", type="csv")
    pasted = st.text_area("…or paste one per line:  Company, https://website.com",
                          "Brickanta, https://brickanta.com\nQonto, https://qonto.com\nMirakl, https://www.mirakl.com",
                          height=130)

def read_leads():
    if uploaded is not None:
        df = pd.read_csv(uploaded)
        df.columns = [c.strip().lower() for c in df.columns]
        return df[["company", "website"]].fillna("").to_dict("records")
    rows = []
    for line in pasted.splitlines():
        if "," in line:
            c, w = line.split(",", 1)
            rows.append({"company": c.strip(), "website": w.strip()})
    return rows

# ── Run ─────────────────────────────────────────────────────────────────────
if st.button("🚀 Research leads", type="primary"):
    leads = read_leads()
    needed = agent.KEY_NEEDED.get(provider)
    if not leads:
        st.error("Add at least one company.")
    elif not offer.strip():
        st.error("Describe what you offer.")
    elif needed and not os.environ.get(needed):
        st.error(f"Add your {provider} API key in the sidebar.")
    else:
        results, bar = [], st.progress(0.0, text="Starting…")
        for i, lead in enumerate(leads, 1):
            bar.progress((i - 1) / len(leads), text=f"Researching {lead['company']} ({i}/{len(leads)})…")
            row = dict(lead)
            try:
                if provider == "demo":
                    row.update(agent.demo_analysis(lead["company"]))
                else:
                    text = agent.research_company(lead["website"]) if lead["website"] else ""
                    row.update(agent.analyse(provider, offer, lead["company"], text, sender))
                    time.sleep(agent.DELAY[provider])
                row["status"] = "ok"
            except Exception as e:
                row.update({"fit_score": 0, "status": f"error: {e}"})
            results.append(row)
        bar.progress(1.0, text="Done!")
        st.session_state["results"] = sorted(results, key=lambda r: r.get("fit_score", 0), reverse=True)

# ── Results ─────────────────────────────────────────────────────────────────
if "results" in st.session_state:
    res = st.session_state["results"]
    df = pd.DataFrame(res)
    strong = int((df["fit_score"] >= 7).sum())
    m1, m2, m3 = st.columns(3)
    m1.metric("Companies researched", len(df))
    m2.metric("Strong leads (7+/10)", strong)
    m3.metric("Average fit", f"{df['fit_score'].mean():.1f}/10")

    st.subheader("Leads, best first")
    show = [c for c in ["company", "fit_score", "what_they_do", "likely_pain", "fit_reason", "status"] if c in df]
    st.dataframe(df[show], width="stretch", hide_index=True)

    st.subheader("Draft emails: read and edit before sending")
    for r in res:
        with st.expander(f"{r['company']} — fit {r.get('fit_score', 0)}/10"):
            st.text_input("Subject", r.get("email_subject", ""), key=f"s_{r['company']}")
            st.text_area("Email", r.get("email_body", ""), height=160, key=f"b_{r['company']}")

    buf = io.StringIO()
    df.reindex(columns=agent.FIELDS).to_csv(buf, index=False)
    st.download_button("⬇️ Download results (CSV)", buf.getvalue(), "lead_results.csv", "text/csv")
