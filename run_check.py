"""
run_check.py
------------
The conductor. This file doesn't do any thinking itself, it calls the other files
in order and saves the results.

    questions.py  makes the questions
    models.py     asks the AI models
    scoring.py    turns answers into numbers
    this file     loops over everything and writes the results

Run one business from the command line:
    python run_check.py --name "Goodthing Coffee" --category "coffee shop" \
        --city "Burlingame, CA" --providers gemini --runs 2 --questions 10
"""

import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import models
import questions as qbuilder
import scoring


def slugify(text: str) -> str:
    """Turn 'Goodthing Coffee' into 'goodthing-coffee' so it's safe in a filename."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def collect_answers(category, city, providers, runs=2, num_questions=10,
                    api_key=None, on_progress=None, max_failures_in_a_row=3,
                    demo_business=""):
    """
    Ask every question on every model, `runs` times each, and return the raw answers.

    This is the only function that spends API calls. The key design choice:
    the business name is never in the question, so ONE answer can be scored for
    ANY number of businesses afterward. Comparing 8 coffee shops costs the same
    as checking 1. The first version asked separately per business and would
    have needed 8x the calls, which the free tier can't cover.

    on_progress: called after every call as on_progress(done, total), so the web
                 app can move a progress bar.
    max_failures_in_a_row: three failures back to back means something is really
                 broken, so stop and show the error instead of grinding on.
    """
    question_list = qbuilder.build_questions(category, city, limit=num_questions)
    answers = []
    total = len(question_list) * len(providers) * runs
    done = 0
    failures_in_a_row = 0

    for question in question_list:
        for provider in providers:
            for run in range(1, runs + 1):
                done += 1
                try:
                    answer = models.ask(provider, question, business_name=demo_business,
                                        run=run, api_key=api_key)
                    error = ""
                    failures_in_a_row = 0
                except models.ModelError:
                    # Bad key, daily limit used up on every model, etc. Every other
                    # call would fail the same way, so stop now with the real reason.
                    raise
                except Exception as e:
                    answer, error = "", str(e)
                    failures_in_a_row += 1
                    if failures_in_a_row >= max_failures_in_a_row:
                        raise models.ModelError(
                            f"Stopped after {failures_in_a_row} failed calls in a row. "
                            f"Last error: {e}")

                answers.append({
                    "question": question,
                    "provider": provider,
                    "model": models.model_id(provider),
                    "run": run,
                    "answer": answer,
                    "error": error,
                    "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                })
                if on_progress:
                    on_progress(done, total)
    return answers


def score_answers(answers, name, aliases=None):
    """
    Score a list of raw answers for one business. No API calls happen here,
    which is why scoring 8 businesses is free once the answers exist.
    """
    rows = []
    for a in answers:
        found = scoring.find_mention(a["answer"], name, aliases)
        label, value = scoring.score_sentiment(found["snippet"])
        rows.append({
            "business": name,
            "question": a["question"],
            "provider": a["provider"],
            "model": a["model"],
            "run": a["run"],
            "mentioned": found["mentioned"],
            "position": found["position"],
            "total_items": found["total"],
            "position_score": round(scoring.position_score(found["position"], found["total"]), 3),
            "sentiment": label,
            "sentiment_value": value,
            "snippet": found["snippet"][:300],
            "answer": a["answer"],
            "error": a["error"],
            "timestamp": a["timestamp"],
        })
    return rows


def run_business(name, category, city, providers, runs=2, aliases=None,
                 num_questions=10, verbose=True, on_progress=None,
                 max_failures_in_a_row=3, api_key=None):
    """Check one business: collect answers, then score them for that business."""
    answers = collect_answers(category, city, providers, runs=runs,
                              num_questions=num_questions, api_key=api_key,
                              on_progress=on_progress,
                              max_failures_in_a_row=max_failures_in_a_row,
                              demo_business=name)
    return score_answers(answers, name, aliases)


def summarize(rows, name):
    """Roll one business's rows up into the headline numbers plus advice."""
    usable = [r for r in rows if not r["error"]]   # failed calls aren't evidence either way
    summary = scoring.visibility_score(usable)
    cons = scoring.consistency(usable)
    summary["business"] = name
    summary["consistency"] = cons["label"]
    summary["consistency_spread"] = cons["spread"]
    summary["errors"] = len(rows) - len(usable)
    summary["suggestions"] = scoring.suggestions(summary, cons)

    # Per-model breakdown. Two models given the same question often disagree,
    # and that disagreement is a finding in itself.
    by_model = {}
    for r in usable:
        by_model.setdefault(r["model"], []).append(r)
    summary["by_model"] = {m: scoring.visibility_score(rs) for m, rs in by_model.items()}
    return summary


