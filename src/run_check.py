"""
run_check.py
------------
The conductor. This file doesn't do any thinking itself, it calls the other files
in order and saves the results.

The flow:
    questions.py  makes the questions
    models.py     asks the AI models
    scoring.py    turns answers into numbers
    this file     loops over everything and writes the CSV

Run it like this:
    python src/run_check.py --name "Goodthing Coffee" --category "coffee shop" \
        --city "Burlingame, CA" --providers gemini --runs 3
"""

import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))

import models
import questions as qbuilder
import scoring


def slugify(text: str) -> str:
    """Turn 'Goodthing Coffee' into 'goodthing-coffee' so it's safe in a filename."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def run_business(name, category, city, providers, runs=3, aliases=None,
                 num_questions=20, verbose=True):
    """
    Ask every question, on every model, the given number of times.

    The three nested loops are the heart of the tool:
        for each question
          for each model
            for each run

    So 20 questions x 2 models x 3 runs = 120 API calls. That number is why
    the PRD cares about cost. Each loop you add multiplies the bill.

    Returns a list of row dicts, one per API call.
    """
    question_list = qbuilder.build_questions(category, city, limit=num_questions)
    rows = []
    total = len(question_list) * len(providers) * runs
    done = 0

    for question in question_list:
        for provider in providers:
            for run in range(1, runs + 1):
                done += 1
                try:
                    answer = models.ask(provider, question, business_name=name, run=run)
                    error = ""
                except Exception as e:
                    # One failed call should not kill a 120-call job. We record
                    # the failure and keep going, then report how many failed.
                    answer, error = "", str(e)

                found = scoring.find_mention(answer, name, aliases)
                label, value = scoring.score_sentiment(found["snippet"])

                rows.append({
                    "business": name,
                    "question": question,
                    "provider": provider,
                    "model": models.model_id(provider),
                    "run": run,
                    "mentioned": found["mentioned"],
                    "position": found["position"],
                    "total_items": found["total"],
                    "position_score": round(
                        scoring.position_score(found["position"], found["total"]), 3),
                    "sentiment": label,
                    "sentiment_value": value,
                    "snippet": found["snippet"][:300],
                    "answer": answer,
                    "error": error,
                    "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                })

                if verbose and done % 10 == 0:
                    print(f"  {done}/{total} calls done", flush=True)

    return rows


def summarize(rows, name):
    """Roll the rows up into the headline numbers plus advice."""
    summary = scoring.visibility_score(rows)
    cons = scoring.consistency(rows)
    summary["business"] = name
    summary["consistency"] = cons["label"]
    summary["consistency_spread"] = cons["spread"]
    summary["errors"] = sum(1 for r in rows if r["error"])
    summary["suggestions"] = scoring.suggestions(summary, cons)

    # Per-model breakdown. This is the interesting part: two models given the
    # same question often disagree, and that disagreement is a finding.
    by_provider = {}
    for r in rows:
        by_provider.setdefault(r["provider"], []).append(r)
    summary["by_provider"] = {
        p: scoring.visibility_score(rs) for p, rs in by_provider.items()
    }
    return summary


def save(rows, summary, outdir="data"):
    """Write one CSV of every answer and one JSON of the summary."""
    os.makedirs(outdir, exist_ok=True)
    slug = slugify(summary["business"])

    csv_path = os.path.join(outdir, f"results_{slug}.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    json_path = os.path.join(outdir, f"summary_{slug}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    return csv_path, json_path


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
    print()
    print("  By model:")
    for p, ps in s["by_provider"].items():
        print(f"    {p:<10} score {ps['score']:<6} mention rate "
              f"{ps['mention_rate'] * 100:.0f}%")
    print()
    print("  What to do about it:")
    for i, tip in enumerate(s["suggestions"], 1):
        print(f"    {i}. {tip}")
    print()


def main():
    ap = argparse.ArgumentParser(description="Measure a business's AI search visibility.")
    ap.add_argument("--name", required=True, help='e.g. "Goodthing Coffee"')
    ap.add_argument("--category", required=True, help='e.g. "coffee shop"')
    ap.add_argument("--city", required=True, help='e.g. "Burlingame, CA"')
    ap.add_argument("--providers", default="demo",
                    help="comma separated: demo,gemini,openai,claude")
    ap.add_argument("--runs", type=int, default=3, help="repeat runs per question")
    ap.add_argument("--questions", type=int, default=20)
    ap.add_argument("--aliases", default="",
                    help='comma separated other spellings, e.g. "Good Thing Coffee"')
    args = ap.parse_args()

    providers = [p.strip() for p in args.providers.split(",") if p.strip()]
    aliases = [a.strip() for a in args.aliases.split(",") if a.strip()]

    print(f"Checking {args.name} on {', '.join(providers)} "
          f"({args.questions} questions x {args.runs} runs)")

    rows = run_business(args.name, args.category, args.city, providers,
                        runs=args.runs, aliases=aliases, num_questions=args.questions)
    summary = summarize(rows, args.name)
    csv_path, json_path = save(rows, summary)
    print_report(summary)
    print(f"Saved {csv_path} and {json_path}")


if __name__ == "__main__":
    main()
