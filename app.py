"""
app.py
------
The Streamlit web app. This is the part people see when they click your link.

Two modes, and the split matters:
  1. "Study results" reads saved files from data/. No API key, no waiting.
     This is what loads by default so a visitor sees a finished report in
     one second instead of an empty form that errors out.
  2. "Run your own check" does a live run. Needs the visitor's own API key,
     entered in the sidebar and never saved anywhere.

Run locally:  streamlit run app.py
"""

import json
import os
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import run_check
import scoring

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def load_keys_from_secrets():
    """
    Pull API keys out of Streamlit's secrets manager and into environment variables.

    Why this exists: models.py reads keys with os.getenv(), because it has to work
    from the command line too, where Streamlit isn't running. Streamlit Cloud stores
    keys in st.secrets instead. This copies one into the other, so the same code
    works locally and deployed without changing anything.

    Wrapped in try/except because st.secrets raises if no secrets file exists,
    which is normal when running locally.
    """
    for name in ("GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        try:
            if name in st.secrets and not os.getenv(name):
                os.environ[name] = st.secrets[name]
        except Exception:
            pass


load_keys_from_secrets()


def has_key(provider):
    """True if a key for this provider is already available, so we can skip asking."""
    return bool(os.getenv({"gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY",
                           "claude": "ANTHROPIC_API_KEY"}.get(provider, "")))

st.set_page_config(page_title="GEO Check", page_icon="📊", layout="wide")


def load_study():
    path = os.path.join(DATA_DIR, "study.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def score_color(score):
    if score >= 70:
        return "🟢"
    if score >= 40:
        return "🟡"
    return "🔴"


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
st.sidebar.title("GEO Check")
st.sidebar.caption("How often do AI models recommend a business?")

mode = st.sidebar.radio("View", ["Study results", "Run your own check"])

st.sidebar.markdown("---")
st.sidebar.caption(
    "Built by Ian Bautista. Measures whether AI assistants name a business "
    "when someone asks for a recommendation."
)

# ---------------------------------------------------------------------------
# Mode 1: the saved study
# ---------------------------------------------------------------------------
if mode == "Study results":
    study = load_study()
    if not study:
        st.warning("No saved study yet. Run `python src/run_study.py --config study.json` first.")
        st.stop()

    st.title(f"Which {study['category']}s does AI recommend in {study['city']}?")
    st.markdown(
        f"**{len(study['results'])} businesses · {study['questions']} questions · "
        f"{len(study['providers'])} model(s) · {study['runs']} runs each.** "
        "The business name never appears in the question. We only count it if the "
        "model brings it up on its own."
    )

    results = study["results"]
    df = pd.DataFrame([{
        "Business": r["business"],
        "Score": r["score"],
        "Mention rate": r["mention_rate"],
        "Avg position": r["avg_position"],
        "Sentiment": r["avg_sentiment"],
        "Consistency": r["consistency"],
    } for r in results])

    # Headline numbers
    c1, c2, c3 = st.columns(3)
    c1.metric("Highest score", f"{df['Score'].max():.1f}", df.loc[df['Score'].idxmax(), 'Business'])
    c2.metric("Lowest score", f"{df['Score'].min():.1f}", df.loc[df['Score'].idxmin(), 'Business'])
    c3.metric("Spread", f"{df['Score'].max() - df['Score'].min():.1f} pts")

    st.subheader("Leaderboard")
    st.bar_chart(df.set_index("Business")["Score"], height=320)

    st.dataframe(
        df.style.format({"Mention rate": "{:.0%}", "Score": "{:.1f}",
                         "Avg position": "{:.1f}", "Sentiment": "{:.2f}"}),
        use_container_width=True, hide_index=True,
    )

    # Per business detail
    st.subheader("Look at one business")
    pick = st.selectbox("Business", [r["business"] for r in results])
    detail = next(r for r in results if r["business"] == pick)

    d1, d2, d3, d4 = st.columns(4)
    d1.metric("Visibility score", f"{score_color(detail['score'])} {detail['score']}")
    d2.metric("Mention rate", f"{detail['mention_rate']:.0%}")
    d3.metric("Avg position", detail["avg_position"] or "n/a")
    d4.metric("Consistency", detail["consistency"])

    if len(detail.get("by_provider", {})) > 1:
        st.markdown("**Models disagree.** Same questions, different answers:")
        prov_df = pd.DataFrame([{
            "Model": p, "Score": v["score"], "Mention rate": v["mention_rate"]
        } for p, v in detail["by_provider"].items()])
        st.dataframe(prov_df.style.format({"Mention rate": "{:.0%}"}),
                     use_container_width=True, hide_index=True)

    st.markdown("**Suggested next steps**")
    for i, tip in enumerate(detail.get("suggestions", []), 1):
        st.markdown(f"{i}. {tip}")

    # Raw answers, so nobody has to take the score on faith
    slug = run_check.slugify(pick)
    csv_path = os.path.join(DATA_DIR, f"results_{slug}.csv")
    if os.path.exists(csv_path):
        raw = pd.read_csv(csv_path)
        with st.expander("See the actual AI answers behind these numbers"):
            st.dataframe(
                raw[["question", "provider", "run", "mentioned", "position",
                     "sentiment", "snippet"]],
                use_container_width=True, hide_index=True,
            )
        st.download_button("Download full results as CSV",
                           raw.to_csv(index=False).encode(),
                           file_name=f"geocheck_{slug}.csv", mime="text/csv")

# ---------------------------------------------------------------------------
# Mode 2: live run
# ---------------------------------------------------------------------------
else:
    st.title("Run your own check")
    st.caption(
        "This makes real API calls, so it needs your own key. The key is used "
        "for this run only and is never stored."
    )

    with st.form("check"):
        c1, c2, c3 = st.columns(3)
        name = c1.text_input("Business name", "Goodthing Coffee")
        category = c2.text_input("Category", "coffee shop")
        city = c3.text_input("City", "Burlingame, CA")
        aliases = st.text_input("Other spellings (comma separated)", "Good Thing Coffee")

        c4, c5, c6 = st.columns(3)
        provider = c4.selectbox("Model", ["demo", "gemini", "openai", "claude"])
        n_questions = c5.slider("Questions", 5, 20, 10)
        runs = c6.slider("Runs per question", 1, 3, 2)

        if provider == "demo" or has_key(provider):
            api_key = ""
            st.caption("Key already configured. No need to enter one.")
        else:
            api_key = st.text_input("API key", type="password")
        go = st.form_submit_button("Run check")

    if go:
        if provider != "demo" and not api_key and not has_key(provider):
            st.error("That model needs an API key. Pick 'demo' to try it without one.")
            st.stop()

        env_var = {"gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY",
                   "claude": "ANTHROPIC_API_KEY"}.get(provider)
        if env_var and api_key:
            os.environ[env_var] = api_key

        total = n_questions * runs
        st.info(f"Making {total} API calls. This takes about {total * 2 // 60 + 1} minute(s).")

        with st.spinner("Asking the model..."):
            rows = run_check.run_business(
                name, category, city, [provider], runs=runs,
                aliases=[a.strip() for a in aliases.split(",") if a.strip()],
                num_questions=n_questions, verbose=False,
            )
            summary = run_check.summarize(rows, name)

        st.success("Done")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Visibility score", f"{score_color(summary['score'])} {summary['score']}")
        m2.metric("Mention rate", f"{summary['mention_rate']:.0%}")
        m3.metric("Avg position", summary["avg_position"] or "n/a")
        m4.metric("Consistency", summary["consistency"])

        if summary["errors"]:
            st.warning(f"{summary['errors']} call(s) failed and were skipped.")

        st.markdown("**Suggested next steps**")
        for i, tip in enumerate(summary["suggestions"], 1):
            st.markdown(f"{i}. {tip}")

        raw = pd.DataFrame(rows)
        with st.expander("See the actual AI answers"):
            st.dataframe(raw[["question", "run", "mentioned", "position",
                              "sentiment", "snippet"]],
                         use_container_width=True, hide_index=True)
        st.download_button("Download results as CSV", raw.to_csv(index=False).encode(),
                           file_name="geocheck_results.csv", mime="text/csv")