def build_study(target, category, city, providers, runs=2, num_questions=10,
                api_key=None, on_progress=None, competitors=8):
    """
    Answer the question a business owner actually has: "Who does AI recommend
    in my category and city, and where do I rank?"

    target: {"name": "Goodthing Coffee", "aliases": ["Good Thing Coffee"]}

    Step 1: collect answers (the only step that costs API calls).
    Step 2: pull out every business the AI named and keep the most-named ones.
            We don't pick the competitors. The answers do.
    Step 3: score the target and each discovered competitor on the SAME answers,
            so the comparison is apples to apples.
    """
    answers = collect_answers(category, city, providers, runs=runs,
                              num_questions=num_questions, api_key=api_key,
                              on_progress=on_progress, demo_business=target["name"])
    texts = [a["answer"] for a in answers if not a["error"]]

    businesses = [{"name": target["name"], "aliases": target.get("aliases", []), "is_target": True}]
    for name, _count in scoring.top_recommended(texts, limit=competitors + 3):
        # Skip the target itself if the AI named it (it's already on the list).
        if scoring.find_mention(name, target["name"], target.get("aliases"))["mentioned"]:
            continue
        businesses.append({"name": name, "aliases": [], "is_target": False})
        if len(businesses) > competitors:
            break

    all_rows, summaries = [], []
    for biz in businesses:
        rows = score_answers(answers, biz["name"], biz["aliases"])
        all_rows.extend(rows)
        summary = summarize(rows, biz["name"])
        summary["is_target"] = biz["is_target"]
        summaries.append(summary)

    summaries.sort(key=lambda s: s["score"], reverse=True)
    study = {
        "target": target["name"],
        "category": category,
        "city": city,
        "providers": providers,
        "models_used": sorted({a["model"] for a in answers if not a["error"]}),
        "runs": runs,
        "questions": num_questions,
        "api_calls": len(answers),
        "failed_calls": sum(1 for a in answers if a["error"]),
        "run_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "results": summaries,
    }
    return study, all_rows


def save_study(study, rows, folder="."):
    """Two files: the summary the app reads, and every answer for anyone who wants proof."""
    with open(os.path.join(folder, "study_results.json"), "w", encoding="utf-8") as f:
        json.dump(study, f, indent=2)
    with open(os.path.join(folder, "study_answers.csv"), "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def print_report(summary):
    s = summary
    print()
    print("=" * 58)
    print(f"  {s['business']}")
    print("=" * 58)
    print(f"  Visibility Score   {s['score']} / 100")
    print(f"  Mentioned in       {s['mentions']} of {s['runs']} answers "
          f"({s['mention_rate'] * 100:.0f}%)")
    print(f"  Average position   {s['avg_position'] if s['avg_position'] else 'n/a'}")
    print(f"  Average sentiment  {s['avg_sentiment']}  (0 = negative, 1 = positive)")
    print(f"  Consistency        {s['consistency']} (spread {s['consistency_spread']})")
    if s["errors"]:
        print(f"  Failed calls       {s['errors']}")
    print("\n  By model:")
    for m, ms in s["by_model"].items():
        print(f"    {m:<24} score {ms['score']:<6} mention rate {ms['mention_rate'] * 100:.0f}%")
    print("\n  What to do about it:")
    for i, tip in enumerate(s["suggestions"], 1):
        print(f"    {i}. {tip}")
    print()


def main():
    ap = argparse.ArgumentParser(description="Measure a business's AI search visibility.")
    ap.add_argument("--name", required=True)
    ap.add_argument("--category", required=True)
    ap.add_argument("--city", required=True)
    ap.add_argument("--providers", default="demo", help="comma separated: demo,gemini,openai,claude")
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--questions", type=int, default=10)
    ap.add_argument("--aliases", default="")
    args = ap.parse_args()

    providers = [p.strip() for p in args.providers.split(",") if p.strip()]
    aliases = [a.strip() for a in args.aliases.split(",") if a.strip()]
    rows = run_business(args.name, args.category, args.city, providers, runs=args.runs,
                        aliases=aliases, num_questions=args.questions)
    print_report(summarize(rows, args.name))


if __name__ == "__main__":
    main()
