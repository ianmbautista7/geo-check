"""
app.py
------
The Streamlit web app. This is what people see when they click the link.

Three views:
  1. Study results   Reads saved files. No API calls, loads instantly. This is the
                     default so a recruiter clicking the link sees a finished report.
  2. Run your own    A live check. Visitors must bring their own API key, so random
                     visitors can't use up the owner's small free daily allowance.
  3. Build study     Owner only (password). Runs the real study with the owner's key
                     and lets you download the results to commit to GitHub.

Run locally:  streamlit run app.py
"""

import io
import json
import os
import sys
import zipfile

import pandas as pd
import streamlit as st

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import models
import run_check

st.set_page_config(page_title="GEO Check", page_icon="📊", layout="wide")

KEY_NAMES = {"gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY", "claude": "ANTHROPIC_API_KEY"}


def secret(name):
    """Read one value from Streamlit's secrets. Returns None when running without a secrets file."""
    try:
        return st.secrets.get(name)
    except Exception:
        return None


def is_owner():
    """
    True only if the person typed the owner password from the app's secrets.
    Why: the free Gemini tier allows about 20 questions per model per day. If any
    visitor could spend that, the owner couldn't run their own study.
    """
    expected = secret("ADMIN_PASSWORD")
    return bool(expected) and st.session_state.get("owner_pw") == expected


