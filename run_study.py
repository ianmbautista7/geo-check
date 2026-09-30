"""
run_study.py
------------
Runs the same check across several businesses so you can compare them.

This is what produces the published study. One business alone gives you a
number with no context. Eight businesses in the same city, asked the exact
same questions, gives you a ranking, which is the thing people actually
want to look at.

Run it like this:
    python src/run_study.py --config study.json --providers gemini --runs 3
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import run_check


def main():
    ap = argparse.ArgumentParser(description="Run the visibility check on several businesses.")
    ap.add_argument("--config", required=True, help="JSON file listing the businesses")
    ap.add_argument("--providers", default="demo")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--questions", type=int, default=20)
    args = ap.parse_args()

    with open(args.config) as f:
        cfg = json.load(f)

    providers = [p.strip() for p in args.providers.split(",") if p.strip()]
    category = cfg["category"]
    city = cfg["city"]
    all_summaries = []

    for biz in cfg["businesses"]:
        name = biz["name"]
        aliases = biz.get("aliases", [])
        print(f"\n--- {name} ---")
        rows = run_check.run_business(name, category, city, providers,
                                      runs=args.runs, aliases=aliases,
                                      num_questions=args.questions)
        summary = run_check.summarize(rows, name)
        run_check.save(rows, summary)
        run_check.print_report(summary)
        all_summaries.append(summary)

    # Sort best to worst so the leaderboard is ready to display.
    all_summaries.sort(key=lambda s: s["score"], reverse=True)

    os.makedirs("data", exist_ok=True)
    out = {"category": category, "city": city,
           "providers": providers, "runs": args.runs,
           "questions": args.questions, "results": all_summaries}
    with open("data/study.json", "w") as f:
        json.dump(out, f, indent=2)

    print("\n" + "=" * 58)
    print(f"  LEADERBOARD: {category} in {city}")
    print("=" * 58)
    for i, s in enumerate(all_summaries, 1):
        print(f"  {i}. {s['business']:<28} {s['score']:>5} / 100   "
              f"({s['mention_rate'] * 100:.0f}% mention rate)")
    print("\nSaved data/study.json")


if __name__ == "__main__":
    main()
