"""
run_study.py
------------
Compare several businesses from the command line, using one shared set of answers.

    python run_study.py --config study.json --providers gemini --runs 2 --questions 10

That's 20 API calls total. The competitors are discovered from the answers
themselves, and each answer gets scored for every business at no extra cost.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import run_check


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="study.json")
    ap.add_argument("--providers", default="demo")
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--questions", type=int, default=10)
    args = ap.parse_args()

    with open(args.config) as f:
        cfg = json.load(f)
    providers = [p.strip() for p in args.providers.split(",") if p.strip()]

    study, rows = run_check.build_study(cfg["target"], cfg["category"], cfg["city"],
                                        providers, runs=args.runs, num_questions=args.questions,
                                        on_progress=lambda d, t: print(f"  {d}/{t}", end="\r"))
    run_check.save_study(study, rows)

    print(f"\nLEADERBOARD: {study['category']} in {study['city']} "
          f"({study['api_calls']} API calls, models: {', '.join(study['models_used'])})")
    for i, s in enumerate(study["results"], 1):
        print(f"  {i}. {s['business']:<28} {s['score']:>5} / 100   "
              f"({s['mention_rate'] * 100:.0f}% mention rate)")
    print("\nSaved study_results.json and study_answers.csv")


if __name__ == "__main__":
    main()