def load_study():
    path = os.path.join(HERE, "study_results.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def load_answers():
    path = os.path.join(HERE, "study_answers.csv")
    return pd.read_csv(path) if os.path.exists(path) else None


def score_icon(score):
    return "🟢" if score >= 70 else ("🟡" if score >= 40 else "🔴")


def show_error(e):
    st.error(f"The check stopped: {e}")
    st.caption(
        "Daily limit messages reset at midnight Pacific. A key message means the key "
        "is wrong or was deleted. Anything else, try again with fewer questions."
    )


def show_business(detail, rows_df=None):
    d1, d2, d3, d4 = st.columns(4)
    d1.metric("Visibility score", f"{score_icon(detail['score'])} {detail['score']}")
    d2.metric("Mention rate", f"{detail['mention_rate']:.0%}")
    d3.metric("Avg position", detail["avg_position"] or "n/a")
    d4.metric("Consistency", detail["consistency"])

    by_model = detail.get("by_model", {})
    if len(by_model) > 1:
        st.markdown("**Models disagree.** Same questions, different answers:")
        st.dataframe(pd.DataFrame([{"Model": m, "Score": v["score"], "Mention rate": v["mention_rate"]}
                                   for m, v in by_model.items()])
                     .style.format({"Mention rate": "{:.0%}"}),
                     use_container_width=True, hide_index=True)

    st.markdown("**Suggested next steps**")
    for i, tip in enumerate(detail.get("suggestions", []), 1):
        st.markdown(f"{i}. {tip}")

    if rows_df is not None and len(rows_df):
        with st.expander("See the actual AI answers behind these numbers"):
            cols = [c for c in ["question", "model", "run", "mentioned", "position", "sentiment", "snippet"]
                    if c in rows_df.columns]
            st.dataframe(rows_df[cols], use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
st.sidebar.title("GEO Check")
st.sidebar.caption("How often do AI models recommend a business?")

views = ["Study results", "Run your own check"]
if is_owner():
    views.append("Build study (owner)")
mode = st.sidebar.radio("View", views)

st.sidebar.markdown("---")
st.sidebar.caption("Built by Ian Bautista. Measures whether AI assistants name a "
                   "business when someone asks for a recommendation.")
if secret("ADMIN_PASSWORD"):
    with st.sidebar.expander("Owner"):
        st.text_input("Password", type="password", key="owner_pw")
        if is_owner():
            st.caption("Unlocked. Your saved key will be used.")

# ---------------------------------------------------------------------------
# View 1: saved study
# ---------------------------------------------------------------------------
if mode == "Study results":
    study = load_study()
    if not study:
        st.title("GEO Check")
        st.info("The first study hasn't been published yet. Try **Run your own check** "
                "with the free demo model in the meantime.")
        st.stop()

    st.title(f"Which {study['category']}s does AI recommend in {study['city']}?")
    st.markdown(
        f"**{study['questions']} customer questions × {study['runs']} runs = "
        f"{study['api_calls']} AI answers**, collected {study['run_date']} from "
        f"{', '.join(study['models_used'])}. The business name never appears in a question: "
        "a business only counts if the AI brings it up on its own. The competitors below "
        "weren't chosen by us. They're the businesses the AI named most often."
    )

    results = study["results"]
    df = pd.DataFrame([{
        "Business": ("⭐ " if r.get("is_target") else "") + r["business"],
        "Score": r["score"],
        "Mention rate": r["mention_rate"],
        "Avg position": r["avg_position"],
        "Consistency": r["consistency"],
    } for r in results])

    target = next((r for r in results if r.get("is_target")), None)
    if target:
        rank = [r["business"] for r in results].index(target["business"]) + 1
        c1, c2, c3 = st.columns(3)
        c1.metric(f"{target['business']} rank", f"#{rank} of {len(results)}")
        c2.metric(f"{target['business']} score", f"{target['score']}")
        c3.metric("Top score", f"{results[0]['score']}", results[0]["business"])

    st.subheader("Leaderboard")
    import altair as alt  # ships with Streamlit
    chart_df = df.assign(Yours=[bool(r.get("is_target")) for r in results])
    st.altair_chart(
        alt.Chart(chart_df).mark_bar().encode(
            x=alt.X("Score:Q", scale=alt.Scale(domain=[0, 100])),
            y=alt.Y("Business:N", sort="-x", title=None),
            color=alt.condition("datum.Yours", alt.value("#E4572E"), alt.value("#4C78A8")),
            tooltip=["Business", "Score", alt.Tooltip("Mention rate:Q", format=".0%")],
        ).properties(height=36 * len(chart_df) + 40),
        use_container_width=True,
    )
    st.dataframe(df.style.format({"Mention rate": "{:.0%}", "Score": "{:.1f}", "Avg position": "{:.1f}"}),
                 use_container_width=True, hide_index=True)

    st.subheader("Look at one business")
    pick = st.selectbox("Business", [r["business"] for r in results])
    detail = next(r for r in results if r["business"] == pick)
    answers = load_answers()
    show_business(detail, answers[answers["business"] == pick] if answers is not None else None)
    if answers is not None:
        st.download_button("Download every answer (CSV)", answers.to_csv(index=False).encode(),
                           file_name="geocheck_study_answers.csv", mime="text/csv")

# ---------------------------------------------------------------------------
# View 2: live check
# ---------------------------------------------------------------------------
elif mode == "Run your own check":
    st.title("Run your own check")
    st.caption("Pick **demo** to try it free with fake answers. Real models need your own API key, "
               "used for this run only and never saved.")

    with st.form("check"):
        c1, c2, c3 = st.columns(3)
        name = c1.text_input("Business name", "Goodthing Coffee")
        category = c2.text_input("Category", "coffee shop")
        city = c3.text_input("City", "Burlingame, CA")
        aliases = st.text_input("Other spellings (comma separated)", "Good Thing Coffee")
        c4, c5, c6 = st.columns(3)
        provider = c4.selectbox("Model", ["demo", "gemini", "openai", "claude"])
        n_questions = c5.slider("Questions", 3, 20, 5)
        runs = c6.slider("Runs per question", 1, 3, 1)
        typed_key = st.text_input("Your API key (not needed for demo)", type="password")
        go = st.form_submit_button("Run check")

    if go:
        key = None
        if provider != "demo":
            key = typed_key or (secret(KEY_NAMES[provider]) if is_owner() else None)
            if not key:
                st.error("Real models need an API key. Pick **demo** to try it without one.")
                st.stop()

        total = n_questions * runs
        bar = st.progress(0.0, text=f"Asking the model... 0 of {total} answers back")
        try:
            rows = run_check.run_business(
                name, category, city, [provider], runs=runs,
                aliases=[a.strip() for a in aliases.split(",") if a.strip()],
                num_questions=n_questions, verbose=False, api_key=key,
                on_progress=lambda d, t: bar.progress(d / t, text=f"Asking the model... {d} of {t} answers back"),
            )
        except models.ModelError as e:
            bar.empty()
            show_error(e)
            st.stop()
        bar.empty()
        if provider == "demo":
            st.warning("Demo mode: these answers are fake, generated to show how the tool works.")
        summary = run_check.summarize(rows, name)
        if summary["errors"]:
            st.warning(f"{summary['errors']} of {len(rows)} calls failed and were left out of the score.")
        show_business(summary, pd.DataFrame(rows))

# ---------------------------------------------------------------------------
# View 3: build the published study (owner only)
# ---------------------------------------------------------------------------
else:
    st.title("Build the study")
    st.caption("Uses your saved key. The free tier allows about 20 questions per model per day, "
               "and the tool moves to another Gemini model when one runs out.")

    with st.form("study"):
        c1, c2, c3 = st.columns(3)
        target = c1.text_input("Your business", "Goodthing Coffee")
        category = c2.text_input("Category", "coffee shop")
        city = c3.text_input("City", "Burlingame, CA")
        aliases = st.text_input("Other spellings (comma separated)", "Good Thing Coffee, Goodthing")
        c4, c5, c6 = st.columns(3)
        n_questions = c4.slider("Questions", 5, 20, 10)
        runs = c5.slider("Runs per question", 1, 3, 2)
        competitors = c6.slider("Competitors to show", 3, 10, 8)
        st.caption("Calls = questions × runs. 10 × 2 = 20, about one model's free daily allowance.")
        go = st.form_submit_button("Build study")

    if go:
        key = secret("GEMINI_API_KEY")
        if not key:
            st.error("No GEMINI_API_KEY in the app's secrets.")
            st.stop()
        total = n_questions * runs
        bar = st.progress(0.0, text=f"Asking Gemini... 0 of {total}")
        try:
            study, rows = run_check.build_study(
                {"name": target, "aliases": [a.strip() for a in aliases.split(",") if a.strip()]},
                category, city, ["gemini"], runs=runs, num_questions=n_questions,
                api_key=key, competitors=competitors,
                on_progress=lambda d, t: bar.progress(d / t, text=f"Asking Gemini... {d} of {t}"),
            )
        except models.ModelError as e:
            bar.empty()
            show_error(e)
            st.stop()
        bar.empty()

        st.success(f"Done: {study['api_calls']} answers from {', '.join(study['models_used'])}, "
                   f"{study['failed_calls']} failed.")
        st.dataframe(pd.DataFrame([{"Business": ("⭐ " if r.get("is_target") else "") + r["business"],
                                    "Score": r["score"], "Mention rate": r["mention_rate"]}
                                   for r in study["results"]])
                     .style.format({"Mention rate": "{:.0%}"}),
                     use_container_width=True, hide_index=True)

        # Streamlit Cloud forgets files when it restarts, so results have to go to GitHub.
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("study_results.json", json.dumps(study, indent=2))
            z.writestr("study_answers.csv", pd.DataFrame(rows).to_csv(index=False))
        st.download_button("Download results", buf.getvalue(), file_name="geocheck_study.zip",
                           mime="application/zip")
        st.info("To publish: unzip, then upload **study_results.json** and **study_answers.csv** "
                "to the main page of your GitHub repo. The Study results page updates by itself.")
